from __future__ import annotations

from datetime import datetime, timedelta


def parse_push_times(push_time: str | None, fallback_hour: int, fallback_minute: int) -> list[tuple[int, int]]:
    if isinstance(push_time, str) and push_time.strip():
        out: list[tuple[int, int]] = []
        for part in push_time.replace("，", ",").split(","):
            item = part.strip()
            if not item:
                continue
            bits = item.split(":")
            if len(bits) != 2:
                continue
            try:
                hour, minute = int(bits[0]), int(bits[1])
            except Exception:
                continue
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                out.append((hour, minute))
        if out:
            return sorted(set(out))

    hour = max(0, min(23, int(fallback_hour)))
    minute = max(0, min(59, int(fallback_minute)))
    return [(hour, minute)]


def calculate_sleep_time(now: datetime, times: list[tuple[int, int]]) -> tuple[float, datetime]:
    candidates: list[datetime] = []
    for hour, minute in times:
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= now:
            dt = dt + timedelta(days=1)
        candidates.append(dt)

    if not candidates:
        fallback = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if fallback <= now:
            fallback = fallback + timedelta(days=1)
        candidates.append(fallback)

    next_dt = min(candidates)
    return (next_dt - now).total_seconds(), next_dt
