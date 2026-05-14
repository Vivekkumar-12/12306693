# Notification App Backend

Minimal Flask backend for the campus notification platform.

Requirements
- Python 3.8+
- Install dependencies:

```bash
pip install -r notification_app_be/requirements.txt
```

Initialize DB and run

```bash
python3 notification_app_be/init_db.py
python3 notification_app_be/app.py
```

This starts the API on port 5000.

Endpoints
- `GET /api/v1/notifications?studentID=<id>&limit=20&page=1&notification_type=Placement`
- `GET /api/v1/notifications/<id>`
- `POST /api/v1/notifications` (JSON body: studentID, type, message)
- `PATCH /api/v1/notifications/<id>` (JSON body: isRead)
- `GET /api/v1/notifications/stream?studentID=<id>` (SSE stream)

Logging
- All requests are logged to `notification_app_be/logs/requests.log` as JSON lines by the custom `LoggingMiddleware`.

Notes for evaluation
- Use an API client (Postman or Insomnia) to call the endpoints on `http://localhost:5000` and capture request body, response and response time for submission screenshots.
