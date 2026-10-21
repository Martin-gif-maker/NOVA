# win_account.py — the AI behind NOVA: which provider and models are used, the API key, first-run setup,
# and applying what was changed in Settings.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import os
import threading
import logging
from PySide6.QtWidgets import QLineEdit, QInputDialog, QDialog
from PySide6.QtCore import QTimer
import platform_utils as plat
import paths
import tts
from onboarding import OnboardingDialog
import models as model_registry
import providers
from i18n import tr
from keystore import _get_api_key, _save_api_key
from models import MODELS
from prompts import _build_prompt
from workers import WakeWordListener
from settings_dialog import SettingsDialog

log = logging.getLogger("nova")


class AccountMixin:
    # ── AI provider / client ─────────────────────────────────────
    def _provider(self) -> str:
        return self.config.get("provider", providers.DEFAULT_PROVIDER)

    def _activate_models(self):
        """Point the model slots at the configured provider (+ any models the user pinned)."""
        prov = self._provider()
        pinned = dict(self.config.get("models_by_provider", {}).get(prov, {}))
        if prov == "groq": pinned = {**self.config.get("models", {}), **pinned}       # legacy setting
        model_registry.activate(prov, pinned)

    def _needs_key(self, key: str) -> bool:
        return providers.info(self._provider())["needs_key"] and not key and not self.config.get("keyless")

    def _connect(self, key: str = None) -> bool:
        """(Re)create the AI client for the configured provider. On failure: no client and a clear message."""
        prov = self._provider()
        if key is None: key = _get_api_key(prov)
        try:
            self.client = providers.make_client(prov, key, self.config.get("base_url", ""))
            warm = getattr(self.client, "warm_up", None)
            if callable(warm):                     # the SDK loads in the background once the window is up
                QTimer.singleShot(250, lambda: threading.Thread(target=warm, daemon=True, name="sdk-warm-up").start())
            return True
        except Exception as e:
            self.client = None
            kind, _ = providers.classify_error(e)
            msg = tr("⚠️  No API key yet, so NOVA cannot answer. Choose ≡ → Change API key.") if kind == "auth" else f"⚠️  {e}"
            self.chat_area.add_message(msg, "system", self._theme)
            log.warning("could not create the %s client: %s", prov, e)
            return False

    def _store_key(self, key: str, provider: str = None):
        where = _save_api_key(key, provider or self._provider())
        if where == "file":
            self.chat_area.add_message(tr("🔑  Keychain unavailable — key saved to a private file."), "system", self._theme)
        elif not where:
            self.chat_area.add_message(tr("⚠️  Could not store the API key; you'll be asked again next launch."), "system", self._theme)
        return where

    def _run_onboarding(self, existing_key: str = "") -> str:
        """Show the first-run wizard. Returns the API key to use ('' if none / not needed)."""
        dlg = OnboardingDialog(self._theme, existing_key=bool(existing_key), parent=self,
                               provider=self._provider(), base_url=self.config.get("base_url", ""))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ch = dlg.choices()
            new_prov = ch.get("provider") or self._provider()
            if not self.config.get("onboarded"):                      # a brand-new user needs no "what's new" note
                self.config["seen_version"] = paths.__version__
            if new_prov != self._provider():
                existing_key = _get_api_key(new_prov)                 # a key saved earlier for that provider
            self.config.update(consent=True, onboarded=True, schema=paths.SCHEMA_VERSION,
                               wake_word=ch["wake_word"], tts_auto=ch["tts_auto"], provider=new_prov,
                               base_url=ch.get("base_url", self.config.get("base_url", "")),
                               keyless=bool(ch.get("keyless", False)))
            self._activate_models()
            if ch["api_key"]:
                existing_key = ch["api_key"]; self._store_key(existing_key, new_prov)
            self._save_config()
        return existing_key

    def _init_client(self):
        prov = self._provider()
        key = _get_api_key(prov)
        if not key and prov == "groq":
            key = self.config.get("groq_api_key", "").strip()      # legacy: key stored in config.json
            if key and _save_api_key(key, "groq"):
                self.config.pop("groq_api_key", None); self._save_config()
        if self._needs_key(key) or not self.config.get("onboarded"):
            key = self._run_onboarding(key)
        if self._needs_key(key):
            self.chat_area.add_message(tr("⚠️  No API key yet, so NOVA cannot answer. Choose ≡ → Change API key."), "system", self._theme)
            return
        if not self._connect(key): return
        if not any(m["role"] == "assistant" for m in self.messages):
            self.chat_area.add_message(
                tr("Hi, I'm NOVA. Ask me anything, or press + to see what I can do."),
                "assistant", self._theme, markdown=True)
        self._start_wake_listener()
        self._refresh_models()

    def _change_api_key(self, provider: str = None, parent=None) -> bool:
        """Ask for a key and store it for `provider` (default: the active one). True if a key was saved."""
        prov = provider or self._provider(); name = providers.label(prov)
        if not providers.info(prov)["needs_key"] and not providers.info(prov).get("needs_url"):
            self.chat_area.add_message(tr("🔑  {} does not use an API key.").format(name), "system", self._theme); return False
        key, ok = QInputDialog.getText(parent or self, tr("{} API key").format(name), tr("Enter new API key:"), QLineEdit.EchoMode.Password)
        if not (ok and key.strip()): return False
        key = key.strip()
        where = _save_api_key(key, prov)
        stored = {"keyring": tr("to {} ✓").format(plat.KEYSTORE_NAME), "file": tr("to a private file (keychain unavailable)"),
                  "": tr("for this session only (could not be stored!)")}[where]
        if prov != self._provider():                                    # a key for a provider not in use (yet)
            self.chat_area.add_message(tr("🔑  {} API key saved {}").format(name, stored), "system", self._theme); return True
        self.config.pop("groq_api_key", None); self.config["keyless"] = False; self._save_config()
        if self._connect(key):
            self.chat_area.add_message(tr("🔑  {} API key updated — saved {}").format(name, stored), "system", self._theme)
            self._apply_wake_setting(); self._refresh_models()
        return True

    def _change_search_key(self, parent=None):
        key, ok = QInputDialog.getText(parent or self, tr("Brave API key"), tr("Enter your Brave Search API key:"),
                                       QLineEdit.EchoMode.Password)
        if ok and key.strip():
            where = _save_api_key(key.strip(), "brave")
            self.chat_area.add_message(tr("🔑  Brave Search key saved ✓") if where else tr("⚠️  Could not store the Brave Search key."),
                                       "system", self._theme)

    def _ai_signature(self):
        prov = self._provider()
        return (prov, self.config.get("base_url", ""), tuple(sorted(self.config.get("models_by_provider", {}).get(prov, {}).items())))

    def _apply_provider_change(self, before: dict, parent=None) -> bool:
        """The provider / server / pinned models changed in Settings: reconnect. On failure, go back to `before`."""
        prov = self._provider()
        self.config["keyless"] = not providers.info(prov)["needs_key"]
        key = _get_api_key(prov)
        if self._needs_key(key):
            self.chat_area.add_message(tr("{} needs an API key.").format(providers.label(prov)), "system", self._theme)
            if not self._change_api_key(prov, parent): key = ""
            else: key = _get_api_key(prov) or ""
            if not key and self._needs_key(key):
                self.config.update(before); self._activate_models()
                self.chat_area.add_message(tr("Staying with {} — no key was entered.").format(providers.label(self._provider())),
                                           "system", self._theme)
                return False
        self._stop_wake_listener()
        self._activate_models(); self._available_models = set()
        if not self._connect(key or None):
            self.config.update(before); self._activate_models(); self._connect()
            self.chat_area.add_message(tr("Could not switch — staying with {}.").format(providers.label(self._provider())),
                                       "system", self._theme)
            return False
        self.chat_area.add_message(tr("✓ Now using {}").format(providers.label(prov)), "system", self._theme)
        self._refresh_models()
        return True

    # ── Settings ─────────────────────────────────────────────────
    def _show_settings(self):
        dlg = SettingsDialog(self.config, self._theme, self, available_models=model_registry.chat_models(self._available_models),
                             key_lookup=_get_api_key)
        dlg._mem_view_btn.clicked.connect(lambda: self._show_memories_dialog(dlg))
        dlg._mem_clear_btn.clicked.connect(lambda: self._clear_memories(dlg))
        dlg._data_export_btn.clicked.connect(lambda: self._export_data(dlg))
        dlg._data_folder_btn.clicked.connect(lambda: self._reveal(paths.DATA_DIR))
        dlg._data_logs_btn.clicked.connect(lambda: self._reveal(paths.LOG_DIR))
        dlg._data_wipe_btn.clicked.connect(lambda: self._wipe_data(dlg))
        dlg._setup_btn.clicked.connect(lambda: (dlg.reject(), QTimer.singleShot(0, self._rerun_setup)))
        dlg._update_btn.clicked.connect(self._check_updates)
        dlg._activity_btn.clicked.connect(lambda: self._open_activity_log(dlg))
        dlg._sent_btn.clicked.connect(lambda: self._show_sent_today(dlg))
        dlg._diag_btn.clicked.connect(self._copy_diagnostics)
        dlg._key_btn.clicked.connect(lambda: self._change_api_key(dlg._provider_cb.currentData(), dlg))
        dlg._search_key_btn.clicked.connect(lambda: self._change_search_key(dlg))
        dlg._mcp_btn.clicked.connect(lambda: self._show_mcp_dialog(dlg))
        dlg._usage_btn.clicked.connect(lambda: self._show_usage(dlg))
        if dlg.exec() != QDialog.DialogCode.Accepted or self._wiped: return
        vals = dlg.get_values()
        before = {k: self.config.get(k) for k in ("provider", "base_url", "models_by_provider", "keyless")}
        ai_before = self._ai_signature(); was_encrypted = bool(self.config.get("encrypt_data", False))
        sync_before = self.config.get("sync_folder", "")
        changed_model = vals["model_key"] != self._model_key
        tts.ENABLED  = vals["tts"]
        tts.VOICE    = vals["tts_voice"]
        tts.ENGINE   = vals["tts_engine"]
        self._model_key = vals["model_key"]
        WakeWordListener.THRESH = vals["wake_thresh"]
        self.config.update(vals)
        if self._ai_signature() != ai_before:
            self._apply_provider_change(before, self)
        if bool(self.config.get("encrypt_data", False)) != was_encrypted:
            self._apply_encryption_setting()
        if self.config.get("sync_folder", "") != sync_before:
            self.config["sync_status"] = ""
            if self.config.get("sync_folder"): self._start_sync()
            else:
                import sync
                sync.forget(self.config)
        self._theme_key = vals["theme"]
        self._theme = self._resolve_theme()
        self._apply_theme()                       # also re-applies fonts / scale
        self.chat_area.refresh_fonts()
        self.messages[0] = {"role": "system", "content": _build_prompt()}
        self._refresh_model_label()
        if changed_model:
            mid, lbl = MODELS[self._model_key]
            self.chat_area.add_message(tr("✓ Model: {} ({})").format(lbl, mid), "system", self._theme)
        if not plat.set_autostart(vals["autostart"], os.path.abspath(__file__), vals["start_hidden"]):
            self.chat_area.add_message(tr("⚠️  Could not change the launch-at-login setting."), "system", self._theme)
        self._stop_wake_listener(); self._apply_wake_setting()          # restart: engine / language may have changed
        self._apply_selection_setting()
        self._save_config()
        self.chat_area.add_message(tr("Settings saved."), "system", self._theme)

    def _rerun_setup(self):
        key = self._run_onboarding(_get_api_key(self._provider()))
        if self._needs_key(key): return
        if self._connect(key):
            self._refresh_model_label()
            self._apply_wake_setting(); self._refresh_models()

    # ── Models: notice retired ones ──────────────────────────────
    _MODEL_LIST_RETRY_MS = (30_000, 120_000)    # after a network error (at start-up the Wi-Fi may still be waking up)

    def _refresh_models(self, attempt: int = 0):
        client = self.client
        if client is None: return
        def _bg():
            try:
                available = model_registry.fetch_available(client)
            except Exception as e:
                log.info("model list unavailable: %s", e)
                if providers.classify_error(e)[0] in ("connection", "server"):
                    self._models_ready.emit(("retry", attempt))         # the window's timer tries again, not this thread
                return
            self._models_ready.emit((model_registry.reconcile(available), available))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_models(self, payload):
        if isinstance(payload, tuple) and payload[0] == "retry":
            if payload[1] < len(self._MODEL_LIST_RETRY_MS):
                self._later(self._MODEL_LIST_RETRY_MS[payload[1]], lambda: self._refresh_models(payload[1] + 1))
            return
        notes, available = payload if isinstance(payload, tuple) else (payload, None)
        if available is not None: self._available_models = set(available)       # offered in Settings → AI
        if not notes: return
        for n in notes: log.warning(n)
        self._refresh_model_label()
        self.chat_area.add_message("🔄  " + "; ".join(notes), "system", self._theme)
