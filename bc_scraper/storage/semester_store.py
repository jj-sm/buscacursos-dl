import atexit
import json
import sqlite3
import threading
import uuid


class SemesterSQLiteStore:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        atexit.register(self.close)

    def _conn_or_raise(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SQLite store is closed")
        return self._conn

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @staticmethod
    def _table_name(period: str) -> str:
        # Periods are like 2022-2, normalize to sqlite-safe table names.
        safe = "".join(ch if ch.isalnum() else "_" for ch in period)
        return f"semester_{safe}"

    def _ensure_table(self, period: str):
        table = self._table_name(period)
        with self._lock:
            conn = self._conn_or_raise()
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            col_names = {c[1] for c in cols}
            if "payload" in col_names:
                # Preserve old table and recreate with normalized schema.
                conn.execute(f"ALTER TABLE {table} RENAME TO {table}_legacy_payload")

            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY,
                    initials TEXT NOT NULL,
                    section INTEGER NOT NULL,
                    nrc TEXT NOT NULL,
                    name TEXT,
                    credits INTEGER,
                    req TEXT,
                    conn TEXT,
                    restr TEXT,
                    equiv TEXT,
                    program TEXT,
                    school TEXT,
                    area TEXT,
                    category TEXT,
                    teachers TEXT,
                    schedule_json TEXT,
                    format TEXT,
                    campus TEXT,
                    is_english INTEGER,
                    is_removable INTEGER,
                    is_special INTEGER,
                    total_quota INTEGER,
                    quota_json TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_section_identity ON {table} (initials, section, nrc)"
            )
            conn.commit()

    def ensure_period_table(self, period: str):
        self._ensure_table(period)

    def upsert_course_section(self, period: str, initials: str, course: dict, section_number: int, section: dict):
        table = self._table_name(period)
        self._ensure_table(period)

        stable_key = f"{period}:{initials}:{section_number}:{section.get('nrc', '')}"
        row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, stable_key))

        with self._lock:
            conn = self._conn_or_raise()
            conn.execute(
                f"""
                INSERT INTO {table} (
                    id, initials, section, nrc, name, credits, req, conn, restr, equiv,
                    program, school, area, category, teachers, schedule_json, format,
                    campus, is_english, is_removable, is_special, total_quota, quota_json, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT(initials, section, nrc)
                DO UPDATE SET
                    id=excluded.id,
                    name=excluded.name,
                    credits=excluded.credits,
                    req=excluded.req,
                    conn=excluded.conn,
                    restr=excluded.restr,
                    equiv=excluded.equiv,
                    program=excluded.program,
                    school=excluded.school,
                    area=excluded.area,
                    category=excluded.category,
                    teachers=excluded.teachers,
                    schedule_json=excluded.schedule_json,
                    format=excluded.format,
                    campus=excluded.campus,
                    is_english=excluded.is_english,
                    is_removable=excluded.is_removable,
                    is_special=excluded.is_special,
                    total_quota=excluded.total_quota,
                    quota_json=excluded.quota_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    row_id,
                    initials,
                    int(section_number),
                    str(section.get("nrc", "")),
                    course.get("name"),
                    int(course.get("credits", 0)) if course.get("credits") is not None else None,
                    course.get("req"),
                    course.get("conn"),
                    course.get("restr"),
                    course.get("equiv"),
                    course.get("program"),
                    course.get("school"),
                    course.get("area"),
                    course.get("category"),
                    section.get("teachers"),
                    json.dumps(section.get("schedule"), ensure_ascii=False),
                    section.get("format"),
                    section.get("campus"),
                    int(bool(section.get("is_english"))),
                    int(bool(section.get("is_removable"))),
                    int(bool(section.get("is_special"))),
                    int(section.get("total_quota", 0)) if section.get("total_quota") is not None else None,
                    json.dumps(section.get("quota"), ensure_ascii=False),
                ),
            )
            conn.commit()
