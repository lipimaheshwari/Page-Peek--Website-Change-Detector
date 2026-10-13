import os, sqlite3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "page_peek.db")

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS pages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      url TEXT NOT NULL UNIQUE,
      interval_minutes INTEGER NOT NULL DEFAULT 60,
      watch_selectors TEXT NOT NULL DEFAULT '',
      ignore_selectors TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      last_checked TEXT NOT NULL DEFAULT '',
      last_status TEXT NOT NULL DEFAULT 'waiting',
      last_error TEXT NOT NULL DEFAULT '',
      last_hash TEXT NOT NULL DEFAULT '',
      last_title TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      page_id INTEGER NOT NULL,
      version_no INTEGER NOT NULL,
      checked_at TEXT NOT NULL,
      title TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      content_text TEXT NOT NULL,
      screenshot_path TEXT NOT NULL,
      FOREIGN KEY(page_id) REFERENCES pages(id) ON DELETE CASCADE,
      UNIQUE(page_id, version_no)
    );
    """)
    db.commit()
    db.close()
