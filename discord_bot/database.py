import sqlite3
import threading
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        self._setup()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _setup(self):
        c = self._conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id     INTEGER PRIMARY KEY,
                prefix       TEXT DEFAULT '!',
                log_channel  INTEGER,
                xp_channel   INTEGER,
                warn_channel INTEGER,
                min_messages INTEGER DEFAULT 20,
                min_voice_minutes INTEGER DEFAULT 0,
                warn_at_inactive INTEGER DEFAULT 1,
                kick_at_warns INTEGER DEFAULT 5,
                ban_at_warns  INTEGER DEFAULT 10
            );

            CREATE TABLE IF NOT EXISTS staff_roles (
                guild_id INTEGER,
                role_id  INTEGER,
                role_name TEXT,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS tracked_roles (
                guild_id  INTEGER,
                role_id   INTEGER,
                role_name TEXT,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS activity (
                guild_id       INTEGER,
                user_id        INTEGER,
                week_messages  INTEGER DEFAULT 0,
                week_voice_min INTEGER DEFAULT 0,
                total_messages INTEGER DEFAULT 0,
                total_voice_min INTEGER DEFAULT 0,
                last_message   TEXT,
                week_start     TEXT,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                mod_id     INTEGER NOT NULL,
                reason     TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active     INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS level_roles (
                guild_id  INTEGER,
                level     INTEGER,
                role_id   INTEGER,
                role_name TEXT,
                PRIMARY KEY (guild_id, level)
            );

            CREATE TABLE IF NOT EXISTS user_levels (
                guild_id INTEGER,
                user_id  INTEGER,
                xp       INTEGER DEFAULT 0,
                level    INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS activity_checks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                checked_at  TEXT NOT NULL,
                total_staff INTEGER DEFAULT 0,
                active_staff INTEGER DEFAULT 0,
                warned_count INTEGER DEFAULT 0
            );
        """)
        c.commit()

    # ── Guild Settings ────────────────────────────────────────────────────────

    def get_settings(self, guild_id: int) -> sqlite3.Row | None:
        return self._conn().execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()

    def ensure_settings(self, guild_id: int):
        self._conn().execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
        )
        self._conn().commit()

    def update_setting(self, guild_id: int, key: str, value):
        self.ensure_settings(guild_id)
        self._conn().execute(
            f"UPDATE guild_settings SET {key} = ? WHERE guild_id = ?", (value, guild_id)
        )
        self._conn().commit()

    # ── Staff / Tracked Roles ─────────────────────────────────────────────────

    def add_staff_role(self, guild_id: int, role_id: int, role_name: str):
        self._conn().execute(
            "INSERT OR IGNORE INTO staff_roles (guild_id, role_id, role_name) VALUES (?,?,?)",
            (guild_id, role_id, role_name)
        )
        self._conn().commit()

    def remove_staff_role(self, guild_id: int, role_id: int):
        self._conn().execute(
            "DELETE FROM staff_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
        )
        self._conn().commit()

    def get_staff_roles(self, guild_id: int) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM staff_roles WHERE guild_id = ?", (guild_id,)
        ).fetchall()

    def add_tracked_role(self, guild_id: int, role_id: int, role_name: str):
        self._conn().execute(
            "INSERT OR IGNORE INTO tracked_roles (guild_id, role_id, role_name) VALUES (?,?,?)",
            (guild_id, role_id, role_name)
        )
        self._conn().commit()

    def get_tracked_roles(self, guild_id: int) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM tracked_roles WHERE guild_id = ?", (guild_id,)
        ).fetchall()

    # ── Activity ──────────────────────────────────────────────────────────────

    def get_activity(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        return self._conn().execute(
            "SELECT * FROM activity WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()

    def ensure_activity(self, guild_id: int, user_id: int):
        self._conn().execute(
            "INSERT OR IGNORE INTO activity (guild_id, user_id, week_start) VALUES (?,?,?)",
            (guild_id, user_id, datetime.now(timezone.utc).isoformat())
        )
        self._conn().commit()

    def add_message(self, guild_id: int, user_id: int):
        self.ensure_activity(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn().execute(
            """UPDATE activity
               SET week_messages = week_messages + 1,
                   total_messages = total_messages + 1,
                   last_message = ?
               WHERE guild_id = ? AND user_id = ?""",
            (now, guild_id, user_id)
        )
        self._conn().commit()

    def add_voice_minutes(self, guild_id: int, user_id: int, minutes: int):
        self.ensure_activity(guild_id, user_id)
        self._conn().execute(
            """UPDATE activity
               SET week_voice_min = week_voice_min + ?,
                   total_voice_min = total_voice_min + ?
               WHERE guild_id = ? AND user_id = ?""",
            (minutes, minutes, guild_id, user_id)
        )
        self._conn().commit()

    def reset_weekly(self, guild_id: int):
        now = datetime.now(timezone.utc).isoformat()
        self._conn().execute(
            """UPDATE activity
               SET week_messages = 0, week_voice_min = 0, week_start = ?
               WHERE guild_id = ?""",
            (now, guild_id)
        )
        self._conn().commit()

    def get_all_activity(self, guild_id: int) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM activity WHERE guild_id = ?", (guild_id,)
        ).fetchall()

    # ── Warnings ──────────────────────────────────────────────────────────────

    def add_warning(self, guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
        cur = self._conn().execute(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?,?,?,?,?)",
            (guild_id, user_id, mod_id, reason, datetime.now(timezone.utc).isoformat())
        )
        self._conn().commit()
        return cur.lastrowid

    def get_warnings(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? AND active = 1 ORDER BY created_at DESC",
            (guild_id, user_id)
        ).fetchall()

    def get_warning_by_id(self, warn_id: int) -> sqlite3.Row | None:
        return self._conn().execute(
            "SELECT * FROM warnings WHERE id = ?", (warn_id,)
        ).fetchone()

    def remove_warning(self, warn_id: int):
        self._conn().execute("UPDATE warnings SET active = 0 WHERE id = ?", (warn_id,))
        self._conn().commit()

    def clear_all_warnings(self, guild_id: int, user_id: int):
        self._conn().execute(
            "UPDATE warnings SET active = 0 WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        self._conn().commit()

    def count_warnings(self, guild_id: int, user_id: int) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ? AND active = 1",
            (guild_id, user_id)
        ).fetchone()
        return row[0] if row else 0

    # ── Levels ────────────────────────────────────────────────────────────────

    def get_user_level(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        return self._conn().execute(
            "SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()

    def ensure_user_level(self, guild_id: int, user_id: int):
        self._conn().execute(
            "INSERT OR IGNORE INTO user_levels (guild_id, user_id) VALUES (?,?)", (guild_id, user_id)
        )
        self._conn().commit()

    def add_xp(self, guild_id: int, user_id: int, xp: int) -> tuple[int, int, bool]:
        """Returns (new_xp, new_level, leveled_up)."""
        self.ensure_user_level(guild_id, user_id)
        row = self.get_user_level(guild_id, user_id)
        new_xp = row["xp"] + xp
        old_level = row["level"]
        new_level = self._calc_level(new_xp)
        leveled_up = new_level > old_level
        self._conn().execute(
            "UPDATE user_levels SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
            (new_xp, new_level, guild_id, user_id)
        )
        self._conn().commit()
        return new_xp, new_level, leveled_up

    def set_xp(self, guild_id: int, user_id: int, xp: int):
        self.ensure_user_level(guild_id, user_id)
        level = self._calc_level(xp)
        self._conn().execute(
            "UPDATE user_levels SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
            (xp, level, guild_id, user_id)
        )
        self._conn().commit()

    @staticmethod
    def _calc_level(xp: int) -> int:
        level = 0
        while xp >= Database.xp_for_next_level(level):
            xp -= Database.xp_for_next_level(level)
            level += 1
        return level

    @staticmethod
    def xp_for_next_level(level: int) -> int:
        return 100 + (level * 50)

    def get_leaderboard(self, guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit)
        ).fetchall()

    # ── Level Roles ───────────────────────────────────────────────────────────

    def set_level_role(self, guild_id: int, level: int, role_id: int, role_name: str):
        self._conn().execute(
            "INSERT OR REPLACE INTO level_roles (guild_id, level, role_id, role_name) VALUES (?,?,?,?)",
            (guild_id, level, role_id, role_name)
        )
        self._conn().commit()

    def get_level_roles(self, guild_id: int) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)
        ).fetchall()

    def get_role_for_level(self, guild_id: int, level: int) -> sqlite3.Row | None:
        return self._conn().execute(
            "SELECT * FROM level_roles WHERE guild_id = ? AND level <= ? ORDER BY level DESC LIMIT 1",
            (guild_id, level)
        ).fetchone()

    # ── Activity Checks ───────────────────────────────────────────────────────

    def log_activity_check(self, guild_id: int, total: int, active: int, warned: int):
        self._conn().execute(
            "INSERT INTO activity_checks (guild_id, checked_at, total_staff, active_staff, warned_count) VALUES (?,?,?,?,?)",
            (guild_id, datetime.now(timezone.utc).isoformat(), total, active, warned)
        )
        self._conn().commit()
