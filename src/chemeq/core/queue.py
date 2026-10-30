"""Small in-process grading queue.

A single teacher does not need Celery/Redis.  A bounded number of worker threads
pull submission IDs from a queue, call the VLM and persist the result.  On
startup, submissions left in ``processing`` by a crash are marked ``interrupted``
and re-queued.
"""

from __future__ import annotations

import queue
import threading

from .. import db
from ..config import Config
from .grade import ensure_db, transcribe_submission


class GradeQueue:
    def __init__(self, cfg: Config, workers: int | None = None):
        self.cfg = cfg
        self.workers = max(1, int(workers or cfg.max_concurrency))
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._started = False
        self._stopping = False

    def start(self) -> None:
        if self._started:
            return
        ensure_db(self.cfg)
        pending = db.pending_submissions(self.cfg.db_path)
        for submission_id in pending:
            submission = db.get_submission(self.cfg.db_path, submission_id)
            if submission and submission.get("status") == "processing":
                db.update_submission(
                    self.cfg.db_path, submission_id, status="interrupted", error="上次处理中断"
                )
            self._queue.put(submission_id)
        for index in range(self.workers):
            thread = threading.Thread(
                target=self._worker, name=f"chemeq-grader-{index + 1}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        self._started = True

    def submit(self, submission_id: int) -> None:
        if not self._started:
            self.start()
        self._queue.put(int(submission_id))

    def _worker(self) -> None:
        while True:
            submission_id = self._queue.get()
            try:
                if submission_id is None:
                    return
                if self._stopping:
                    return
                transcribe_submission(self.cfg, submission_id)
            except Exception as exc:  # keep the worker alive
                try:
                    db.update_submission(
                        self.cfg.db_path,
                        int(submission_id),
                        status="failed",
                        error=str(exc),
                        needs_review=1,
                    )
                    db.add_event(
                        self.cfg.db_path, "error", f"批改失败：{exc}", int(submission_id)
                    )
                except Exception:
                    pass
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        self._stopping = True
        for _ in self._threads:
            self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()
        self._started = False

    @property
    def pending(self) -> int:
        return self._queue.qsize()
