from uuid import uuid4


def conversation(client):
    response = client.post("/api/conversations", json={"title": "Groceries"})
    assert response.status_code == 201
    return response.json()["id"]


def submit(client, cid, text="Add milk", request_id=None):
    return client.post(
        f"/api/conversations/{cid}/messages",
        json={"request_id": request_id or str(uuid4()), "content": text},
    )


def test_private_routes_require_authentication(client):
    client.auth = None
    for path in ["/", "/api/conversations", "/api/shopping-list"]:
        assert client.get(path).status_code == 401
    assert client.get("/health").status_code == 200


def test_conversation_and_message_survive_new_api_instance(client, app):
    cid = conversation(client)
    response = submit(client, cid)
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    from fastapi.testclient import TestClient

    from household.api import create_app

    with TestClient(create_app(app.state.settings)) as restarted:
        restarted.auth = client.auth
        assert restarted.get("/api/conversations").json()[0]["id"] == cid
        jobs = restarted.get(f"/api/conversations/{cid}/messages").json()
        assert jobs[0]["content"] == "Add milk"
        assert jobs[0]["id"] == job["id"]


def test_request_id_deduplicates_and_rejects_conflicting_reuse(client):
    cid = conversation(client)
    key = str(uuid4())
    first = submit(client, cid, request_id=key).json()
    assert submit(client, cid, request_id=key).json()["id"] == first["id"]
    assert submit(client, cid, "Different", key).status_code == 409
    assert submit(client, conversation(client), request_id=key).status_code == 409
    assert len(client.get(f"/api/conversations/{cid}/messages").json()) == 1


def test_one_unfinished_message_per_conversation(client):
    cid = conversation(client)
    assert submit(client, cid).status_code == 202
    assert submit(client, cid, "Show list").status_code == 409


def test_missing_conversation_and_invalid_messages(client):
    assert submit(client, str(uuid4())).status_code == 404
    cid = conversation(client)
    assert submit(client, cid, "   ").status_code == 422
    assert submit(client, cid, "x" * 4001).status_code == 422


def test_browser_and_empty_list(client):
    assert "<html" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/shopping-list").json() == []


