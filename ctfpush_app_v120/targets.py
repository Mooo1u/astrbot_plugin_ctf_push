from __future__ import annotations

from typing import Any


def flatten_targets(raw: Any) -> list[str]:
    out: list[str] = []

    def walk(v: Any):
        if v is None:
            return
        if isinstance(v, (str, int)):
            s = str(v).strip()
            if s:
                out.append(s)
            return
        if isinstance(v, list):
            for item in v:
                walk(item)
            return
        if isinstance(v, dict):
            for key in ("umo", "unified_msg_origin", "target", "value", "group_id", "groupId", "id"):
                if key in v:
                    walk(v[key])
                    return
            for item in v.values():
                if isinstance(item, (str, int)):
                    walk(item)

    walk(raw)
    return out


def resolve_targets(raw: Any, known_targets: dict[str, str]) -> tuple[list[str], list[str]]:
    candidates = flatten_targets(raw)
    targets: list[str] = []
    missing_numeric: list[str] = []

    for item in candidates:
        key = str(item).strip()
        if not key:
            continue
        if not key.isdigit():
            targets.append(key)
            continue
        if key in known_targets:
            targets.append(known_targets[key])
        else:
            targets.append(key)
            missing_numeric.append(key)

    seen = set()
    deduped: list[str] = []
    for t in targets:
        if t in seen:
            continue
        seen.add(t)
        deduped.append(t)
    return deduped, missing_numeric


def extract_event_group_mapping(event: Any) -> tuple[str, str] | None:
    try:
        group_id = event.get_group_id()
    except Exception:
        group_id = None
    if not group_id:
        return None

    group_key = str(group_id)

    umo = getattr(event, "unified_msg_origin", None)
    if not umo and hasattr(event, "get_unified_msg_origin"):
        try:
            umo = event.get_unified_msg_origin()
        except Exception:
            umo = None
    if not umo:
        return None

    return group_key, str(umo)
