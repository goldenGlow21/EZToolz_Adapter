"""Run slow work off the UI thread and bring its events back to it.

Tk widgets may only be touched from the thread that created them. Work such
as downloads, scans and tool runs therefore happens in background threads
that report through a queue, which the UI thread drains every 100 ms.

Installs and runs are exclusive: only one can be in progress, because both
change the tools folder or depend on it. Scans run alongside them.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable

_POLL_MS = 100
# Upper bound per poll so a chatty tool cannot freeze the window.
_EVENTS_PER_POLL = 500


@dataclass(frozen=True)
class _Finished:
    callback: Callable[[Any, BaseException | None], None]
    result: Any
    error: BaseException | None


class Worker:
    def __init__(self, root, dispatch: Callable[[object], None]):
        self._root = root
        self._dispatch = dispatch
        self._queue: queue.Queue = queue.Queue()
        self._busy_label: str | None = None
        self.cancel_event = threading.Event()
        self._after_id = root.after(_POLL_MS, self._poll)

    @property
    def busy_label(self) -> str | None:
        """What the exclusive task is doing, or None when idle."""
        return self._busy_label

    def start(self, label: str, work: Callable, done: Callable[[Any, BaseException | None], None]) -> bool:
        """Start the exclusive task; returns False if another one is running.

        work(report, cancel) runs in the background; done(result, error) runs on the UI thread.
        """
        if self._busy_label is not None:
            return False
        self._busy_label = label
        self.cancel_event = threading.Event()

        def finish(result, error):
            self._busy_label = None
            done(result, error)

        self._spawn(lambda: work(self._queue.put, self.cancel_event), finish)
        return True

    def background(self, work: Callable[[], Any], done: Callable[[Any, BaseException | None], None]) -> None:
        """Run a short, non-exclusive job such as a folder scan."""
        self._spawn(work, done)

    def cancel(self) -> None:
        self.cancel_event.set()

    def stop(self) -> None:
        """Stop polling; called when the window closes so no callback outlives it."""
        self._root.after_cancel(self._after_id)

    def _spawn(self, work, done) -> None:
        def body():
            try:
                result, error = work(), None
            except Exception as caught:  # handed to `done`, which shows it to the user
                traceback.print_exc()
                result, error = None, caught
            self._queue.put(_Finished(done, result, error))

        threading.Thread(target=body, daemon=True).start()

    def _poll(self) -> None:
        for _ in range(_EVENTS_PER_POLL):
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, _Finished):
                event.callback(event.result, event.error)
            else:
                self._dispatch(event)
        self._after_id = self._root.after(_POLL_MS, self._poll)
