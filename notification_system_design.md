# Notification System Design

This document covers the seven-stage deliverables: API design, persistence, query optimization, scaling, bulk reliability, priority inbox logic, and frontend notes.

## Stage 1 — API Design

- Base URL: `/api/v1/notifications`
- Supported query parameters: `limit` (int), `page` (int), `notification_type` (Event|Result|Placement), `studentID` (int), `isRead` (boolean), `since` (ISO timestamp)

Endpoints and sample request/response:

- GET /api/v1/notifications?studentID=1042&limit=20&page=1&notification_type=Placement

Request: none

Response (200):
```json
{
  "meta": { "page": 1, "limit": 20, "total": 254 },
  "data": [
    { "id": 123, "studentID": 1042, "type": "Placement", "message": "On-campus drive by X Corp", "isRead": false, "createdAt": "2026-05-12T09:12:00Z" }
  ]
}
```

- GET /api/v1/notifications/{id}
Response (200): single notification object

- POST /api/v1/notifications
Request: create notification (used by admins/services)
```json
{ "studentID": 1042, "type": "Event", "message": "Career fair on May 20", "metadata": {"location":"Hall A"} }
```

Response (201): created object

- PATCH /api/v1/notifications/{id}
Body to mark read/unread or update: `{ "isRead": true }`

Realtime mechanism:
- Primary: Server-Sent Events (SSE) or WebSocket for real-time push from server to client.
- Recommendation: use SSE for its simplicity with HTTP and automatic reconnects for live notification streams per student:

SSE event example:
```
event: notification
data: {"id": 999, "type":"Placement", "message":"New placement posted", "createdAt":"2026-05-14T10:00:00Z"}

```

Logging middleware:
- All API handlers must call the custom `LoggingMiddleware` (no console.log). Middleware records: endpoint, method, studentID (if present), request body hash, response code, duration, and correlation ID. Logs are written to a structured sink (JSON) and forwarded to central log store.

## Stage 2 — Data Persistence

Choice: PostgreSQL. Rationale: relational queries (per-student retrieval, pagination, ordered queries), strong consistency, and mature indexing.

Schema (DDL):
```sql
CREATE TABLE students (
  id BIGSERIAL PRIMARY KEY,
  name TEXT,
  email TEXT UNIQUE
);

CREATE TABLE notifications (
  id BIGSERIAL PRIMARY KEY,
  student_id BIGINT REFERENCES students(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('Event','Result','Placement')),
  message TEXT NOT NULL,
  metadata JSONB,
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Index to support queries by student and unread status and ordering by created_at
CREATE INDEX idx_notifications_student_isread_createdat ON notifications (student_id, is_read, created_at DESC);

-- Index to support queries by type and created_at (for time-window queries)
CREATE INDEX idx_notifications_type_createdat ON notifications (type, created_at DESC);
```

Sample queries:

- Insert notification:
```sql
INSERT INTO notifications (student_id, type, message, metadata)
VALUES (1042, 'Placement', 'X Corp hiring', '{"url":"https://..."}');
```

- Paginated fetch:
```sql
SELECT id, type, message, is_read, created_at
FROM notifications
WHERE student_id = $1
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;
```

## Stage 3 — Query Optimization

Problem query:
```sql
SELECT * FROM notifications WHERE studentID = 1042 AND isRead = false ORDER BY createdAt ASC;
```

Why it's slow:
- Missing compound index on `(studentID, isRead, createdAt)` forces a sequential scan for large tables.
- `SELECT *` pulls unnecessary columns (large `metadata` JSONB may be returned) increasing I/O.
- Ordering ascending on `createdAt` may prevent index usage if the index is created with DESC; however a matching index enables efficient ordered retrieval.

Why indexing every column is bad:
- Indexes increase write cost and storage. Indexing every column (including large text/JSON) slows inserts/updates and wastes space. Index only the columns used in WHERE/ORDER/GROUP BY.

Recommended index and query:
```sql
-- Create compound index (if not already present)
CREATE INDEX IF NOT EXISTS idx_notifications_student_isread_createdat_asc
ON notifications (student_id, is_read, created_at ASC);

-- Fetch unread notifications (only required fields) in ascending order
SELECT id, type, message, created_at
FROM notifications
WHERE student_id = 1042 AND is_read = false
ORDER BY created_at ASC
LIMIT 100;
```

