"""시도·동 단위 동네예보 답."""
from __future__ import annotations

import datetime as dt
import logging

from src.advice.rules import build_advice
from src.common.text import day_label
from src.kma.dong_forecast import DongError, fetch_dong
from src.mention.foliage.note import _foliage_note
from src.mention.parse import DONG_MAX_DAYS
from src.mention.snow.note import _snow_note
from src.mention.texts import NO_EMOJI, help_text, self_mention, sky_emoji

log = logging.getLogger("weather-mention")


def _dong_advice(summary, region: str = "") -> list:
    from types import SimpleNamespace

    days = [
        SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo, tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)
        for d, lo, hi, sky, pop in summary
    ]
    return build_advice(days, region=region)


def _partial_start(fc, date: dt.date) -> int | None:
    hours = [p.when.hour for p in getattr(fc, "points", ()) if p.when.date() == date]
    return min(hours) if hours and min(hours) > 0 else None


def _dong_reply(zone: str, name: str, days: int = 4, start: dt.date | None = None,
                *, quiet: bool = False, today: dt.date | None = None) -> str:
    """동·시도 단위 동네예보. quiet 이면 실패·빈 결과에 안내문 대신 빈 문자열(산 답에 붙일 때)."""
    try:
        fc = fetch_dong(zone, name)
    except DongError as exc:
        log.warning("동네예보 실패: %s", exc)
        if quiet:
            return ""
        return (
            f"*{name}* 동네예보를 가져오지 못했습니다.\n"
            f"광역 구역으로는 7일치를 볼 수 있습니다 — 예: {self_mention()} 수도권\n\n{help_text()}"
        )

    available = fc.daily_summary()
    summary = available
    if start is not None:
        summary = [row for row in available if row[0] >= start][:max(1, days)]
        if not summary:
            if quiet:
                return ""
            return (
                f"*{name}* 동네예보는 오늘부터 {DONG_MAX_DAYS}일까지만 제공됩니다. {NO_EMOJI}\n"
                f"그 이후는 광역 구역으로 불러 주세요. 예: {self_mention()} 수도권"
            )
    else:
        summary = summary[:max(1, days)]
    scope = (day_label(summary[0][0]) if len(summary) == 1
             else f"{day_label(summary[0][0])} ~ {day_label(summary[-1][0])}")
    lines = [f"*{fc.name}* 동네예보 ({scope})"]
    # 오늘 줄은 발표 이후 남은 몇 시간의 값뿐 — «N시 이후» 를 달고, 최저·최고 강조와 조언에서 뺌
    partial = {row[0]: h for row in summary if (h := _partial_start(fc, row[0]))}
    whole = [row for row in summary if row[0] not in partial] or summary
    coldest = min(whole, key=lambda r: r[1])[0] if whole else None
    hottest = max(whole, key=lambda r: r[2])[0] if whole else None
    for date, lo, hi, sky, pop in summary:
        temp = f"{lo:.0f}~{hi:.0f}℃"
        if date in (coldest, hottest) and date not in partial:
            temp = f"*{temp}*"
        since = f"{partial[date]}시 이후 " if date in partial else ""
        lines.append(
            f"• `{day_label(date)}` {since}{temp} · {sky_emoji(sky)}"
            + (f" · `{pop}%`" if pop else "")
        )
    tips = _dong_advice([row for row in summary if row[0] not in partial], fc.name)
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]
    lines.append(f"_기상청 동네예보 · {fc.issued} 발표_")
    # 광역 안내는 자료 끝날까지 보여 줬을 때만 — 끝날은 발표 시각마다 달라(글피·그글피) 일수로 못 잼.
    # 하루치 답(본문이 짧음)과 산 답(quiet)에는 붙이지 않음.
    if not quiet and len(summary) > 1 and summary[-1][0] == available[-1][0]:
        lines.append(f"_더 먼 날이 필요하시면 광역 구역으로 불러 주세요 (최대 10일). "
                     f"예: {self_mention()} 수도권_")
    if today is not None:
        lines += _foliage_note(zone, summary[0][0], summary[-1][0], today)
        lines += _snow_note(zone, [(row[0], row[3]) for row in summary], today)
    return "\n".join(lines)
