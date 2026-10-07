"""시도·동 단위 동네예보 답."""
from __future__ import annotations

import datetime as dt
import logging

from src.advice.rules import build_advice
from src.common.text import day_label
from src.kma.dong_forecast import DongError, fetch_dong
from src.mention.foliage_note import _foliage_note
from src.mention.parse import DONG_MAX_DAYS
from src.mention.texts import NO_EMOJI, help_text, self_mention, sky_emoji
from src.season.mountains import (
    in_zone,
)

log = logging.getLogger("weather-mention")


def _dong_advice(summary, region: str = "") -> list:
    """동네예보 일별 요약(날짜, 최저, 최고, 하늘, 강수)을 조언 입력 형태로 맞춤."""
    from types import SimpleNamespace

    days = [
        SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo, tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)
        for d, lo, hi, sky, pop in summary
    ]
    return build_advice(days, region=region)


def _partial_start(fc, date: dt.date) -> int | None:
    """그날 예보가 0시보다 늦게 시작하면 그 시각 — 발표 이후 남은 시간만 있는 오늘 줄."""
    hours = [p.when.hour for p in getattr(fc, "points", ()) if p.when.date() == date]
    return min(hours) if hours and min(hours) > 0 else None


def _dong_reply(zone: str, name: str, days: int = 4, start: dt.date | None = None,
                *, quiet: bool = False, today: dt.date | None = None) -> str:
    """동·시도 단위 동네예보. 닿는 날까지만 보여주고, 더 필요하면 광역으로 안내함.

    quiet 이면 실패하거나 그날 예보가 없을 때 안내문 대신 빈 문자열 — 다른 답(산 단풍)
    뒤에 덧붙일 때 도움말 전문이 끼어들지 않게.
    today 를 주면 단풍철에 그 동네 산의 단풍 한 줄을 붙임 — 예보를 보여 줬을 때만,
    보여 준 날짜 범위로.
    """
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
    # 오늘 줄은 발표 이후 남은 시간의 값뿐 — 하루치 최저~최고로 읽히지 않게 «N시 이후» 를 붙이고,
    # 그 주에서 가장 춥고 더운 날을 고르는 굵게 표시에서도 뺌(밤 몇 시간 값이 «최저» 로 뽑히지 않게).
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
    # 조언도 하루치 값만으로 — 저녁 발표의 오늘 줄(밤 몇 시간)이 «아침 최저 N도» 로 읽히지 않게
    tips = _dong_advice([row for row in summary if row[0] not in partial], fc.name)
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]
    lines.append(f"_기상청 동네예보 · {fc.issued} 발표_")
    # 광역 안내는 «동네예보 자료 끝까지 보여 줬을 때» 만 함. 끝날은 발표 시각마다 다름(오전·낮 발표는
    # 글피, 17·20시 발표는 그글피) — 일수로 재면 4일치 발표에서는 끝까지 보여 줘도 안내가 붙지 않음.
    # 하루치 답에서는 쓸모없이 두 줄 본문의 절반을 차지하고, 같은 꼬리말 탓에 다른 지역을 물은
    # 두 답이 같은 메시지로 읽힘.
    # quiet(산 답) 에서는 붙이지 않음 — 산 단풍 사이에 «예: 수도권» 이 끼어들면 엉뚱함.
    if not quiet and len(summary) > 1 and summary[-1][0] == available[-1][0]:
        lines.append(f"_더 먼 날이 필요하시면 광역 구역으로 불러 주세요 (최대 10일). "
                     f"예: {self_mention()} 수도권_")
    if today is not None:
        lines += _foliage_note(in_zone(zone), summary[0][0], summary[-1][0], today)
    return "\n".join(lines)
