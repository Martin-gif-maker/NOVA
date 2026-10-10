# win_schedule.py — runs the scheduled tasks (repeating reminders, requests sent at set times).
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import logging
from PySide6.QtCore import QTimer
import paths
import schedule as sched
import tools as computer_tools
import platform_utils as plat
from i18n import tr
from dialogs import ScheduleDialog, schedule_when

log = logging.getLogger("nova")


class ScheduleMixin:
    def _start_scheduler(self):
        self._sched_timer = QTimer(self); self._sched_timer.timeout.connect(self._check_schedule)
        self._sched_timer.start(20_000)
        QTimer.singleShot(5000, self._check_schedule)        # tasks that came due while NOVA was closed (same day)

    def _check_schedule(self, now=None):
        """Run what is due. Requests wait while NOVA is busy; one request per check."""
        if self._quitting or self._wiped: return
        try:
            with computer_tools._sched_lock:
                tasks = sched.load(paths.SCHEDULE_FILE)
                if not tasks: return
                kept = sched.expired(tasks, now)
                todo = sched.due(kept, now)
                run = []
                for task in todo:
                    if task["kind"] == "ask":
                        if self._busy or not self.client or any(t["kind"] == "ask" for t in run): continue    # next check
                    run.append(task); kept = sched.mark_run(kept, task, now)
                if run or len(kept) != len(tasks): sched.save(paths.SCHEDULE_FILE, kept)
        except Exception as e:
            log.warning("schedule check failed: %s", e); return
        for task in run:
            self._run_scheduled(task)

    def _run_scheduled(self, task: dict):
        text = task["text"]
        log.info("scheduled %s: %s", task["kind"], text[:80])
        if task["kind"] == "reminder":
            plat.notify("NOVA", text, ms=8000)
            self._on_reminder(text)
            return
        self.chat_area.add_message(tr("⏰  Scheduled ({}):").format(schedule_when(task)), "system", self._theme)
        self._last_user_msg = text
        self.chat_area.add_message(text, "user", self._theme)
        self.messages.append({"role": "user", "content": text})
        self._update_ctx_counter()
        self._refresh_prompt(text)
        self._start_ai()

    def _show_schedule(self):
        ScheduleDialog(self._theme, paths.SCHEDULE_FILE, computer_tools._sched_lock, self).exec()
