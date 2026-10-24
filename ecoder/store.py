"""SQLite is the durable source of truth; all IDs are bound SQL parameters."""
import json
import sqlite3
import time
import uuid
from pathlib import Path


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, title TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, session TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, session TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS memories(session TEXT PRIMARY KEY, content TEXT);
                CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY, session TEXT, path TEXT, mime TEXT, size INTEGER, created REAL, UNIQUE(session,path));
                CREATE TABLE IF NOT EXISTS session_workspaces(session TEXT PRIMARY KEY, path TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cron_jobs(id TEXT PRIMARY KEY, session TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS goals(session TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experiences(id TEXT PRIMARY KEY, session TEXT, scope TEXT, fingerprint TEXT, body TEXT, UNIQUE(scope,fingerprint));
                CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY, session TEXT, body TEXT);
            """)

        with self.connect() as db:
            upload_columns = {row["name"] for row in db.execute("PRAGMA table_info(uploads)")}
            if "root" not in upload_columns:
                db.execute("ALTER TABLE uploads ADD COLUMN root TEXT")
            # Keep the actual attachment location independent of later workspace changes.
            for row in db.execute("SELECT DISTINCT session FROM uploads WHERE root IS NULL").fetchall():
                local = db.execute("SELECT path FROM session_workspaces WHERE session=?", (row["session"],)).fetchone()
                root = local[0] if local else str(self.path.parent / "uploads" / row["session"])
                db.execute("UPDATE uploads SET root=? WHERE session=? AND root IS NULL", (root,row["session"]))
            columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
            if "archived" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            if "deleted_at" in columns:
                # One-time migration: remove previously soft-deleted content.
                for table in ("messages", "events", "tasks", "memories", "uploads", "session_workspaces", "cron_jobs", "goals", "experiences", "annotations"):
                    db.execute(f"DELETE FROM {table} WHERE session IN (SELECT id FROM sessions WHERE deleted_at IS NOT NULL)")
                db.execute("DELETE FROM sessions WHERE deleted_at IS NOT NULL")
                db.execute("ALTER TABLE sessions DROP COLUMN deleted_at")

    def archive_legacy_runs(self):
        with self.connect() as db:
            for session in db.execute("SELECT id FROM sessions WHERE archived=0").fetchall():
                starts = [json.loads(row[0]) for row in db.execute("SELECT body FROM events WHERE session=?", (session["id"],)) if json.loads(row[0]).get("type") == "run_start"]
                if starts and all(event.get("mode") == "demo" for event in starts):
                    db.execute("UPDATE sessions SET archived=1 WHERE id=?", (session["id"],))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def create_session(self, title="新的编程任务"):
        session = {"id": uid(), "title": title[:80], "created": time.time()}
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id,title,created) VALUES(:id,:title,:created)", session)
        return session

    def sessions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,title,created FROM sessions WHERE archived=0 ORDER BY created DESC")]

    def exists(self, session):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM sessions WHERE id=?", (session,)).fetchone() is not None

    def delete_session(self, session):
        """Permanently delete the session and its contents in one transaction."""
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sessions WHERE id=? AND archived=0", (session,)).fetchone():
                return False
            for table in ("messages", "events", "tasks", "memories", "uploads", "session_workspaces", "cron_jobs", "goals", "experiences", "annotations"):
                db.execute(f"DELETE FROM {table} WHERE session=?", (session,))
            result = db.execute("DELETE FROM sessions WHERE id=?", (session,))
            return result.rowcount == 1

    def rename(self, session, title):
        with self.connect() as db:
            db.execute("UPDATE sessions SET title=? WHERE id=?", (title[:80], session))

    def append(self, session, message):
        with self.connect() as db:
            db.execute("INSERT INTO messages(session,body) VALUES(?,?)", (session, json.dumps(message, ensure_ascii=False)))

    def messages(self, session):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM messages WHERE session=? ORDER BY id", (session,))]

    def event(self, session, kind, **data):
        event = {"type": kind, "time": time.time(), **data}
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(session,body) VALUES(?,?)", (session, json.dumps(event, ensure_ascii=False)))
            event["seq"] = cursor.lastrowid
        return event

    def events(self, session, after=0):
        with self.connect() as db:
            return [{**json.loads(row["body"]), "seq": row["id"]} for row in db.execute("SELECT id,body FROM events WHERE session=? AND id>? ORDER BY id", (session, after))]

    def tasks(self, session):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM tasks WHERE session=? ORDER BY rowid", (session,))]

    def save_task(self, session, task):
        with self.connect() as db:
            db.execute("INSERT INTO tasks VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (task["id"], session, json.dumps(task, ensure_ascii=False)))

    def memory(self, session):
        with self.connect() as db:
            row = db.execute("SELECT content FROM memories WHERE session=?", (session,)).fetchone()
            return row[0] if row else ""

    def save_memory(self, session, content):
        with self.connect() as db:
            db.execute("INSERT INTO memories VALUES(?,?) ON CONFLICT(session) DO UPDATE SET content=excluded.content", (session, content[:8000]))

    def crons(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM cron_jobs ORDER BY rowid")]

    def save_cron(self, session, job):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sessions WHERE id=?", (session,)).fetchone():
                raise ValueError("会话不存在")
            db.execute("INSERT INTO cron_jobs(id,session,body) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body WHERE cron_jobs.session=excluded.session", (job['id'], session, json.dumps(job, ensure_ascii=False)))

    def delete_cron(self, session, job_id):
        with self.connect() as db:
            db.execute("DELETE FROM cron_jobs WHERE id=? AND session=?", (job_id, session))

    def goal(self, session):
        with self.connect() as db:
            row = db.execute('SELECT body FROM goals WHERE session=?',(session,)).fetchone()
            return json.loads(row[0]) if row else None

    def goals(self):
        with self.connect() as db:
            return [(row[0],json.loads(row[1])) for row in db.execute('SELECT session,body FROM goals')]

    def save_goal(self, session, state):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM sessions WHERE id=?',(session,)).fetchone():
                raise ValueError('会话不存在')
            db.execute('INSERT INTO goals(session,body) VALUES(?,?) ON CONFLICT(session) DO UPDATE SET body=excluded.body',
                       (session,json.dumps(state,ensure_ascii=False)))
