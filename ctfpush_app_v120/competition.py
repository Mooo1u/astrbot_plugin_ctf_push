from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


def normalize_payload(raw: Any, default_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(default_payload)
    if not isinstance(raw, dict):
        return payload

    types_raw = raw.get("types", payload.get("types", [0, 1, 2]))
    if isinstance(types_raw, list):
        cleaned_types: list[int] = []
        for item in types_raw:
            try:
                val = int(item)
            except Exception:
                continue
            if val in (0, 1, 2):
                cleaned_types.append(val)
        if cleaned_types:
            payload["types"] = sorted(set(cleaned_types))

    ext_raw = raw.get("isExternal", payload.get("isExternal", 1))
    try:
        payload["isExternal"] = 1 if int(ext_raw) else 0
    except Exception:
        payload["isExternal"] = 1

    return payload


def fetch_cards(
    api_url: str,
    payload_raw: Any,
    timeout: int,
    default_payload: dict[str, Any],
    sensitive_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    payload = normalize_payload(payload_raw, default_payload)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
    }

    req = urllib.request.Request(
        url=api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid json from api") from exc

    cleaned = redact_json(data, sensitive_terms)
    collected = collect_items(cleaned)
    cards = [parse_card(item, hint) for item, hint in collected]
    return dedupe_cards(cards)


def dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for c in cards:
        cid = str(c.get("competition_id") or "").strip()
        if cid:
            sig = ("id", cid)
        else:
            sig = (
                "name-time",
                c["name"],
                c["start"].timestamp() if c["start"] else None,
                c["end"].timestamp() if c["end"] else None,
            )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    return out


def redact_json(value: Any, sensitive_terms: tuple[str, ...]) -> Any:
    def redact_text(text: str) -> str:
        out = text
        for term in sensitive_terms:
            out = re.sub(re.escape(term), "[redacted]", out, flags=re.IGNORECASE)
        return out

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            key_lower = key.lower()
            if any(term in key_lower for term in sensitive_terms):
                continue
            cleaned[redact_text(key)] = redact_json(v, sensitive_terms)
        return cleaned
    if isinstance(value, list):
        return [redact_json(v, sensitive_terms) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def collect_items(
    node: Any,
    hint: str | None = None,
    out: list[tuple[dict[str, Any], str | None]] | None = None,
) -> list[tuple[dict[str, Any], str | None]]:
    if out is None:
        out = []

    if isinstance(node, dict):
        for k, v in node.items():
            next_hint = bucket_hint_from_key(str(k)) or hint
            collect_items(v, next_hint, out)
        return out

    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node):
            matched = [x for x in node if looks_like_competition(x)]
            if matched:
                out.extend((x, hint) for x in matched)
                return out
        for x in node:
            collect_items(x, hint, out)
    return out


def looks_like_competition(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    has_name = any(k in item for k in ("name", "title", "competitionName", "eventName"))
    has_time = any(
        k in item
        for k in (
            "startTime",
            "startAt",
            "competitionStartTime",
            "beginTime",
            "gameStartTime",
            "endTime",
            "endAt",
            "competitionEndTime",
            "finishTime",
            "gameEndTime",
            "preSignUpStartTime",
            "registerStartTime",
            "registerEndTime",
        )
    )
    return has_name and has_time


def bucket_hint_from_key(key: str) -> str | None:
    norm = re.sub(r"[\s_-]+", "", key.lower())
    if any(x in norm for x in ("running", "ongoing", "live", "inprogress", "进行")):
        return "ongoing"
    if any(x in norm for x in ("registering", "signup", "enroll", "presignup", "报名")):
        return "registering"
    if any(x in norm for x in ("upcoming", "coming", "notstarted", "即将", "未开始")):
        return "upcoming"
    return None


def parse_card(item: dict[str, Any], hint: str | None) -> dict[str, Any]:
    raw_desc = pick(item, "description", "desc", "introduction", "intro", "content")
    return {
        "competition_id": str(pick(item, "id", "competitionId", "eventId", "gameId") or ""),
        "name": str(pick(item, "name", "title", "competitionName", "eventName") or "未命名比赛"),
        "short_name": str(pick(item, "shortName", "short_name", "abbr", "alias") or ""),
        "description": normalize_description(raw_desc),
        "start": parse_dt(
            pick(item, "startTime", "startAt", "competitionStartTime", "beginTime", "gameStartTime")
        ),
        "end": parse_dt(pick(item, "endTime", "endAt", "competitionEndTime", "finishTime", "gameEndTime")),
        "reg_start": parse_dt(
            pick(
                item,
                "registerStartTime",
                "registrationStartTime",
                "signupStartTime",
                "enrollStartTime",
                "preSignUpStartTime",
            )
        ),
        "reg_end": parse_dt(
            pick(
                item,
                "registerEndTime",
                "registrationEndTime",
                "signupEndTime",
                "enrollEndTime",
                "preSignUpEndTime",
            )
        ),
        "status": str(
            pick(item, "statusName", "statusText", "status", "state", "competitionStatus", "stage", "phase")
            or ""
        ).lower(),
        "pre_signup": bool(item.get("isPreSignUp") or item.get("preSignUp")),
        "allow_join": bool(item.get("isAllowJoin") or item.get("allowJoin") or item.get("canJoin")),
        "hint": hint,
        "raw": item,
    }


def normalize_description(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def pick(item: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in item and item[k] not in (None, "", []):
            return item[k]
    return None


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        n = int(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.isdigit():
            n = int(s)
        else:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
            ):
                try:
                    return datetime.strptime(s, fmt).astimezone()
                except ValueError:
                    pass
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()
            except ValueError:
                return None
    else:
        return None

    if n >= 1_000_000_000_000:
        return datetime.fromtimestamp(n / 1000, tz=timezone.utc).astimezone()
    if n >= 1_000_000_000:
        return datetime.fromtimestamp(n, tz=timezone.utc).astimezone()
    return None


def classify(card: dict[str, Any], now: datetime) -> str:
    start = card["start"]
    end = card["end"]
    reg_start = card["reg_start"]
    reg_end = card["reg_end"]
    status = card["status"]
    hint = card["hint"]

    if end and end < now:
        return "ended"
    if start and start <= now and (not end or now <= end):
        return "ongoing"

    if any(x in status for x in ("进行", "running", "ongoing", "live")):
        return "ongoing"
    if any(x in status for x in ("报名", "register", "signup", "enroll")) and (not start or now < start):
        return "registering"

    if reg_start and reg_end and reg_start <= now <= reg_end and (not start or now < start):
        return "registering"
    if reg_start and not reg_end and reg_start <= now and (not start or now < start):
        return "registering"
    if card["pre_signup"] and card["allow_join"] and (not start or now < start):
        return "registering"

    if hint == "ongoing":
        return "ongoing"
    if hint == "registering" and (not start or now < start):
        return "registering"
    return "upcoming"
