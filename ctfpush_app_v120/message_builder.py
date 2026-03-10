from __future__ import annotations

from datetime import datetime

from .competition import classify


def build_today_message(
    now: datetime,
    cards: list[dict],
    section_separator: str,
    include_header: bool = True,
) -> str:
    ongoing: list[dict] = []
    registering: list[dict] = []
    upcoming: list[dict] = []

    for c in cards:
        bucket = classify(c, now)
        if bucket == "ended":
            continue
        if bucket == "ongoing":
            ongoing.append(c)
        elif bucket == "registering":
            registering.append(c)
        else:
            upcoming.append(c)

    ongoing = sort_by_start(ongoing)
    registering = sort_by_start(registering)
    upcoming = sort_by_start(upcoming)

    lines: list[str] = []
    if include_header:
        lines.append(f"【CTF 比赛推送 {now.strftime('%Y-%m-%d')}】")
    lines.append(section_separator)
    lines.extend(render_section("正在进行", ongoing))
    lines.append(section_separator)
    lines.extend(render_section("即将开始", upcoming, limit=3))
    lines.append(section_separator)
    lines.extend(render_section("正在报名", registering))
    lines.append(section_separator)
    return "\n".join(lines)


def render_section(title: str, cards: list[dict], limit: int | None = None) -> list[str]:
    total = len(cards)
    shown = cards[:limit] if limit is not None else cards
    count_text = f"{len(shown)}/{total}" if limit is not None else str(total)

    lines = [f"{title} ({count_text})"]
    if not shown:
        lines.append("  暂无")
        return lines
    for idx, card in enumerate(shown, 1):
        lines.append(f"{idx}. {card['name']}")
        lines.append(f"   开始: {fmt(card['start'])}")
        lines.append(f"   结束: {fmt(card['end'])}")
        lines.append(f"   报名: {fmt(card['reg_start'])} ~ {fmt(card['reg_end'])}")
    return lines


def sort_by_start(cards: list[dict]) -> list[dict]:
    return sorted(cards, key=lambda x: (x["start"] is None, x["start"] or datetime.max.astimezone()))


def fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"
