import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "notifications.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT,
      email TEXT UNIQUE
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      student_id INTEGER,
      type TEXT,
      message TEXT,
      metadata TEXT,
      is_read INTEGER DEFAULT 0,
      created_at TEXT
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_student_isread_createdat ON notifications (student_id, is_read, created_at DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_type_createdat ON notifications (type, created_at DESC);")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Initialized DB at", DB_PATH)
