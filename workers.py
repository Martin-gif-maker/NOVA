# workers.py — background threads: AI request, voice recording, wake word, vision, system stats.
import os, io, re, json, time, base64, tempfile, threading, logging
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Signal, QThread
import tools as computer_tools
import platform_utils as plat
from models import MODELS, fast_model_id
import models as model_registry
import providers
import speech
import schemas
from mdrender import _strip_think
from chatutil import compress_messages, _LENGTH_HINTS

from i18n import tr
log = logging.getLogger("nova")

_MODEL_COOLDOWN = {}          # model id -> time until which it is rate-limited (skip it, don't re-hit the 429)
# Read-only tools that can safely run side by side; anything else runs strictly in order.
# Action tools whose result only says "done ✓". When every call of a round is one of these and succeeded, and
# either the model already wrote its reply in the same message or the request was one plain command ("open
# Spotify", "volume up"), there is nothing left to ask the model: the request ends after one round instead of two,
# which halves its cost and its time. The reply is then the model's own words, or simply "Done.".
_ONE_ROUND = {"open_application", "open_url", "open_maps", "search_web", "open_in_explorer", "control_volume", "control_system",
              "control_spotify", "set_clipboard", "type_text_keyboard", "take_screenshot", "empty_recycle_bin", "save_note",
              "set_reminder", "save_memory", "schedule_task", "add_calendar_event", "add_apple_reminder", "draft_email",
              "draft_email_reply", "write_file"}

_PARALLEL_SAFE = {"search_web_and_read", "read_webpage", "get_weather", "get_system_stats", "get_battery",
                  "get_network_info", "list_processes", "read_notes", "read_memory", "read_file",
                  "search_files", "get_clipboard", "get_calendar_events", "list_apple_reminders",
                  "search_documents", "list_documents", "list_scheduled_tasks"}


def _shorten_tool_content(content: str, limit: int) -> str:
    """Trim a stored tool result without breaking its JSON envelope."""
    try:
        data = json.loads(content)
        key = "result" if "result" in data else "error"
        if isinstance(data.get(key), str) and len(data[key]) > limit:
            data[key] = data[key][:limit] + " …[shortened]"
        return json.dumps(data, ensure_ascii=False)
    except (ValueError, TypeError, AttributeError):
        return content[:limit] + " …[shortened]"


def _compact_history(messages: list) -> list:
    """Keep the current turn and the one before it intact; reduce older turns to plain text.
    (Tool output from the previous turn is kept - truncated - so NOVA can still refer back to it.)"""
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    last_user = users[-1] if users else -1
    keep_from = users[-2] if len(users) >= 2 else 0
    out = [messages[0]]
    for i, m in enumerate(messages[1:], 1):
        role, content = m.get("role"), m.get("content")
        if i >= last_user:
            out.append(m)
        elif i >= keep_from:                                  # previous turn: tool plumbing stays, tool output shortened
            if role == "tool" and isinstance(content, str) and len(content) > 800:
                m = dict(m); m["content"] = _shorten_tool_content(content, 800)
            out.append(m)
        elif role == "system" and isinstance(content, str):
            out.append(m)                                     # conversation summary
        elif role in ("user", "assistant") and isinstance(content, str) and content.strip() and not m.get("tool_calls"):
            out.append({"role": role, "content": content[:1500]})
    return out


