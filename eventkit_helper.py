# eventkit_helper.py — talks to the Mac's Calendar and Reminders (EventKit) in a separate, short-lived process.
#
# Why its own process: macOS decides per *launching app* whether calendar access may even be asked for, and
# ends a process that asks from the wrong place. Keeping EventKit out of NOVA's own process means the worst
# case is this helper stopping - NOVA then explains what to do instead of quitting.
#
#   request (JSON on stdin)  ->  answer (last stdout line, prefixed with MARK)
#     {"op": "events", "start": <epoch>, "end": <epoch>}
#     {"op": "add_event", "title", "start", "end", "all_day", "location", "notes", "calendar"}
#     {"op": "reminders", "limit": 50}
#     {"op": "add_reminder", "title", "due": <epoch or null>, "notes", "list"}
import sys, json, threading

MARK = "@@NOVA-EVENTKIT@@"
ASK_TIMEOUT = 110            # how long the user gets to answer the macOS permission question

DENIED = {"event": "Calendar access is off for NOVA. Turn it on in System Settings → Privacy & Security → Calendars.",
          "reminder": "Reminders access is off for NOVA. Turn it on in System Settings → Privacy & Security → Reminders."}


class Refused(Exception):
    pass


def _access(EK, store, kind: str, need_read: bool = True) -> None:
    """Make sure we may use calendars / reminders; asks the user the first time. Raises Refused."""
    etype = EK.EKEntityTypeEvent if kind == "event" else EK.EKEntityTypeReminder
    status = int(EK.EKEventStore.authorizationStatusForEntityType_(etype))
    if status == 3: return                                   # full access
    if status == 4 and not need_read: return                 # write-only is enough to add things
    if status in (1, 2, 4): raise Refused(DENIED[kind])      # restricted / denied / write-only when reading
    done = threading.Event(); answer = {}

    def _cb(granted, error):
        answer["granted"] = bool(granted); done.set()
    if kind == "event": store.requestFullAccessToEventsWithCompletion_(_cb)
    else: store.requestFullAccessToRemindersWithCompletion_(_cb)
    if not done.wait(ASK_TIMEOUT): raise Refused("The permission question was not answered in time. Ask again and choose Allow.")
    if not answer.get("granted"): raise Refused(DENIED[kind])


def _date(ts: float):
    from Foundation import NSDate
    return NSDate.dateWithTimeIntervalSince1970_(float(ts))


def _calendar_named(store, EK, kind: str, name: str):
    etype = EK.EKEntityTypeEvent if kind == "event" else EK.EKEntityTypeReminder
    want = (name or "").strip().lower()
    if want:
        for c in store.calendarsForEntityType_(etype) or []:
            if str(c.title()).lower() == want and c.allowsContentModifications(): return c
    return store.defaultCalendarForNewEvents() if kind == "event" else store.defaultCalendarForNewReminders()


def handle(req: dict) -> dict:
    import EventKit as EK
    store = EK.EKEventStore.alloc().init()
    op = req.get("op")
    if op == "events":
        _access(EK, store, "event")
        pred = store.predicateForEventsWithStartDate_endDate_calendars_(_date(req["start"]), _date(req["end"]), None)
        out = []
        for e in store.eventsMatchingPredicate_(pred) or []:               # repeating events are expanded for us
            out.append({"title": str(e.title() or ""), "start": e.startDate().timeIntervalSince1970(),
                        "end": e.endDate().timeIntervalSince1970(), "all_day": bool(e.isAllDay()),
                        "calendar": str(e.calendar().title() or "") if e.calendar() else "",
                        "location": str(e.location() or "")})
        out.sort(key=lambda x: x["start"])
        return {"ok": True, "events": out[:200]}
    if op == "add_event":
        _access(EK, store, "event", need_read=False)
        cal = _calendar_named(store, EK, "event", req.get("calendar", ""))
        if cal is None: raise Refused("There is no calendar that new events can be added to.")
        ev = EK.EKEvent.eventWithEventStore_(store)
        ev.setTitle_(str(req["title"])); ev.setStartDate_(_date(req["start"])); ev.setEndDate_(_date(req["end"]))
        ev.setAllDay_(bool(req.get("all_day"))); ev.setCalendar_(cal)
        if req.get("location"): ev.setLocation_(str(req["location"]))
        if req.get("notes"): ev.setNotes_(str(req["notes"]))
        ok, err = store.saveEvent_span_error_(ev, EK.EKSpanThisEvent, None)
        if not ok: raise Refused(f"Calendar did not save the event: {err.localizedDescription() if err else 'unknown reason'}")
        return {"ok": True, "calendar": str(cal.title() or "")}
    if op == "reminders":
        _access(EK, store, "reminder")
        from Foundation import NSCalendar
        done = threading.Event(); found = []

        def _got(items):
            found.extend(items or []); done.set()
        store.fetchRemindersMatchingPredicate_completion_(
            store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, None), _got)
        if not done.wait(30): raise Refused("Reminders did not answer in time.")
        out = []
        for r in found:
            comps = r.dueDateComponents(); due = None
            if comps is not None:
                d = NSCalendar.currentCalendar().dateFromComponents_(comps)
                due = d.timeIntervalSince1970() if d is not None else None
            out.append({"title": str(r.title() or ""), "due": due, "list": str(r.calendar().title() or "") if r.calendar() else ""})
        out.sort(key=lambda x: (x["due"] is None, x["due"] or 0))
        return {"ok": True, "reminders": out[:int(req.get("limit", 50))], "total": len(out)}
    if op == "add_reminder":
        _access(EK, store, "reminder", need_read=False)
        from Foundation import NSCalendar
        cal = _calendar_named(store, EK, "reminder", req.get("list", ""))
        if cal is None: raise Refused("There is no reminder list that new reminders can be added to.")
        rem = EK.EKReminder.reminderWithEventStore_(store)
        rem.setTitle_(str(req["title"])); rem.setCalendar_(cal)
        if req.get("notes"): rem.setNotes_(str(req["notes"]))
        if req.get("due"):
            when = _date(req["due"])
            from Foundation import NSCalendarUnitYear, NSCalendarUnitMonth, NSCalendarUnitDay, NSCalendarUnitHour, NSCalendarUnitMinute
            units = NSCalendarUnitYear | NSCalendarUnitMonth | NSCalendarUnitDay | NSCalendarUnitHour | NSCalendarUnitMinute
            rem.setDueDateComponents_(NSCalendar.currentCalendar().components_fromDate_(units, when))
            rem.addAlarm_(EK.EKAlarm.alarmWithAbsoluteDate_(when))              # so it actually notifies
        ok, err = store.saveReminder_commit_error_(rem, True, None)
        if not ok: raise Refused(f"Reminders did not save it: {err.localizedDescription() if err else 'unknown reason'}")
        return {"ok": True, "list": str(cal.title() or "")}
    return {"ok": False, "error": f"unknown request {op!r}"}


def main(argv=None) -> int:
    try:
        answer = handle(json.loads(sys.stdin.read() or "{}"))
    except Refused as e:
        answer = {"ok": False, "error": str(e), "refused": True}
    except BaseException as e:
        answer = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write("\n" + MARK + json.dumps(answer, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
