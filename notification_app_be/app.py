from flask import Flask, request, jsonify, Response, stream_with_context
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import time
import json

from logging_middleware import logging_middleware
from init_db import DB_PATH, init_db

app = Flask(__name__)
logging_middleware(app)


def dict_from_row(row, cur):
    return {col[0]: row[idx] for idx, col in enumerate(cur.description)}


def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/api/v1/notifications", methods=["GET"])
def list_notifications():
    student_id = request.args.get("studentID", type=int)
    limit = request.args.get("limit", default=20, type=int)
    page = request.args.get("page", default=1, type=int)
    ntype = request.args.get("notification_type")
    is_read = request.args.get("isRead")

    if not student_id:
        return jsonify({"error": "studentID is required"}), 400

    offset = (page - 1) * limit
    q = "SELECT id, student_id, type, message, metadata, is_read, created_at FROM notifications WHERE student_id = ?"
    params = [student_id]
    if ntype:
        q += " AND type = ?"
        params.append(ntype)
    if is_read is not None:
        val = 1 if str(is_read).lower() in ("1", "true", "t") else 0
        q += " AND is_read = ?"
        params.append(val)
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = get_db_conn()
    cur = conn.execute(q, params)
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if r.get("created_at"):
            if r["created_at"].endswith("Z"):
                pass
            else:
                try:
                    dt = datetime.fromisoformat(r["created_at"]) 
                except Exception:
                    dt = datetime.now(timezone.utc)
                r["created_at"] = dt.astimezone(timezone.utc).isoformat()

    cur2 = conn.execute("SELECT COUNT(1) FROM notifications WHERE student_id = ?", (student_id,))
    total = cur2.fetchone()[0]
    conn.close()

    return jsonify({"meta": {"page": page, "limit": limit, "total": total}, "data": rows})


@app.route("/api/v1/notifications/<int:nid>", methods=["GET"])
def get_notification(nid):
    conn = get_db_conn()
    cur = conn.execute("SELECT id, student_id, type, message, metadata, is_read, created_at FROM notifications WHERE id = ?", (nid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    r = dict(row)
    return jsonify(r)


@app.route("/api/v1/notifications", methods=["POST"])
def create_notification():
    body = request.get_json() or {}
    student_id = body.get("studentID") or body.get("student_id")
    if not student_id or not body.get("type") or not body.get("message"):
        return jsonify({"error": "studentID, type and message required"}), 400
    metadata = json.dumps(body.get("metadata")) if body.get("metadata") else None
    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_conn()
    cur = conn.execute("INSERT INTO notifications (student_id, type, message, metadata, is_read, created_at) VALUES (?, ?, ?, ?, 0, ?)",
                       (student_id, body.get("type"), body.get("message"), metadata, created_at))
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return jsonify({"id": nid, "studentID": student_id, "type": body.get("type"), "message": body.get("message"), "createdAt": created_at}), 201


@app.route("/api/v1/notifications/<int:nid>", methods=["PATCH"]) 
def update_notification(nid):
    body = request.get_json() or {}
    if "isRead" in body or "is_read" in body:
        val = body.get("isRead") if "isRead" in body else body.get("is_read")
        val_int = 1 if str(val).lower() in ("1", "true", "t") else 0
        conn = get_db_conn()
        conn.execute("UPDATE notifications SET is_read = ? WHERE id = ?", (val_int, nid))
        conn.commit()
        conn.close()
        return jsonify({"id": nid, "isRead": bool(val_int)})
    return jsonify({"error": "No updatable fields provided"}), 400


@app.route("/api/v1/notifications/stream")
def sse_stream():
    student_id = request.args.get("studentID", type=int)
    if not student_id:
        return jsonify({"error": "studentID required"}), 400

    def gen():
        last_seen = None
        while True:
            conn = get_db_conn()
            if last_seen:
                cur = conn.execute("SELECT id, student_id, type, message, metadata, is_read, created_at FROM notifications WHERE student_id = ? AND created_at > ? ORDER BY created_at ASC", (student_id, last_seen))
            else:
                cur = conn.execute("SELECT id, student_id, type, message, metadata, is_read, created_at FROM notifications WHERE student_id = ? ORDER BY created_at ASC LIMIT 1", (student_id,))
            rows = cur.fetchall()
            conn.close()
            if rows:
                for r in rows:
                    obj = dict(r)
                    if obj.get("created_at") and obj["created_at"].endswith("Z"):
                        obj["created_at"] = obj["created_at"].replace("Z", "+00:00")
                    data = json.dumps(obj)
                    yield f"event: notification\n"
                    yield f"data: {data}\n\n"
                    last_seen = obj.get("created_at")
            time.sleep(1)

    return Response(stream_with_context(gen()), mimetype="text/event-stream")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