Query to find placement notifications from last 7 days:
```sql
SELECT id, student_id, type, message, created_at
FROM notifications
WHERE type = 'Placement' AND created_at >= now() - INTERVAL '7 days'
ORDER BY created_at DESC;
```

## Stage 4 — Performance & Scaling

Problem: fetching notifications on every page load causes DB overload.

Solutions and tradeoffs:

- Client-side caching + Stale-While-Revalidate (SWR): cache recent notifications in browser/HTTP cache or service worker. Tradeoff: slightly stale UI until revalidated.
- Server-side cache (Redis) per student: store recent N notifications in Redis. Fast reads; must handle cache invalidation on writes. Tradeoff: eventual consistency and memory cost.
- Push model (SSE/WebSocket): push only new notifications to active clients; reduces repeated fetches. Tradeoff: complexity of maintaining connections and horizontal scaling (use sticky sessions or an external message broker like Redis Pub/Sub).
- Polling with exponential backoff: simple but increases DB load if many clients poll frequently.
- Use a notification feed service / stream (Kafka) + materialized views: enable high write throughput and scalable reads. Tradeoff: increases infra complexity.

Recommended approach: combine Redis cache for recent notifications + SSE push for active sessions + paginated DB read for history.

## Stage 5 — Reliability in Bulk Operations

Problem: `notify_all` fails midway when sending emails to 50,000 students.

Robust approach (patterns):
- Use an outbox pattern: writes a `notifications_outbox` table/queue when creating notifications. Background workers read the outbox and deliver messages.
- Batch processing with checkpointing: process in batches (e.g., 500-2000), commit progress, and on failure resume from last checkpoint.
- Idempotency: design deliveries to be idempotent (store delivery status per student+notification). Use unique delivery IDs.
- Parallel workers with rate limiting and retry with exponential backoff. Use dead-letter queue for permanent failures.

Pseudocode (reliable and fast):

```
function notify_all(notification_payload):
  -- write notifications to outbox table with status='pending'
  insert into outbox(notification_id, student_id, payload, status)

  -- worker pool picks batches
  while true:
    batch = fetch_pending_batch(limit=1000)
    if batch.empty: break
    for item in batch in parallel (N workers):
      try:
         deliver(item) -- send email via provider API
         mark_outbox_item_sent(item.id)
      except transient_error:
         schedule_retry(item, backoff)
      except permanent_error:
         mark_outbox_item_failed(item.id)

  -- monitoring: track sent/failed counts and surface dead-letter items
```

Notes:
- Use bulk-send APIs where available (SES bulk templated sends) to reduce overhead.
- Use connection pooling and HTTP keep-alive for provider APIs.

## Stage 6 — Priority Inbox Logic

Definition: compute a weight score for notifications combining type priority and recency. Type weights: Placement=3, Result=2, Event=1.

Implementation: a Python script that reads sample notifications and outputs Top 10.

See `/notification_app_be/priority_top10.py` and `/notification_app_be/sample_notifications.json`.

How score is computed (implemented in code):
- weight_score = type_weight * 1000000 + recency_score
- recency_score = max(0, (now - createdAt) in seconds transformed to favor recent items)

## Stage 7 — Frontend Notes

- Build a React app using Material UI at `notification_app_fe/`.
- Requirements: run on `http://localhost:3000` (use `npm run dev` or `npm start` depending on framework).
- Features to implement: All/Priority tabs, filters for Event/Result/Placement, mark-read toggles, distinguish new/viewed via styling, SSE connection for real-time updates.

Deliverables included in this repo:
- `notification_system_design.md` (this file)
- `notification_app_be/priority_top10.py` (Top 10 implementation)
- `notification_app_be/sample_notifications.json` (sample data)
- `notification_app_be/sample_output.txt` (sample run output)

Next steps I can implement on request:
- Scaffold the frontend `notification_app_fe` with a Material UI project and basic pages.
- Implement the Logging Middleware library and integrate it with the backend.
- Containerize services and add a docker-compose for Redis/Postgres and the app.


# output 
