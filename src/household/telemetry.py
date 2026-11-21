"""Per-request timing with a heartbeat independent of the executing graph thread."""

import json
import logging
import threading
import time
from contextlib import contextmanager, nullcontext

from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger("household.progress")


class JobTrace:
    def __init__(self, job_id, *, interval=5, slow_seconds=10, clock=time.monotonic):
        self.job_id = str(job_id)
        self.interval = interval
        self.slow_seconds = slow_seconds
        self.clock = clock
        self.started = clock()
        self.active = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, name="job-progress", daemon=True)

    def emit(self, event, *, warning=False, **fields):
        # Callers supply operation labels and IDs only, never SQL parameters or prompts.
        logger.log(
            logging.WARNING if warning else logging.INFO,
            json.dumps({"event": event, "job_id": self.job_id, **fields}),
        )

    @contextmanager
    def stage(self, name, **fields):
        token = object()
        started = self.clock()
        with self.lock:
            self.active[token] = (name, started)
        self.emit("stage_started", stage=name, **fields)
        outcome = "success"
        error_fields = {}
        try:
            yield
        except BaseException as exc:
            outcome = "error"
            error_fields = {"error_type": type(exc).__name__}
            raise
        finally:
            elapsed = self.clock() - started
            with self.lock:
                self.active.pop(token, None)
            self.emit(
                "stage_finished",
                stage=name,
                elapsed_ms=round(elapsed * 1000),
                outcome=outcome,
                **fields,
                **error_fields,
            )

    def report_progress(self):
        now = self.clock()
        with self.lock:
            active = [
                {"stage": name, "elapsed_ms": round((now - started) * 1000)}
                for name, started in self.active.values()
            ]
        slow = any(s["elapsed_ms"] >= self.slow_seconds * 1000 for s in active)
        self.emit(
            "job_progress",
            warning=slow,
            elapsed_ms=round((now - self.started) * 1000),
            active_stages=active,
            slow=slow,
        )

    def _heartbeat(self):
        while not self.stopped.wait(self.interval):
            self.report_progress()

    def start(self):
        self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=1)


def stage(trace, name, **fields):
    return trace.stage(name, **fields) if trace is not None else nullcontext()


class TracedPostgresSaver(PostgresSaver):
    def __init__(self, conn, trace):
        super().__init__(conn)
        self.trace = trace

    def get_tuple(self, *args, **kwargs):
        with self.trace.stage("checkpoint.load"):
            return super().get_tuple(*args, **kwargs)

    def put(self, *args, **kwargs):
        with self.trace.stage("checkpoint.save"):
            return super().put(*args, **kwargs)

    def put_writes(self, *args, **kwargs):
        with self.trace.stage("checkpoint.write_tasks"):
            return super().put_writes(*args, **kwargs)
