from __future__ import annotations

import asyncio
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

DEFAULT_API_URL = "" # 查询比赛列表的API地址
DEFAULT_API_PAYLOAD = {} # 查询API时的结构体
SENSITIVE_TERMS = ("",) 
DEFAULT_PUSH_TIME = "09:00"
SECTION_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
DB_DIR = PLUGIN_DIR / "app" / "sql"

from ctfpush_app_v120.config import ConfigAdapter
from ctfpush_app_v120.service import CTFPushService


PLUGIN_VERSION = "1.2.2"


@register("astrbot_plugin_ctf_push", "Mo1u", "每日推送当日 CTF 比赛信息", PLUGIN_VERSION)
class CTFPushPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        self.cfg = ConfigAdapter(config)
        self.service = CTFPushService(
            config=self.cfg,
            known_targets_file=PLUGIN_DIR / "known_targets.json",
            default_api_url=DEFAULT_API_URL,
            default_api_payload=DEFAULT_API_PAYLOAD,
            sensitive_terms=SENSITIVE_TERMS,
            section_separator=SECTION_SEPARATOR,
            default_push_time=DEFAULT_PUSH_TIME,
            db_dir=DB_DIR,
        )

        self._task: asyncio.Task | None = None
        self._sent_marks: set[str] = set()
        try:
            self._task = asyncio.create_task(self._scheduler_loop())
            logger.info("[ctf_push] scheduler started from __init__")
        except RuntimeError:
            self._task = None

    async def initialize(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._scheduler_loop())
            logger.info("[ctf_push] scheduler started from initialize")

    async def terminate(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[ctf_push] scheduler stopped")

    @filter.command("比赛")
    async def competition_cn(self, event: AstrMessageEvent):
        text = self._build_today_reply_text(event)
        yield event.plain_result(text)

    @filter.command("比赛帮助")
    async def competition_help(self, event: AstrMessageEvent):
        text = self._build_help_text()
        yield event.plain_result(text)

    @filter.command("查询比赛")
    async def query_competition(self, event: AstrMessageEvent):
        text = self._build_query_reply_text(event)
        yield event.plain_result(text)

    @filter.command("比赛查询")
    async def query_competition_alias(self, event: AstrMessageEvent):
        text = self._build_query_reply_text(event)
        yield event.plain_result(text)

    def _build_help_text(self) -> str:
        lines = [
            "【比赛插件帮助】",
            "1. /比赛",
            "   获取当日比赛信息，并同步数据库。",
            "2. /比赛查询 <比赛名称(可模糊查询)>",
            "   按比赛名称、简称、简介模糊查询已入库比赛。",
            "3. /查询比赛 <比赛名称(可模糊查询)>",
            "   与 /比赛查询 功能一致。",
        ]
        return "\n".join(lines)

    def _build_today_reply_text(self, event: AstrMessageEvent) -> str:
        self._refresh_runtime_config()
        self.service.remember_event_mapping(event, logger)
        now = self.service.now()
        try:
            cards = self.service.fetch_cards()
            self._sync_cards_to_db(now, cards)
        except Exception as exc:
            logger.error(f"[ctf_push] fetch failed: {exc}")
            return f"获取比赛信息失败: {exc}"
        return self.service.build_today_message(now, cards, include_header=True)

    def _build_query_reply_text(self, event: AstrMessageEvent) -> str:
        self._refresh_runtime_config()
        self.service.remember_event_mapping(event, logger)
        keyword = self._extract_query_keyword(event)
        if not keyword:
            return (
                "用法:\n"
                "/比赛查询 <比赛名称(可模糊查询)>\n"
                "/查询比赛 <比赛名称(可模糊查询)>"
            )

        try:
            matches = self.service.search_competitions(keyword, limit=8)
        except Exception as exc:
            logger.error(f"[ctf_push] query failed: {exc}")
            return f"查询失败: {exc}"

        if not matches:
            return (
                f"未找到与“{keyword}”相关的比赛。\n"
                "提示: 先执行一次 /比赛 同步最新数据，或等待下一次定时推送。"
            )

        now_tz = self.service.now().tzinfo
        lines = [f"【比赛查询】关键词: {keyword}", f"匹配结果: {len(matches)}"]
        for idx, item in enumerate(matches, 1):
            lines.append(f"{idx}. {item.get('name') or '未命名比赛'}")
            short_name = str(item.get("short_name") or "").strip()
            if short_name:
                lines.append(f"   简称: {short_name}")
            lines.append(f"   开始: {self._fmt_ts(item.get('start_ts'), now_tz)}")
            lines.append(f"   结束: {self._fmt_ts(item.get('end_ts'), now_tz)}")
            lines.append(
                "   报名: "
                f"{self._fmt_ts(item.get('reg_start_ts'), now_tz)} ~ {self._fmt_ts(item.get('reg_end_ts'), now_tz)}"
            )
            desc = self._description_snippet(item.get("description"))
            if desc:
                lines.append(f"   简介: {desc}")
        return "\n".join(lines)

    async def _scheduler_loop(self):
        while True:
            try:
                self._refresh_runtime_config()
                if not self.service.is_enabled():
                    await asyncio.sleep(30)
                    continue

                now = self.service.now()
                self._cleanup_sent_marks(now)

                due_mark = self.service.get_due_mark(now)
                if not due_mark:
                    await asyncio.sleep(15)
                    continue

                if due_mark in self._sent_marks:
                    await asyncio.sleep(15)
                    continue

                cards = self.service.fetch_cards()
                self._sync_cards_to_db(now, cards)
                text = self.service.build_today_message(now, cards, include_header=True)
                result = await self._push_to_whitelist(text)
                self._sent_marks.add(due_mark)
                logger.info(
                    "[ctf_push] pushed mark=%s targets=%d success=%d fail=%d",
                    due_mark,
                    len(result["targets"]),
                    result["ok"],
                    result["fail"],
                )
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"[ctf_push] scheduler error: {exc}")
                await asyncio.sleep(30)

    async def _push_to_whitelist(self, text: str):
        self._refresh_runtime_config()
        targets = self.service.resolve_whitelist_targets(logger)
        result = {
            "targets": targets,
            "ok": 0,
            "fail": 0,
            "errors": [],
        }
        if not targets:
            logger.warning("[ctf_push] no whitelist targets resolved, skip push")
            return result

        for target in targets:
            try:
                await self.context.send_message(target, MessageChain().message(text))
                result["ok"] += 1
            except Exception as exc:
                result["fail"] += 1
                result["errors"].append(f"{target}: {exc}")
                logger.error(f"[ctf_push] push failed target={target}: {exc}")

        logger.info(
            "[ctf_push] daily push complete: targets=%d success=%d failed=%d",
            len(result["targets"]),
            result["ok"],
            result["fail"],
        )
        return result

    def _cleanup_sent_marks(self, now):
        today_prefix = now.strftime("%Y-%m-%d")
        self._sent_marks = {m for m in self._sent_marks if m.startswith(today_prefix)}

    def _refresh_runtime_config(self):
        latest = getattr(self, "config", None)
        if latest is None:
            return
        self.cfg = ConfigAdapter(latest)
        self.service.config = self.cfg

    def _sync_cards_to_db(self, now: datetime, cards: list[dict]):
        try:
            count = self.service.save_cards_snapshot(now, cards)
            logger.info(
                "[ctf_push] db synced rows=%d path=%s",
                count,
                str(self.service.store.db_path),
            )
        except Exception as exc:
            logger.error(f"[ctf_push] db sync failed: {exc}")

    def _extract_query_keyword(self, event: AstrMessageEvent) -> str:
        aliases = ("查询比赛", "比赛查询")
        for text in self._event_text_candidates(event):
            keyword = self._extract_query_from_text(text, aliases)
            if keyword:
                return keyword
        return ""

    def _event_text_candidates(self, event: AstrMessageEvent) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()

        def add_value(value):
            if value is None:
                return
            text = str(value).strip()
            if not text or text in seen:
                return
            seen.add(text)
            out.append(text)

        for attr in ("message_str", "raw_message", "raw_text", "text", "message", "content"):
            add_value(getattr(event, attr, None))

        for method_name in ("get_message_str", "get_plain_text", "get_message_text"):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    add_value(method())
                except Exception:
                    pass

        msg_obj = getattr(event, "message_obj", None)
        add_value(msg_obj)
        if msg_obj is not None:
            for attr in ("message_str", "raw_message", "text", "content"):
                add_value(getattr(msg_obj, attr, None))

        return out

    def _extract_query_from_text(self, text: str, aliases: tuple[str, ...]) -> str:
        normalized = str(text).strip()
        if not normalized:
            return ""

        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        for line in lines:
            for alias in aliases:
                for prefix in (f"/{alias}", alias):
                    if not line.startswith(prefix):
                        continue
                    tail = line[len(prefix) :].strip()
                    if tail.startswith((":", "：")):
                        tail = tail[1:].strip()
                    if tail:
                        return tail

        alias_pat = "|".join(re.escape(x) for x in aliases)
        for pattern in (
            rf"(?:^|\s)/(?:{alias_pat})\s+(.+)$",
            rf"(?:^|\s)(?:{alias_pat})\s+(.+)$",
        ):
            matched = re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL)
            if matched:
                value = matched.group(1).strip()
                if value:
                    return value
        return ""

    def _fmt_ts(self, value, tzinfo) -> str:
        if value in (None, ""):
            return "-"
        try:
            ts = int(value)
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tzinfo).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"

    def _description_snippet(self, value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""

        text = raw
        if raw[:1] in ("{", "["):
            try:
                parsed = json.loads(raw)
                chunks: list[str] = []
                self._extract_json_text(parsed, chunks)
                if chunks:
                    text = " ".join(chunks)
            except Exception:
                pass

        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 120:
            return text[:117] + "..."
        return text

    def _extract_json_text(self, node, out: list[str]):
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                out.append(node["text"])
            for value in node.values():
                self._extract_json_text(value, out)
            return
        if isinstance(node, list):
            for item in node:
                self._extract_json_text(item, out)
