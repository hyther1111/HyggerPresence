"""Hygger Presence 2.0 - playtime storage (SQLite, no UI)."""
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from .core import debug_log


class StatsStore:
    """Append-only playtime log with the few aggregates the dashboard needs."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn = None
        try:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS sessions(
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       vndb_id TEXT,
                       title TEXT,
                       exe_name TEXT,
                       day TEXT NOT NULL,
                       start_ts INTEGER,
                       end_ts INTEGER,
                       seconds REAL)""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_day ON sessions(day)")
            self._conn.commit()
            debug_log("stats.db ready: %s" % self.path)
        except Exception as error:
            debug_log("stats.db unavailable: %s" % error)
            self._conn = None

    # ---------- writes ----------
    def add(self, vndb_id, title, exe_name, start_ts, end_ts, seconds, min_seconds=5.0):
        if not self._conn or seconds is None or seconds < min_seconds:
            return
        day = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d")
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO sessions(vndb_id,title,exe_name,day,start_ts,end_ts,seconds)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (vndb_id or "", title or "", exe_name or "", day,
                     int(start_ts), int(end_ts), float(seconds)))
                self._conn.commit()
        except Exception as error:
            debug_log("stats insert failed: %s" % error)

    def last_read(self):
        """Last day each game was read, for the Library's Last read column.

        Both the stored title and the exe name map to the day, because a game
        can be edited (title changed, exe renamed) after the session was saved.
        Newest day wins: the rows come back newest first and the first hit for a
        key is kept.
        """
        if not self._conn:
            return {}
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT vndb_id, title, exe_name, day FROM sessions"
                    " WHERE day IS NOT NULL AND day != ''"
                    " ORDER BY day DESC").fetchall()
        except Exception as error:
            debug_log("stats last_read failed: %s" % error)
            return {}
        latest = {}
        for vndb_id, title, exe_name, day in rows:
            keys = [("vn:%s" % vndb_id) if vndb_id else "", title, exe_name]
            for key in keys:
                if key and key not in latest:
                    latest[key] = day
        return latest

    def delete_sessions(self, ids):
        ids = [int(i) for i in ids]
        if not self._conn or not ids:
            return 0
        try:
            with self._lock:
                cursor = self._conn.executemany(
                    "DELETE FROM sessions WHERE id = ?", [(i,) for i in ids])
                self._conn.commit()
            return len(ids)
        except Exception as error:
            debug_log("stats delete failed: %s" % error)
            return 0

    def delete_range_for(self, day_from, day_to, title):
        """Delete a single visual novel's sessions inside a range."""
        if not self._conn:
            return 0
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "DELETE FROM sessions WHERE day BETWEEN ? AND ? AND title = ?",
                    (day_from, day_to, title or ""))
                self._conn.commit()
                return cursor.rowcount
        except Exception as error:
            debug_log("stats delete failed: %s" % error)
            return 0

    def delete_range(self, day_from, day_to):
        if not self._conn:
            return 0
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "DELETE FROM sessions WHERE day BETWEEN ? AND ?", (day_from, day_to))
                self._conn.commit()
                return cursor.rowcount or 0
        except Exception as error:
            debug_log("stats delete range failed: %s" % error)
            return 0

    # ---------- queries ----------
    def _query(self, sql, args=()):
        if not self._conn:
            return []
        try:
            with self._lock:
                return self._conn.execute(sql, args).fetchall()
        except Exception as error:
            debug_log("stats query failed: %s" % error)
            return []

    def total(self, day_from, day_to):
        rows = self._query(
            "SELECT COALESCE(SUM(seconds),0), COUNT(*) FROM sessions WHERE day BETWEEN ? AND ?",
            (day_from, day_to))
        return (rows[0][0], rows[0][1]) if rows else (0.0, 0)

    def by_day(self, day_from, day_to):
        return self._query(
            "SELECT day, SUM(seconds) FROM sessions WHERE day BETWEEN ? AND ?"
            " GROUP BY day ORDER BY day", (day_from, day_to))

    def by_day_game(self, day_from, day_to):
        """(day, vn key, seconds) - one row per day and visual novel."""
        return self._query(
            "SELECT day, COALESCE(NULLIF(title,''), NULLIF(vndb_id,''), exe_name, '?')"
            " AS vn, SUM(seconds) FROM sessions"
            " WHERE day BETWEEN ? AND ? GROUP BY day, vn ORDER BY day",
            (day_from, day_to))

    def by_month(self, day_from, day_to):
        return self._query(
            "SELECT substr(day,1,7) AS m, SUM(seconds) FROM sessions"
            " WHERE day BETWEEN ? AND ? GROUP BY m ORDER BY m", (day_from, day_to))

    def by_game(self, day_from, day_to, limit=60):
        # Grouped by title + VNDB id, not by exe: the same visual novel often
        # ships several exes (patched, uncensored, voice-fixed), and one card per
        # exe split the playtime of a single game across two rows.
        return self._query(
            "SELECT COALESCE(NULLIF(title,''), MAX(exe_name), vndb_id, '?'), vndb_id,"
            " SUM(seconds), MAX(day), COUNT(*) FROM sessions"
            " WHERE day BETWEEN ? AND ?"
            " GROUP BY title, vndb_id ORDER BY 3 DESC LIMIT ?",
            (day_from, day_to, limit))

    def sessions(self, day_from, day_to, limit=500):
        return self._query(
            "SELECT id, day, COALESCE(NULLIF(title,''), exe_name, vndb_id, '?'),"
            " seconds, start_ts FROM sessions WHERE day BETWEEN ? AND ?"
            " ORDER BY day DESC, start_ts DESC LIMIT ?",
            (day_from, day_to, limit))

    def first_day(self):
        rows = self._query("SELECT MIN(day) FROM sessions")
        return rows[0][0] if rows and rows[0][0] else None

    def close(self):
        try:
            with self._lock:
                if self._conn:
                    self._conn.close()
        except Exception:
            pass
        self._conn = None
