import json
import os
import time
from functools import wraps
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "requests.log"


def write_log(entry: dict):
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def logging_middleware(app):
    from flask import request, g

    @app.before_request
    def _before():
        g._start_time = time.time()
        g._req_body = None
        try:
            g._req_body = request.get_json(silent=True)
        except Exception:
            g._req_body = None

    @app.after_request
    def _after(response):
        duration = int((time.time() - getattr(g, "_start_time", time.time())) * 1000)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method": request.method,
            "path": request.path,
            "query": request.args.to_dict(flat=True),
            "status": response.status_code,
            "duration_ms": duration,
            "studentID": request.args.get("studentID") or (g._req_body or {}).get("studentID"),
        }
        if g._req_body is not None:
            try:
                entry["body_preview"] = json.dumps(g._req_body)[:1000]
            except Exception:
                entry["body_preview"] = None

        write_log(entry)
        return response

    return app
