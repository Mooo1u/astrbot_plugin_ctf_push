from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class CompetitionStore:
    def __init__(self, db_dir: Path):
        self.db_dir = db_dir
        self.db_path = self.db_dir / "competitions.db"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS competitions (
                    source_key TEXT PRIMARY KEY,
                    competition_id TEXT,
                    name TEXT NOT NULL,
                    short_name TEXT,
                    description TEXT,
                    start_ts INTEGER,
                    end_ts INTEGER,
                    reg_start_ts INTEGER,
                    reg_end_ts INTEGER,
                    status TEXT,
                    hint TEXT,
                    payload_json TEXT NOT NULL,
                    last_seen_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_comp_name
                    ON competitions(name COLLATE NOCASE);

                CREATE INDEX IF NOT EXISTS idx_comp_short_name
                    ON competitions(short_name COLLATE NOCASE);

                CREATE INDEX IF NOT EXISTS idx_comp_last_seen
                    ON competitions(last_seen_date);
                """
            )

    def upsert_cards(self, cards: list[dict[str, Any]], now: datetime) -> int:
        if not cards:
            return 0

        rows: list[tuple[Any, ...]] = []
        seen_date = now.strftime("%Y-%m-%d")
        updated_at = now.isoformat(timespec="seconds")

        for card in cards:
            payload_json = json.dumps(card.get("raw") or {}, ensure_ascii=False)
            rows.append(
                (
                    self._source_key(card),
                    str(card.get("competition_id") or ""),
                    str(card.get("name") or "未命名比赛"),
                    str(card.get("short_name") or ""),
                    str(card.get("description") or ""),
                    self._to_ts(card.get("start")),
                    self._to_ts(card.get("end")),
                    self._to_ts(card.get("reg_start")),
                    self._to_ts(card.get("reg_end")),
                    str(card.get("status") or ""),
                    str(card.get("hint") or ""),
                    payload_json,
                    seen_date,
                    updated_at,
                )
            )

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO competitions (
                    source_key,
                    competition_id,
                    name,
                    short_name,
                    description,
                    start_ts,
                    end_ts,
                    reg_start_ts,
                    reg_end_ts,
                    status,
                    hint,
                    payload_json,
                    last_seen_date,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    competition_id=excluded.competition_id,
                    name=excluded.name,
                    short_name=excluded.short_name,
                    description=excluded.description,
                    start_ts=excluded.start_ts,
                    end_ts=excluded.end_ts,
                    reg_start_ts=excluded.reg_start_ts,
                    reg_end_ts=excluded.reg_end_ts,
                    status=excluded.status,
                    hint=excluded.hint,
                    payload_json=excluded.payload_json,
                    last_seen_date=excluded.last_seen_date,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def search(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        text = (keyword or "").strip()
        if not text:
            return []

        limit_num = max(1, min(20, int(limit)))
        lower = text.lower()
        exact = lower
        like_any = f"%{self._escape_like(lower)}%"
        like_prefix = f"{self._escape_like(lower)}%"

        sql = """
            SELECT
                source_key,
                competition_id,
                name,
                short_name,
                description,
                start_ts,
                end_ts,
                reg_start_ts,
                reg_end_ts,
                status,
                hint,
                payload_json,
                last_seen_date,
                updated_at
            FROM competitions
            WHERE
                lower(name) LIKE ? ESCAPE '\\'
                OR lower(COALESCE(short_name, '')) LIKE ? ESCAPE '\\'
                OR lower(COALESCE(description, '')) LIKE ? ESCAPE '\\'
            ORDER BY
                CASE
                    WHEN lower(name) = ? THEN 0
                    WHEN lower(name) LIKE ? ESCAPE '\\' THEN 1
                    WHEN lower(COALESCE(short_name, '')) LIKE ? ESCAPE '\\' THEN 2
                    ELSE 3
                END,
                CASE WHEN start_ts IS NULL THEN 1 ELSE 0 END,
                start_ts ASC
            LIMIT ?
        """

        with self._connect() as conn:
            rows = conn.execute(
                sql,
                (like_any, like_any, like_any, exact, like_prefix, like_prefix, limit_num),
            ).fetchall()
        return [dict(r) for r in rows]

    def _source_key(self, card: dict[str, Any]) -> str:
        cid = str(card.get("competition_id") or "").strip()
        if cid:
            return f"id:{cid}"
        start_ts = self._to_ts(card.get("start"))
        end_ts = self._to_ts(card.get("end"))
        name = str(card.get("name") or "未命名比赛")
        return f"name:{name}|start:{start_ts}|end:{end_ts}"

    @staticmethod
    def _to_ts(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return int(value.timestamp())
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _escape_like(text: str) -> str:
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
