import faulthandler
import logging
import signal
import time
from contextlib import nullcontext

from langchain_core.messages import AIMessage, HumanMessage

from household.agent import build_graph
from household.config import Settings
from household.db import Database
from household.telemetry import JobTrace, TracedPostgresSaver

logger = logging.getLogger("household.worker")


def make_model(settings):
    from langchain_openai import ChatOpenAI

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required by the worker")
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=30,
        max_retries=1,
        max_tokens=800,
    )


def run_once(db: Database, model=None, settings: Settings | None = None):
    settings = settings or Settings()
    # Session locks remain held across commits, and are released if the process dies.
    with db.connect(autocommit=True) as claim:
        candidates = claim.execute(
            "SELECT id, conversation_id FROM jobs WHERE status IN ('queued', 'processing') "
            "ORDER BY sequence LIMIT 50"
        ).fetchall()
        for candidate in candidates:
            key = "household:" + str(candidate["conversation_id"])
            locked = claim.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired", (key,)
            ).fetchone()["acquired"]
            if not locked:
                continue
            try:
                job = claim.execute(
                    "UPDATE jobs SET status = 'processing', attempts = attempts + 1, "
                    "updated_at = now() WHERE id = %s AND status IN ('queued', 'processing') "
                    "RETURNING *",
                    (candidate["id"],),
                ).fetchone()
                if not job:
                    continue
                _process(db, job, model, settings, claim)
                return True
            finally:
                claim.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
    return False


def _process(db, job, model, settings, claim):
    started = time.monotonic()
    logger.info("job_started id=%s attempt=%s", job["id"], job["attempts"])
    # A blocked database/checkpoint operation otherwise looks like an idle worker.
    # Stack traces contain code locations, not message contents or credentials.
    faulthandler.dump_traceback_later(60)
    trace = JobTrace(
        job["id"], interval=settings.progress_log_seconds, slow_seconds=settings.slow_stage_seconds
    )
    trace.start()
    try:
        with trace.stage("job.authorize"):
            context = claim.execute(
                "SELECT c.visibility,c.owner_user_id,u.id AS actor_id,u.email,u.display_name "
                "FROM jobs j JOIN conversations c ON c.id=j.conversation_id "
                "JOIN users u ON u.id=j.submitted_by WHERE j.id=%s",
                (job["id"],),
            ).fetchone()
            if (
                not context
                or context["email"] not in settings.family_emails
                or context["visibility"] == "legacy_shared"
                or (
                    context["visibility"] == "private"
                    and context["owner_user_id"] != context["actor_id"]
                )
            ):
                raise PermissionError("Job identity or conversation access is invalid")
            job = {**job, "visibility": context["visibility"], "actor_id": context["actor_id"]}
        # All durable writes use the lock-owning connection. If it dies, this
        # worker cannot keep saving state after another worker reclaims the job.
        with nullcontext(claim) as checkpoint_conn:
            with trace.stage("graph.build"):
                graph = build_graph(
                    db,
                    job,
                    model or make_model(settings),
                    TracedPostgresSaver(checkpoint_conn, trace),
                    claim,
                    trace,
                )
            config = {"configurable": {"thread_id": str(job["id"])}, "recursion_limit": 16}
            snapshot = graph.get_state(config)
            if snapshot.values:
                logger.info("job_resuming id=%s pending_nodes=%s", job["id"], snapshot.next)
                with trace.stage("graph.resume"):
                    result = (
                        graph.invoke(None, config, durability="sync")
                        if snapshot.next
                        else snapshot.values
                    )
            else:
                with trace.stage("history.load"), db.connect() as conn:
                    previous = conn.execute(
                        "SELECT content, response, submitted_by FROM ("
                        "SELECT sequence, content, response, submitted_by FROM jobs "
                        "WHERE conversation_id = %s AND status = 'completed' AND sequence < %s "
                        "ORDER BY sequence DESC LIMIT 40) history ORDER BY sequence",
                        (job["conversation_id"], job["sequence"]),
                    ).fetchall()
                messages = []
                for row in previous:
                    messages.extend(
                        [
                            HumanMessage(
                                row["content"],
                                name="member_" + str(row["submitted_by"]).replace("-", ""),
                            ),
                            AIMessage(row["response"]),
                        ]
                    )
                messages.append(
                    HumanMessage(
                        job["content"],
                        id=str(job["id"]),
                        name="member_" + str(job["actor_id"]).replace("-", ""),
                    )
                )
                with trace.stage("graph.run"):
                    result = graph.invoke({"messages": messages}, config, durability="sync")
            final = result["messages"][-1]
            if not isinstance(final, AIMessage) or final.tool_calls:
                raise ValueError("Graph did not produce a final answer")
            text = final.text
            if not text.strip():
                raise ValueError("Model returned an empty answer")
            input_tokens = output_tokens = 0
            for message in result["messages"]:
                usage = getattr(message, "usage_metadata", None) or {}
                input_tokens += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)
            cost = None
            if (
                settings.input_usd_per_million is not None
                and settings.output_usd_per_million is not None
            ):
                cost = (
                    input_tokens * settings.input_usd_per_million
                    + output_tokens * settings.output_usd_per_million
                ) / 1_000_000
            with trace.stage("job.save_completed"), nullcontext(claim) as conn:
                conn.execute(
                    "UPDATE jobs SET status = 'completed', response = %s, error = NULL, "
                    "input_tokens = %s, output_tokens = %s, estimated_cost_usd = %s, model = %s, "
                    "updated_at = now() WHERE id = %s",
                    (text, input_tokens, output_tokens, cost, settings.model_name, job["id"]),
                )
            logger.info(
                "job_completed id=%s input_tokens=%s output_tokens=%s elapsed_ms=%d",
                job["id"],
                input_tokens,
                output_tokens,
                (time.monotonic() - started) * 1000,
            )
    except Exception as exc:
        # Provider exception text can contain request contents or credentials.
        logger.error("job_failed id=%s error_type=%s", job["id"], type(exc).__name__)
        with trace.stage("job.save_failed"), nullcontext(claim) as conn:
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = %s, updated_at = now() WHERE id = %s",
                (
                    "The request could not finish. Some list changes may already be saved. "
                    "Retry to resume this request.",
                    job["id"],
                ),
            )
    finally:
        trace.close()
        faulthandler.cancel_dump_traceback_later()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    if len(settings.family_emails) != 5:
        raise ValueError("Configure the five FAMILY_ALLOWED_EMAILS for the worker")
    db = Database(settings.database_url)
    model = make_model(settings)
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("worker_started model=%s", settings.model_name)
    while not stopping:
        try:
            processed = run_once(db, model, settings)
        except Exception as exc:
            logger.error("worker_poll_failed error_type=%s", type(exc).__name__)
            processed = False
        if not processed:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
