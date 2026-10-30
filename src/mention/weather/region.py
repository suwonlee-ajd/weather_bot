"""광역 구역의 기간 예보 답 — 날짜별 기온·하늘·강수확률, 조언, 예보관 서술, 단풍 한 줄."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import replace

from src.advice.rules import build_advice, topic_advice
from src.common.text import day_label, range_text
from src.kma.notice import lines_for_dates
from src.kma.page import ScrapeError
from src.kma.regions import Region
from src.mention.foliage.note import _foliage_note
from src.mention.forecast import cached_scrape, days_in
from src.mention.snow.note import _snow_note
from src.mention.texts import NO_EMOJI, sky_emoji

log = logging.getLogger("weather-mention")

def region_reply(region: Region, note: str, title: str, start: dt.date, days: int, topic: str | None,
                 now: dt.datetime) -> str:
    try:
        cached = cached_scrape(region, now)
        scrape = replace(cached, days=days_in(cached, start, days))
    except ScrapeError as exc:
        log.warning("수집 실패: %s", exc)
        return "기상청 예보를 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요."

    if not scrape.days:
        return f"*{region.label}* {start:%m/%d} 부터의 예보를 찾지 못했습니다."

    end = start + dt.timedelta(days=days - 1)
    # 머리글은 예보가 있는 날까지만 — 주 초의 «다음 주» 는 열흘 안에 사흘만 걸침
    have = max(scrape.days) if scrape.days else end
    shown_end = min(end, have)
    span_text = (day_label(start) if start == shown_end
                 else f"{day_label(start)} ~ {day_label(shown_end)}")
    lines = [f"*{region.label}* {title} ({span_text})"]
    if note:
        lines.append(f"_{note}_")
    complete = [
        scrape.days[d] for d in sorted(scrape.days)
        if scrape.days[d].tmin_lo is not None and scrape.days[d].tmax_hi is not None
    ]
    coldest = min(complete, key=lambda d: d.tmin_lo).date if complete else None
    hottest = max(complete, key=lambda d: d.tmax_hi).date if complete else None

    for offset in range((shown_end - start).days + 1):
        date = start + dt.timedelta(days=offset)
        v = scrape.days.get(date)
        if v is None:
            continue
        morning = range_text(v.tmin_lo, v.tmin_hi) or "-"
        noon = range_text(v.tmax_lo, v.tmax_hi) or "-"
        parts = [
            f"아침 *{morning}*" if date == coldest else f"아침 {morning}",
            f"낮 *{noon}*" if date == hottest else f"낮 {noon}",
        ]
        if v.sky:
            parts.append(sky_emoji(v.sky))
        if v.pop is not None:
            parts.append(f"`{v.pop}%`")
        lines.append(f"• `{day_label(date)}` " + " · ".join(parts))

    if shown_end < end:
        lines.append(f"_{day_label(shown_end + dt.timedelta(days=1))} 이후는 "
                     f"아직 예보가 작성되지 않았습니다 {NO_EMOJI}_")

    shown = [scrape.days[d] for d in sorted(scrape.days)]
    # 조언은 보인 날만 근거로 — 캐시는 열흘을 들고 있음
    window = {start + dt.timedelta(days=i) for i in range(days)}
    scoped = [d for d in shown if d.date in window]
    narrative_lines = [line for n in scrape.narratives for line in n.lines]
    tips = topic_advice(topic, scoped, region.key) if topic else []
    # 겹침은 이모지로 가림 — 문구는 날마다 달라 문장으로 견주면 우산 조언이 두 줄 나감
    seen = {x.emoji for x in tips}
    tips += [t for t in build_advice(scoped, narrative_lines, region.key)
             if t.emoji not in seen][: 3 - len(tips)]
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]

    for narrative in sorted(scrape.narratives, key=lambda n: 0 if "통보문" in n.title else 1):
        # 물은 날짜의 줄만 — 앞 2줄을 자르면 «모레» 에 «(오늘, 12일)» 이 붙음
        picked = lines_for_dates(narrative.lines, now.date(), window)
        for line in picked[:2]:
            lines.append(f"> {line}")
        stamp = f"{narrative.issued_at:%m/%d %H시}" if narrative.issued_at else "발표시각 미상"
        lines.append(f"_{narrative.title} · {stamp} 발표_")

    lines += _foliage_note(region, start, shown_end, now.date())
    lines += _snow_note(region, [(d.date, d.sky) for d in shown if d.date <= shown_end], now.date())
    return "\n".join(lines)
