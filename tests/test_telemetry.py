import json
import logging
import threading

import pytest

from household.telemetry import JobTrace


def events(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "household.progress"]


def test_progress_identifies_active_stage_and_elapsed_time(caplog):
    caplog.set_level(logging.INFO, logger="household.progress")
    now = [10.0]
    trace = JobTrace("request-123", clock=lambda: now[0], slow_seconds=2)
    with trace.stage("sql.receipt_save", tool="add_items"):
        now[0] = 13.0
        trace.report_progress()
    progress = next(e for e in events(caplog) if e["event"] == "job_progress")
    assert progress["job_id"] == "request-123"
    assert progress["elapsed_ms"] == 3000
    assert progress["active_stages"][0]["stage"] == "sql.receipt_save"
    assert progress["active_stages"][0]["elapsed_ms"] == 3000
    assert progress["slow"] is True
    assert events(caplog)[-1]["elapsed_ms"] == 3000
    assert events(caplog)[-1]["outcome"] == "success"


def test_failed_stage_records_type_without_exception_contents(caplog):
    caplog.set_level(logging.INFO, logger="household.progress")
    trace = JobTrace("request-123")
    with pytest.raises(RuntimeError), trace.stage("model.call"):
        raise RuntimeError("private prompt and credential")
    failure = events(caplog)[-1]
    assert failure["outcome"] == "error"
    assert failure["error_type"] == "RuntimeError"
    assert "private prompt" not in caplog.text
    trace.report_progress()
    assert events(caplog)[-1]["active_stages"] == []


def test_background_heartbeat_runs_while_stage_is_blocked(caplog):
    caplog.set_level(logging.INFO, logger="household.progress")
    observed = threading.Event()

    class ProgressObserver(logging.Handler):
        def emit(self, record):
            event = json.loads(record.getMessage())
            if event["event"] == "job_progress" and event["active_stages"]:
                observed.set()

    logger = logging.getLogger("household.progress")
    handler = ProgressObserver()
    logger.addHandler(handler)
    trace = JobTrace("request-123", interval=0.01)
    try:
        trace.start()
        with trace.stage("checkpoint.save"):
            assert observed.wait(2), "blocked work must still emit progress"
    finally:
        trace.close()
        logger.removeHandler(handler)
    assert not trace.thread.is_alive()
