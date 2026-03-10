from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .competition import fetch_cards
from .config import ConfigAdapter
from .message_builder import build_today_message
from .scheduler import parse_push_times
from .storage import CompetitionStore
from .targets import extract_event_group_mapping, resolve_targets


class CTFPushService:
    def __init__(
        self,
        config: ConfigAdapter,
        known_targets_file: Path,
        default_api_url: str,
        default_api_payload: dict[str, Any],
        sensitive_terms: tuple[str, ...],
        section_separator: str,
        default_push_time: str,
        db_dir: Path,
    ):
        self.config = config
        self.known_targets_file = known_targets_file
        self.default_api_url = default_api_url
        self.default_api_payload = default_api_payload
        self.sensitive_terms = sensitive_terms
        self.section_separator = section_separator
        self.default_push_time = default_push_time
        self.store = CompetitionStore(db_dir)
        self.known_targets: dict[str, str] = self._load_known_targets()

    def is_enabled(self) -> bool:
        return self.config.get_bool("enabled", True)

    def now(self) -> datetime:
        tz_name = str(self.config.get("timezone", "Asia/Shanghai") or "Asia/Shanghai")
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            return datetime.now(ZoneInfo("Asia/Shanghai"))

    def get_schedule_times(self) -> list[tuple[int, int]]:
        push_time = str(self.config.get("push_time", self.default_push_time) or self.default_push_time)
        return parse_push_times(push_time, 9, 0)

    def get_due_mark(self, now: datetime) -> str | None:
        times = self.get_schedule_times()
        due: list[str] = []
        for hour, minute in times:
            if (hour, minute) <= (now.hour, now.minute):
                due.append(f"{now.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}")
        if not due:
            return None
        return max(due)

    def fetch_cards(self) -> list[dict[str, Any]]:
        url = str(self.config.get("api_url", self.default_api_url) or self.default_api_url)
        payload_raw = self.config.get("api_payload", self.default_api_payload)
        timeout = max(3, self.config.get_int("request_timeout", 20))
        return fetch_cards(
            api_url=url,
            payload_raw=payload_raw,
            timeout=timeout,
            default_payload=self.default_api_payload,
            sensitive_terms=self.sensitive_terms,
        )

    def build_today_message(self, now: datetime, cards: list[dict[str, Any]], include_header: bool = True) -> str:
        return build_today_message(
            now=now,
            cards=cards,
            section_separator=self.section_separator,
            include_header=include_header,
        )

    def save_cards_snapshot(self, now: datetime, cards: list[dict[str, Any]]) -> int:
        return self.store.upsert_cards(cards, now)

    def search_competitions(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.store.search(keyword, limit=limit)

    def resolve_whitelist_targets(self, logger) -> list[str]:
        raw = self.config.get("groups", None)
        if raw is None:
            raw = self.config.get("group_whitelist", [])

        targets, missing_numeric = resolve_targets(raw, self.known_targets)
        if missing_numeric:
            logger.warning(
                "[ctf_push] unresolved group ids in whitelist: "
                f"{','.join(missing_numeric)}. Send /比赛 in those groups once to bind "
                "group_id -> unified_msg_origin."
            )
        return targets

    def remember_event_mapping(self, event: Any, logger):
        mapping = extract_event_group_mapping(event)
        if not mapping:
            return
        group_key, unified_msg_origin = mapping
        if self.known_targets.get(group_key) == unified_msg_origin:
            return
        self.known_targets[group_key] = unified_msg_origin
        self._save_known_targets()
        logger.info(f"[ctf_push] remembered group mapping: {group_key} -> {unified_msg_origin}")

    def _load_known_targets(self) -> dict[str, str]:
        if not self.known_targets_file.exists():
            return {}
        try:
            data = json.loads(self.known_targets_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save_known_targets(self):
        try:
            self.known_targets_file.write_text(
                json.dumps(self.known_targets, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