class ScriptedModel:
    """External inference is scripted; graph, tools and database are real."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.seen = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def answer(text):
    from langchain_core.messages import AIMessage

    return AIMessage(
        content=text, usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    )


def tool_call(name, args, call_id="call-1"):
    from langchain_core.messages import AIMessage

    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def work(app, model):
    from household.db import Database
    from household.worker import run_once

    return run_once(Database(app.state.settings.database_url), model, app.state.settings)


def test_real_graph_updates_shared_list_across_conversations(client, app):
    cid = conversation(client)
    submit(client, cid, "Add milk and eggs")
    assert work(
        app,
        ScriptedModel(
            tool_call("add_items", {"items": ["Milk", "eggs", " milk "]}), answer("Added.")
        ),
    )
    assert client.get("/api/shopping-list").json() == [{"name": "eggs"}, {"name": "milk"}]
    other = conversation(client)
    submit(client, other, "Remove eggs")
    work(app, ScriptedModel(tool_call("remove_items", {"items": ["eggs"]}), answer("Removed.")))
    assert client.get("/api/shopping-list").json() == [{"name": "milk"}]
    submit(client, cid, "What did I ask before?")
    model = ScriptedModel(answer("You asked to add milk and eggs."))
    work(app, model)
    assert any(m.content == "Add milk and eggs" for m in model.seen[0])
    jobs = client.get(f"/api/conversations/{cid}/messages").json()
    assert all(j["status"] == "completed" for j in jobs)
    assert jobs[0]["input_tokens"] == 10
    assert jobs[0]["output_tokens"] == 5


def test_failure_is_visible_and_same_job_can_retry(client, app):
    cid = conversation(client)
    job = submit(client, cid).json()
    work(app, ScriptedModel(RuntimeError("sensitive provider details")))
    failed = client.get(f"/api/conversations/{cid}/messages").json()[0]
    assert failed["status"] == "failed"
    assert "sensitive" not in failed["error"]
    assert submit(client, cid).status_code == 409
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 202
    work(app, ScriptedModel(tool_call("add_items", {"items": ["milk"]}), answer("Added.")))
    completed = client.get(f"/api/conversations/{cid}/messages").json()[0]
    assert completed["status"] == "completed"
    assert completed["attempts"] == 2
    assert completed["id"] == job["id"]


def test_tool_receipt_prevents_replay_after_other_changes(client, app):
    from household.db import Database
    from household.tools import execute_tool

    db = Database(app.state.settings.database_url)
    job = submit(client, conversation(client)).json()
    execute_tool(db, job["id"], "a", "add_items", {"items": ["milk"]})
    removed = execute_tool(db, job["id"], "b", "remove_items", {"items": ["milk"]})
    execute_tool(db, job["id"], "c", "add_items", {"items": ["milk"]})
    assert execute_tool(db, job["id"], "b", "remove_items", {"items": ["milk"]}) == removed
    assert client.get("/api/shopping-list").json() == [{"name": "milk"}]


def test_processing_job_is_reclaimed_but_locked_conversation_is_not(client, app):
    from household.db import Database

    cid = conversation(client)
    job = submit(client, cid).json()
    db = Database(app.state.settings.database_url)
    with db.connect(autocommit=True) as conn:
        conn.execute("UPDATE jobs SET status = 'processing' WHERE id = %s", (job["id"],))
        conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", ("household:" + cid,))
        assert not work(app, ScriptedModel(answer("Should not run")))
    assert work(app, ScriptedModel(answer("Recovered.")))
    assert client.get(f"/api/conversations/{cid}/messages").json()[0]["response"] == "Recovered."


def test_retry_resumes_checkpoint_without_repeating_model_tool_choice(client, app):
    cid = conversation(client)
    job = submit(client, cid).json()
    work(
        app,
        ScriptedModel(tool_call("add_items", {"items": ["milk"]}), RuntimeError("network failure")),
    )
    assert client.get("/api/shopping-list").json() == [{"name": "milk"}]
    client.post(f"/api/jobs/{job['id']}/retry")
    # Recreated graph/saver reads the persisted checkpoint and resumes at the model node.
    resumed = ScriptedModel(answer("Milk is on the list."))
    work(app, resumed)
    from langchain_core.messages import ToolMessage

    assert any(isinstance(m, ToolMessage) for m in resumed.seen[0])
    assert client.get(f"/api/conversations/{cid}/messages").json()[0]["status"] == "completed"


def test_list_tool_reads_database_and_records_configured_cost(client, app):
    app.state.settings.input_usd_per_million = 1
    app.state.settings.output_usd_per_million = 2
    cid = conversation(client)
    submit(client, cid)
    work(app, ScriptedModel(tool_call("add_items", {"items": ["milk"]}), answer("Added milk.")))
    other = conversation(client)
    submit(client, other, "Show the shopping list")
    model = ScriptedModel(tool_call("list_items", {}), answer("Milk is on the list."))
    work(app, model)
    import json

    from langchain_core.messages import ToolMessage

    tool_result = next(m for m in model.seen[-1] if isinstance(m, ToolMessage))
    assert json.loads(tool_result.content) == {"items": ["milk"]}
    job = client.get(f"/api/conversations/{other}/messages").json()[0]
    assert abs(job["estimated_cost_usd"] - 0.00002) < 1e-10


def test_invalid_tool_input_has_no_database_effect(client, app):
    cid = conversation(client)
    submit(client, cid)
    model = ScriptedModel(
        tool_call("add_items", {"items": ["milk", "   "]}),
        answer("Which items should I add?"),
    )
    work(app, model)
    assert client.get("/api/shopping-list").json() == []
    from langchain_core.messages import ToolMessage

    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in model.seen[-1])


def test_completed_checkpoint_recovers_without_another_model_call(client, app):
    from household.db import Database

    cid = conversation(client)
    job = submit(client, cid).json()
    work(app, ScriptedModel(answer("Saved answer.")))
    # Simulate death after the graph completed but before its final job update committed.
    with Database(app.state.settings.database_url).connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'processing', response = NULL WHERE id = %s", (job["id"],)
        )
    work(app, ScriptedModel())
    recovered = client.get(f"/api/conversations/{cid}/messages").json()[0]
    assert recovered["status"] == "completed"
    assert recovered["response"] == "Saved answer."


def test_empty_model_answer_can_be_retried(client, app):
    cid = conversation(client)
    job = submit(client, cid).json()
    work(app, ScriptedModel(answer("")))
    assert client.get(f"/api/conversations/{cid}/messages").json()[0]["status"] == "failed"
    client.post(f"/api/jobs/{job['id']}/retry")
    work(app, ScriptedModel(answer("Recovered.")))
    result = client.get(f"/api/conversations/{cid}/messages").json()[0]
    assert result["status"] == "completed"
    assert result["response"] == "Recovered."


def test_lost_claim_connection_cannot_continue_mutating_list(client, app):
    import psycopg

    from household.db import Database

    cid = conversation(client)
    submit(client, cid)
    db = Database(app.state.settings.database_url)

    class DisconnectedModel(ScriptedModel):
        def invoke(self, messages):
            if not self.seen:
                with db.connect(autocommit=True) as conn:
                    pid = conn.execute(
                        "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
                        "AND ((classid::bigint << 32) | objid::bigint) = hashtextextended(%s, 0)",
                        ("household:" + cid,),
                    ).fetchone()["pid"]
                    conn.execute("SELECT pg_terminate_backend(%s)", (pid,))
            return super().invoke(messages)

    model = DisconnectedModel(tool_call("add_items", {"items": ["milk"]}), answer("Added milk."))
    try:
        work(app, model)
    except psycopg.OperationalError:
        pass
    assert client.get("/api/shopping-list").json() == []
    assert client.get(f"/api/conversations/{cid}/messages").json()[0]["status"] == "processing"
    assert work(
        app, ScriptedModel(tool_call("add_items", {"items": ["milk"]}), answer("Recovered."))
    )
    assert client.get("/api/shopping-list").json() == [{"name": "milk"}]


def test_job_logs_time_model_tools_sql_and_checkpoints(client, app, caplog):
    import json
    import logging

    caplog.set_level(logging.INFO, logger="household.progress")
    cid = conversation(client)
    job = submit(client, cid, "Private shopping request").json()
    work(
        app,
        ScriptedModel(
            tool_call("remove_items", {"items": ["private item"]}, "remove-call"),
            tool_call("add_items", {"items": ["milk"]}, "add-call"),
            answer("Updated."),
        ),
    )
    events = [json.loads(r.message) for r in caplog.records if r.name == "household.progress"]
    finished = [e for e in events if e["event"] == "stage_finished"]
    stages = {e["stage"] for e in finished}
    assert {
        "model.call",
        "tool.execute",
        "sql.receipt_save",
        "checkpoint.save",
        "checkpoint.write_tasks",
        "checkpoint.load",
        "history.load",
        "job.save_completed",
    } <= stages
    assert all(e["job_id"] == job["id"] for e in events)
    assert all(e["elapsed_ms"] >= 0 for e in finished)
    assert "Private shopping request" not in caplog.text
    assert "private item" not in caplog.text
    assert client.get(f"/api/conversations/{cid}/messages").json()[0]["status"] == "completed"


def test_malformed_tool_identifiers_do_not_leak_into_logs(client, app, caplog):
    import logging

    caplog.set_level(logging.INFO)
    submit(client, conversation(client))
    work(
        app,
        ScriptedModel(
            tool_call("private-invalid-tool", {}, "private-call-identifier"),
            answer("Please clarify."),
        ),
    )
    assert "private-invalid-tool" not in caplog.text
    assert "private-call-identifier" not in caplog.text
    assert "unknown" in caplog.text


def test_tool_waits_for_checkpoint_pipeline_to_release_shared_connection(client, app):
    import threading
    from contextlib import contextmanager

    from langgraph.checkpoint.postgres import PostgresSaver

    from household.agent import build_graph
    from household.db import Database

    db = Database(app.state.settings.database_url)
    job = submit(client, conversation(client)).json()
    pipeline_open = threading.Event()
    connection_attempted = threading.Event()
    release_checkpoint = threading.Event()
    failures = []

    class Probe:
        @contextmanager
        def stage(self, name, **fields):
            if name == "sql.tool_transaction":
                # Capture overlap before waking the controlling thread. This also
                # detects the old implementation, which never acquired saver.lock.
                overlap = pipeline_open.is_set()
                connection_attempted.set()
                if overlap:
                    raise AssertionError("Tool transaction entered an active checkpoint pipeline")
            yield

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if threading.current_thread().name == "regression-tool":
                connection_attempted.set()
            self.lock.acquire()
            return self

        def __exit__(self, *args):
            self.lock.release()

    with db.connect(autocommit=True) as conn:
        saver = PostgresSaver(conn)
        saver.lock = ObservedLock()
        graph = build_graph(db, job, ScriptedModel(), saver, conn, Probe())

        def checkpoint_thread():
            try:
                # Same pipeline context and saver lock used by real checkpoint writes.
                with saver._cursor(pipeline=True) as cursor:
                    cursor.execute("SELECT 1")
                    pipeline_open.set()
                    assert release_checkpoint.wait(3)
                    pipeline_open.clear()
            except BaseException as exc:
                failures.append(exc)

        def tool_thread():
            try:
                graph.nodes["tools"].bound.invoke(
                    {"messages": [tool_call("add_items", {"items": ["milk"]})]}
                )
            except BaseException as exc:
                failures.append(exc)

        checkpoint = threading.Thread(target=checkpoint_thread, daemon=True)
        tool = threading.Thread(target=tool_thread, name="regression-tool", daemon=True)
        checkpoint.start()
        try:
            assert pipeline_open.wait(2)
            tool.start()
            assert connection_attempted.wait(2)
        finally:
            release_checkpoint.set()
            checkpoint.join(3)
            tool.join(3)
        assert not checkpoint.is_alive() and not tool.is_alive()
        assert not failures, failures
    assert client.get("/api/shopping-list").json() == [{"name": "milk"}]
