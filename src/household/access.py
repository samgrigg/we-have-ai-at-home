from fastapi import HTTPException


def require_conversation(conn, cid, user_id, *, write=False):
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=%s AND "
        "(visibility IN ('family','legacy_shared') OR owner_user_id=%s)",
        (cid, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    if write and row["visibility"] == "legacy_shared":
        raise HTTPException(409, "POC archive is read-only; start a new conversation")
    return row