class AIWorker(QThread):
    response_ready = Signal(str, list)
    tool_executing = Signal(str)
    error_occurred = Signal(str, str)       # (message, kind) - kind as in providers.classify_error
    chunk_ready    = Signal(str)
    usage_ready    = Signal(int, int)       # (prompt tokens, completion tokens) of this request
    tool_finished  = Signal(str, str, bool, str)   # (tool name, arguments, succeeded, result text)

    def __init__(self, client, messages, model_id, max_tokens=2048, compress=True, reasoning="low", untrusted="", groups=()):
        super().__init__()
        self.groups     = set(groups)  # on-demand tool groups already in use in this chat (see schemas.select_tools)
        self.untrusted  = untrusted    # the user's message itself carries outside text (a file, a selection): say where from
        self.client     = client
        self.messages   = messages
        self.model_id   = model_id
        self.max_tokens = max_tokens   # completion-length budget for this request
        self.compress   = compress
        self.reasoning  = reasoning    # gpt-oss "thinking" effort: low = fastest
        self._cancelled = False
        self._tok_in = self._tok_out = 0
        self._round_in = 0             # prompt tokens of the latest model call (the next one costs about as much)

    def cancel(self):
        """Ask the worker to stop at the next chunk / between tools (it emits nothing afterwards)."""
        self._cancelled = True

    def _stream(self, messages, tools=None, max_tokens=None):
        if max_tokens is None: max_tokens = self.max_tokens
        kwargs = dict(model=self.model_id, messages=messages,
                      max_tokens=max_tokens, temperature=0.7, stream=True)
        if self.reasoning: kwargs["reasoning_effort"] = self.reasoning     # each provider adapter maps or drops this
        if tools: kwargs["tools"] = tools; kwargs["tool_choice"] = "auto"
        return self.client.chat.completions.create(**kwargs)

    @staticmethod
    def _parse_args(raw: str):
        """dict of arguments, or None when the model sent invalid JSON."""
        if not raw.strip(): return {}
        try:
            args = json.loads(raw)
            return args if isinstance(args, dict) else None
        except Exception:
            return None

    @staticmethod
    def _retry_after(err: str):
        """Seconds Groq asks us to wait ('Please try again in 7.4s' / '1m3.5s'), or None."""
        return providers._retry_after_from_text(err)

    def _sleep(self, seconds: float) -> bool:
        """Interruptible sleep. False if cancelled."""
        for _ in range(int(seconds * 5) + 1):
            if self._cancelled: return False
            time.sleep(0.2)
        return True

    def _estimate(self, tools_: list) -> int:
        """Roughly how many tokens the next model call will cost (what the last round cost, or a guess from the size)."""
        if self._round_in: return self._round_in + 500
        size = sum(len(str(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or "")) for m in self.messages)
        return int((size + len(json.dumps(tools_ or []))) / 4.5) + 200

    def _make_room(self, need: int) -> bool:
        """Before a model call: if this model's per-minute allowance cannot take it, use the other model, or wait
        exactly as long as it takes - instead of sending a request that will be refused. False if cancelled."""
        have = providers.allowance(self.model_id)
        if have is None or have >= need: return True
        other = fast_model_id() if self.model_id != fast_model_id() else MODELS["smart"][0]
        if other != self.model_id:
            have_other = providers.allowance(other)
            if have_other is None or have_other >= need:
                log.info("allowance: %s has %d tokens, %d needed - using %s", self.model_id, have, need, other)
                self.model_id = other
                return True
        wait, wait_other = providers.wait_for(self.model_id, need), (providers.wait_for(other, need) if other != self.model_id else 1e9)
        if wait_other < wait: self.model_id, wait = other, wait_other
        wait = min(wait, 30.0) + 0.3
        log.info("allowance: waiting %.1fs for %d tokens on %s", wait, need, self.model_id)
        self.tool_executing.emit(tr("⏳  Rate limit — retrying in {}s").format(f"{max(1, round(wait))}"))
        return self._sleep(wait)

    def _tools_now(self) -> list:
        """The tool definitions for the next model call: always-on tools plus the groups this chat is about."""
        asked = [m["content"] for m in self.messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
        recent = " ".join(asked[-2:])                        # this request and the one before it ("…and now louder")
        tools_, self.groups = schemas.select_tools(recent[-3000:], self.groups | computer_tools.REQUESTED_GROUPS)
        return tools_

    def _run_tools(self, tcs):
        """Execute this round's tool calls; read-only batches run in parallel, the rest in order."""
        parsed = [(tc, self._parse_args(tc["args"])) for tc in tcs]
        for tc, fargs in parsed:
            shown = ", ".join(f"{k}={repr(v)[:60]}" for k, v in (fargs or {}).items())
            self.tool_executing.emit(f"⚙️  {tc['name']}({shown})")

        def _one(item):
            tc, fargs = item
            if self._cancelled:
                return computer_tools.ToolResult(tc["name"], fargs or {}, False, "Cancelled.")
            if fargs is None:
                return computer_tools.ToolResult(tc["name"], {}, False,
                    "The tool arguments were not valid JSON. Call the tool again with valid arguments.")
            return computer_tools.run_tool(tc["name"], fargs)

        if len(parsed) > 1 and all(tc["name"] in _PARALLEL_SAFE for tc, _ in parsed):
            with ThreadPoolExecutor(max_workers=min(len(parsed), 4)) as pool:
                results = list(pool.map(_one, parsed))
        else:
            results = [_one(it) for it in parsed]
        for (tc, _), res in zip(parsed, results):
            self.messages.append({"role": "tool", "tool_call_id": tc["id"], "content": res.for_model()})
            try: shown = json.dumps({k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:200]) for k, v in res.args.items()},
                                    ensure_ascii=False)
            except (TypeError, ValueError): shown = "{}"
            self.tool_finished.emit(res.name, shown, res.ok, res.text[:600])
        return results

    _MORE_TO_SAY = re.compile(r"\b(and|then|also|after that|why|how|what|which|who|when|where|tell|explain|write|"
                              r"и|после|след това|също|защо|как|какво|кой|кога|къде|кажи|обясни|напиши)\b|[?,;:\n]", re.IGNORECASE)

    def _plain_command(self) -> bool:
        """Is the request one short command with nothing else asked ("open Spotify", "пусни следващата песен")?"""
        text = next((m["content"] for m in reversed(self.messages) if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        for hint in _LENGTH_HINTS:
            if text.endswith(hint): text = text[:-len(hint)]
        text = text.strip().rstrip(".!")
        return 0 < len(text.split()) <= 10 and not self._MORE_TO_SAY.search(text)

    def _done_in_one_round(self, content: str, tcs: list, results: list) -> str:
        """The final reply if this round already finished the request (see _ONE_ROUND), else ''."""
        if not (results and len(results) == len(tcs) and all(tc["name"] in _ONE_ROUND for tc in tcs)
                and all(r.ok and "✓" in r.text for r in results) and not computer_tools.is_tainted()):
            return ""
        if content.strip(): return content
        return tr("Done.") if self._plain_command() else ""

    def run(self):
        MAX_RETRY  = 4
        MAX_ROUNDS = 8   # max tool-call rounds before giving up
        t0 = time.monotonic(); ttft = None; rounds = 0
        computer_tools.begin_request()
        if self.untrusted: computer_tools.taint(self.untrusted)
        begin = getattr(self.client, "begin_request", None)
        if callable(begin): begin()                          # e.g. Claude: forget the previous tool loop's thinking blocks
        if self.model_id != fast_model_id() and time.time() < _MODEL_COOLDOWN.get(self.model_id, 0):
            log.info("%s is cooling down after a 429 - using %s", self.model_id, fast_model_id())
            self.model_id = fast_model_id()
            self.tool_executing.emit(tr("⚡  {} is rate-limited — using {}").format(MODELS['smart'][1], MODELS['fast'][1]))

        if self.compress and len(self.messages) >= 42:
            self.tool_executing.emit(tr("🗜  Compressing history…"))
            self.messages = compress_messages(self.client, self.model_id, self.messages)

        for attempt in range(MAX_RETRY):
            partial = False          # text of the current round already shown -> a retry would duplicate it
            try:
                for _round in range(MAX_ROUNDS):
                    if self._cancelled: return
                    partial = False; rounds += 1
                    tools_ = self._tools_now()
                    if not self._make_room(self._estimate(tools_)): return
                    stream = self._stream(self.messages, tools=tools_, max_tokens=self.max_tokens)
                    content, tc_acc, finish, refusal = "", {}, None, None

                    for chunk in stream:
                        if self._cancelled: return
                        u = getattr(getattr(chunk, "x_groq", None), "usage", None) or getattr(chunk, "usage", None)
                        if u:
                            self._round_in = int(getattr(u, "prompt_tokens", 0) or 0)
                            self._tok_in += self._round_in
                            self._tok_out += int(getattr(u, "completion_tokens", 0) or 0)
                        if not chunk.choices: continue
                        choice = chunk.choices[0]; delta = choice.delta
                        if getattr(choice, "finish_reason", None):
                            finish = choice.finish_reason
                            refusal = getattr(chunk, "refusal_category", None)
                        if delta is None: continue
                        if delta.content:
                            if ttft is None: ttft = time.monotonic() - t0
                            content += delta.content; partial = True
                            self.chunk_ready.emit(delta.content)
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                i = tc.index
                                if i not in tc_acc:
                                    tc_acc[i] = {"id": "", "name": "", "args": ""}
                                if tc.id: tc_acc[i]["id"] = tc.id
                                if tc.function:
                                    if tc.function.name:
                                        tc_acc[i]["name"] += tc.function.name
                                    if tc.function.arguments:
                                        tc_acc[i]["args"] += tc.function.arguments

                    content = _strip_think(content)

                    # ── The model (or its safety system) declined: never run that turn's tools ──
                    if finish == "content_filter":
                        note = tr("The AI declined this request. Try rephrasing it, or switch the model in the menu.")
                        if refusal: note += " " + tr("(Safety category: {})").format(refusal)
                        log.warning("refusal: model=%s category=%s", self.model_id, refusal)
                        self.messages.append({"role": "assistant", "content": note})
                        self.response_ready.emit(note, self.messages)
                        return
                    # ── Cut off mid tool call (token limit): a truncated call must not be executed ──
                    if tc_acc and finish == "length":
                        self.error_occurred.emit(tr("The reply was cut off before a tool call was complete. "
                                                    "Try again, or set the response length to Detailed."), "other")
                        return

                    # ── No tool calls → final response ───────────────────
                    if not tc_acc:
                        self.messages.append({"role": "assistant", "content": content})
                        log.info("reply ok: model=%s rounds=%d ttft=%s total=%.1fs msgs=%d tokens=%d/%d", self.model_id, rounds,
                                 f"{ttft:.1f}s" if ttft is not None else "-", time.monotonic() - t0, len(self.messages),
                                 self._tok_in, self._tok_out)
                        if self._tok_in or self._tok_out: self.usage_ready.emit(self._tok_in, self._tok_out)
                        self.response_ready.emit(content, self.messages)
                        return

                    # ── Tool calls requested ─────────────────────────────
                    tcs = [tc for _, tc in sorted(tc_acc.items())]
                    for n, tc in enumerate(tcs):
                        if not tc["id"]: tc["id"] = f"call_{_round}_{n}"
                    self.messages.append({
                        "role": "assistant", "content": content or "",
                        "tool_calls": [{"id": tc["id"], "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["args"] or "{}"}}
                            for tc in tcs]
                    })
                    results = self._run_tools(tcs)
                    if self._cancelled: return
                    final = self._done_in_one_round(content, tcs, results)
                    if final:
                        if not content.strip():                    # NOVA's own "Done." closes the turn in the history too
                            self.messages.append({"role": "assistant", "content": final})
                            self.chunk_ready.emit(final)
                        log.info("reply ok: model=%s rounds=%d (one round) total=%.1fs msgs=%d tokens=%d/%d", self.model_id, rounds,
                                 time.monotonic() - t0, len(self.messages), self._tok_in, self._tok_out)
                        if self._tok_in or self._tok_out: self.usage_ready.emit(self._tok_in, self._tok_out)
                        self.response_ready.emit(final, self.messages)
                        return
                    # Loop → NOVA will now respond to the tool results

                # Hit MAX_ROUNDS without a final answer
                note = tr("I stopped after {} steps without finishing. Try splitting the request into smaller ones.").format(MAX_ROUNDS)
                log.warning("max tool rounds reached: model=%s rounds=%d", self.model_id, rounds)
                self.messages.append({"role": "assistant", "content": note})
                self.response_ready.emit(note, self.messages)
                return

            except Exception as e:
                if self._cancelled: return
                err = str(e); kind, retry_after = providers.classify_error(e)
                if attempt < MAX_RETRY - 1 and not partial:
                    if kind == "rate_limit":
                        if self.model_id != fast_model_id():       # limits are per model: just use the other one
                            big = self.model_id
                            _MODEL_COOLDOWN[big] = time.time() + min(max(retry_after or 60, 20), 180)
                            self.model_id = fast_model_id()
                            log.warning("429 on %s -> switching to %s", big, fast_model_id())
                            self.tool_executing.emit(tr("⚡  {} is rate-limited — switching to {}").format(big.split('/')[-1], MODELS['fast'][1]))
                            continue
                        wait = min(retry_after or 5 * (attempt + 1), 20) + 0.5
                        log.warning("429 on %s, waiting %.1fs", self.model_id, wait)
                        self.tool_executing.emit(tr("⏳  Rate limit — retrying in {}s").format(f"{wait:.0f}"))
                        if not self._sleep(wait): return
                        continue
                    if kind in ("connection", "server", "tool_json"):
                        if not self._sleep(1.0 if kind != "server" else 2.0): return
                        continue
                self.error_occurred.emit(err, kind)
                return


# ──────────────────────────────────────────────────────────────────
#  Voice Recorder
# ──────────────────────────────────────────────────────────────────
class VoiceRecorder(QThread):
    text_ready = Signal(str)
    error      = Signal(str)
    silence    = Signal()       # nobody said anything within `idle_secs` (hands-free conversation uses this to end)
    MAX_SECS   = 60
    SILENCE_SECS = 1.6          # stop automatically this long after you finished speaking
    def __init__(self, client, language: str = "", auto_stop: bool = True, engine: str = "auto", idle_secs: float = 0):
        super().__init__(); self.client=client; self.language=language; self.auto_stop=auto_stop
        self.engine=engine          # auto | cloud | local (on this Mac)
        self.idle_secs=idle_secs    # > 0: give up when no speech starts within this many seconds
        self._stop=threading.Event()
    def stop(self): self._stop.set()
    def run(self):
        try:
            import sounddevice as sd, numpy as np
        except ImportError as e:
            self.error.emit(f"Missing: {e}"); return
        self._stop.clear(); fs=16000; frames=[]; max_frames=self.MAX_SECS*fs//512
        try:
            with sd.InputStream(samplerate=fs,channels=1,dtype="int16",blocksize=512) as s:
                noise=[]; thresh=None; loud=0; quiet=0; spoke=False; idle=False
                sil_chunks=int(self.SILENCE_SECS*fs/512)
                idle_chunks=int(self.idle_secs*fs/512) if self.idle_secs else 0
                while not self._stop.is_set() and len(frames) < max_frames:
                    d,_=s.read(512); frames.append(d.copy())
                    if not self.auto_stop: continue
                    if idle_chunks and not spoke and len(frames) > idle_chunks:
                        idle=True; break
                    rms=float(np.sqrt(np.mean(d.astype(np.float32)**2)))
                    if thresh is None:                              # first ~0.4 s calibrates the room's noise level
                        noise.append(rms)
                        if len(noise) >= 12: thresh=max(350.0, float(np.median(noise))*2.5)
                        continue
                    if rms > thresh:
                        loud+=1; quiet=0
                        if loud >= 3: spoke=True
                    else:
                        loud=0; quiet+=1
                    if spoke and quiet >= sil_chunks: break
        except Exception as e:
            self.error.emit(tr("Microphone error: {}\nAllow microphone access in System Settings → Privacy & Security → Microphone.").format(e)); return
        if idle and not self._stop.is_set():
            self.silence.emit(); return
        if not frames:
            self.error.emit(tr("No audio was captured.")); return
        audio=np.concatenate(frames)
        with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as f:
            speech.write_wav(f.name, fs, audio); fname=f.name
        try:
            text=speech.transcribe(self.client, fname, self.language, self.engine)
            if text: self.text_ready.emit(text)
            else: self.error.emit(tr("Nothing was recognised."))
        except Exception as e: self.error.emit(str(e))
        finally:
            try: os.unlink(fname)
            except OSError: pass


class BargeInMonitor(QThread):
    """Listens while NOVA is reading a reply aloud and fires when you start talking over it.

    With a `reference` (the loudness curve of the audio being played, see echo.py) the microphone is compared
    with what the loudspeakers should be producing at each moment, so NOVA's own voice coming back through
    the speakers is not mistaken for you. Without one, the first moments calibrate on what the microphone
    hears while NOVA speaks and only something clearly louder counts."""
    interrupted = Signal()
    HOLD_CHUNKS = 8                 # ≈ 0.25 s of sustained speech
    def __init__(self, reference=None, started: float = None, seed_gain: float = None):
        super().__init__(); self._stop = threading.Event()
        self.reference = reference; self.started = started; self.seed_gain = seed_gain
        self._gate = None
    def stop(self): self._stop.set()
    def learned_gain(self):
        """How loud NOVA's own voice reaches the microphone, once that is known (kept for the next reply)."""
        g = self._gate
        return g.gain if g is not None and g.learned() else None
    def run(self):
        try:
            import sounddevice as sd, numpy as np
        except ImportError:
            return
        gate = None
        try:
            with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=512) as s:
                if self.reference is not None and self.started is not None:
                    import echo
                    # where the playback is by now; a little early on purpose, so the echo is never "ahead" of it
                    offset = int((time.monotonic() - self.started) / echo.CHUNK_SECS) - 3
                    gate = self._gate = echo.EchoGate(self.reference, offset=offset, seed_gain=self.seed_gain)
                heard = []; thresh = None; loud = 0
                while not self._stop.is_set():
                    d, _ = s.read(512)
                    rms = float(np.sqrt(np.mean(d.astype(np.float32) ** 2)))
                    if gate is not None:
                        if gate.feed(rms):
                            if not self._stop.is_set(): self.interrupted.emit()
                            return
                        continue
                    if thresh is None:
                        heard.append(rms)
                        if len(heard) >= 20: thresh = max(900.0, float(np.percentile(heard, 90)) * 2.2)
                        continue
                    loud = loud + 1 if rms > thresh else 0
                    if loud >= self.HOLD_CHUNKS:
                        if not self._stop.is_set(): self.interrupted.emit()
                        return
        except Exception as e:
            log.info("barge-in monitor stopped: %s", e)


# ──────────────────────────────────────────────────────────────────
#  Wake Word Listener
# ──────────────────────────────────────────────────────────────────
class WakeWordListener(QThread):
    wake_detected  = Signal(str)
    error_occurred = Signal(str)
    WAKE_RE     = re.compile(r"\bnova\b", re.IGNORECASE)   # whole word only ("innovation" must not trigger)
    THRESH      = 700    # RMS threshold to count as loud
    CONSEC_REQ  = 3      # consecutive loud chunks needed before recording starts
    CHUNK       = 512
    RATE        = 16000
    MIN_SECS    = 0.6
    MAX_SECS    = 6
    SIL_SECS    = 1.3
    COOL        = 5      # seconds cooldown after a wake word

    def __init__(self, client, engine: str = "auto", language: str = ""):
        super().__init__(); self.client=client; self.language=language
        # "local": the word "nova" is spotted on this Mac and nothing is uploaded until it is heard.
        self.engine = "local" if engine in ("auto", "local") and speech.local_ready() else "cloud"
        self._running=True; self._paused=False; self._last=0.0
    def stop(self): self._running=False
    def pause(self): self._paused=True
    def resume(self): self._paused=False

    def run(self):
        if self.engine == "local":
            return self._run_local()
        return self._run_cloud()

    def _command_after_wake(self, pcm: bytes) -> str:
        """Text of the utterance that contained the wake word (on-device for English, else via the provider)."""
        if self.language in ("", "en") or not speech.cloud_available(self.client):
            return speech.transcribe_pcm(pcm)
        import wave
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp: path = tmp.name
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(speech.RATE); wf.writeframes(pcm)
            return speech.transcribe_cloud(self.client, path, self.language)
        finally:
            try: os.unlink(path)
            except OSError: pass

    def _run_local(self):
        """Fully on-device wake word: a recogniser that only knows "nova" listens; audio never leaves the Mac
        unless the wake word was heard AND the voice language needs the cloud recogniser."""
        try:
            import sounddevice as sd
            rec = speech.recognizer(speech.WAKE_GRAMMAR)
        except Exception as e:
            self.error_occurred.emit(tr("Wake word could not start ({}).").format(e)); return
        fails = 0
        while self._running:
            if self._paused: time.sleep(0.3); continue
            try:
                with sd.RawInputStream(samplerate=speech.RATE, channels=1, dtype="int16", blocksize=4000) as s:
                    fails = 0; utter = bytearray()
                    while self._running and not self._paused:
                        data, _ = s.read(4000); data = bytes(data)
                        utter += data
                        if len(utter) > speech.RATE * 2 * 12: del utter[:len(utter) - speech.RATE * 2 * 12]   # keep <= 12 s
                        if not rec.AcceptWaveform(data): continue
                        heard = json.loads(rec.Result()).get("text", "")
                        pcm, utter = bytes(utter), bytearray()
                        if not speech.heard_wake_word(heard) or time.time() - self._last < self.COOL: continue
                        try:
                            text = self._command_after_wake(pcm)
                        except Exception as e:
                            log.info("wake command could not be transcribed: %s", e); text = ""
                        m = self.WAKE_RE.search(text)
                        cmd = text[m.end():].strip(" ,.!?") if m else ""
                        self._last = time.time(); self.wake_detected.emit(cmd)
            except Exception as e:
                fails += 1
                if fails >= 3:
                    self.error_occurred.emit(
                        tr("Wake word disabled - cannot use the microphone ({}). Allow microphone "
                           "access in System Settings → Privacy & Security → Microphone.").format(e))
                    return
                time.sleep(2)

    def _run_cloud(self):
        if not speech.cloud_available(self.client):
            self.error_occurred.emit(tr("Wake word needs the offline voice model (Settings → Voice → Download) "
                                        "because this AI provider has no speech-to-text.")); return
        try:
            import sounddevice as sd, numpy as np
        except ImportError as e:
            self.error_occurred.emit(f"Wake word needs sounddevice: {e}"); return
        sil_c = int(self.SIL_SECS * self.RATE / self.CHUNK)
        max_c = int(self.MAX_SECS * self.RATE / self.CHUNK)
        min_c = int(self.MIN_SECS * self.RATE / self.CHUNK)
        fails = 0
        while self._running:
            if self._paused: time.sleep(0.3); continue
            try:
                rec = []; in_s = False; sil = 0; consec_loud = 0
                with sd.InputStream(samplerate=self.RATE, channels=1,
                                    dtype="int16", blocksize=self.CHUNK) as s:
                    fails = 0
                    while self._running and not self._paused:
                        d, _ = s.read(self.CHUNK)
                        rms = float(np.sqrt(np.mean(d.astype(np.float32) ** 2)))
                        if rms > self.THRESH:
                            consec_loud += 1
                            # Only start recording after CONSEC_REQ consecutive loud chunks
                            # — this filters out brief noise spikes that aren't speech
                            if consec_loud >= self.CONSEC_REQ:
                                in_s = True
                            if in_s:
                                rec.append(d.copy())
                            sil = 0
                        elif in_s:
                            consec_loud = 0; rec.append(d.copy()); sil += 1
                        else:
                            consec_loud = 0
                        if (in_s and len(rec) >= max_c) or (in_s and sil >= sil_c):
                            break
                if len(rec) < min_c or not self._running or self._paused: continue
                if time.time() - self._last < self.COOL: continue
                audio = np.concatenate(rec)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    speech.write_wav(tmp.name, self.RATE, audio); tp = tmp.name
                try:
                    heard = speech.transcribe_cloud(self.client, tp)
                    m = self.WAKE_RE.search(heard)
                    if m:
                        cmd = heard[m.end():].strip(" ,.!?")
                        self._last = time.time(); self.wake_detected.emit(cmd)
                except Exception as e: log.debug("wake word: this recording could not be transcribed: %s", e)
                finally:
                    try: os.unlink(tp)
                    except OSError: pass
            except Exception as e:            # microphone could not be opened / read
                fails += 1
                if fails >= 3:
                    self.error_occurred.emit(
                        tr("Wake word disabled - cannot use the microphone ({}). Allow microphone "
                           "access in System Settings → Privacy & Security → Microphone.").format(e))
                    return
                time.sleep(2)


# ──────────────────────────────────────────────────────────────────
#  Vision Worker  (screen or image file)
# ──────────────────────────────────────────────────────────────────
class VisionWorker(QThread):
    result_ready = Signal(str, str)      # (answer, note stored as the user turn)
    error        = Signal(str)
    def __init__(self, client, question, image_path=None, image=None):
        super().__init__(); self.client=client; self.image_path=image_path; self.image=image
        self.question=question or ("Analyze this image." if image_path else "Analyze the screen.")
    def run(self):
        try:
            from PIL import Image as Pil
            if self.image is not None:                    # already captured (and previewed) by the window
                img = self.image; note = f"[📷] {self.question}"
            elif self.image_path:
                img = Pil.open(self.image_path); note = f"[Image: {os.path.basename(self.image_path)}] {self.question}"
            else:
                if not plat.screen_capture_allowed(request=True):
                    self.error.emit(tr("Screen Recording permission is missing - allow it in System Settings → "
                                       "Privacy & Security → Screen Recording, then restart NOVA.")); return
                import pyautogui
                img = pyautogui.screenshot(); note = f"[📷] {self.question}"
            img = img.convert("RGB")                      # PNG/GIF with alpha or palette can't be saved as JPEG
            w,h=img.size
            if w>1280: img=img.resize((1280,int(h*1280/w)),Pil.Resampling.LANCZOS)
            buf=io.BytesIO(); img.save(buf,format="JPEG",quality=80)
            b64=base64.b64encode(buf.getvalue()).decode()
            msgs=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}},
                {"type":"text","text":self.question}]}]
            last_err = None; kind = "other"; wait = None
            for mid in model_registry.vision_models():   # fall back to the next vision model on limits / retirement
                try:
                    resp=self.client.chat.completions.create(model=mid, messages=msgs, max_tokens=1024)
                    text = resp.choices[0].message.content or ""
                    if getattr(resp.choices[0], "finish_reason", None) == "content_filter":
                        text = tr("The AI declined to analyse this image.")
                    self.result_ready.emit(text, note); return
                except Exception as e:
                    last_err = e; kind, wait = providers.classify_error(e)
                    low = str(e).lower()
                    if kind not in ("rate_limit", "not_found", "bad_request") and "model" not in low: break
                    log.warning("vision model %s failed (%s) - trying next", mid, str(e)[:120])
            if last_err is None:
                raise RuntimeError(tr("No image-capable model is available with this AI provider."))
            if kind == "rate_limit":
                raise RuntimeError(tr("Image analysis is rate-limited - try again in {}s.").format(f"{wait:.0f}") if wait
                                   else tr("Image analysis is rate-limited - try again shortly."))
            raise last_err
        except Exception as e: self.error.emit(str(e))




class StatsWorker(QThread):
    updated = Signal(str)
    paused  = False                 # set while the window is hidden (saves battery)
    def run(self):
        try:
            import psutil
            psutil.cpu_percent(interval=None)                 # prime: the next call reports usage since now
            while not self.isInterruptionRequested():
                for _ in range(20):                           # sample every 2 s, but notice "quit" within 0.1 s
                    if self.isInterruptionRequested(): return
                    self.msleep(100)
                if self.paused: continue
                cpu=psutil.cpu_percent(interval=None); ram=psutil.virtual_memory().percent
                self.updated.emit(f"CPU {cpu:.0f}%  ·  RAM {ram:.0f}%")
        except Exception as e: log.info("system statistics stopped: %s", e)
