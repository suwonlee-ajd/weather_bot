"""철마다 주간 게시에 붙이는 소식(테마) — 영역 3~6 의 덩어리(Block) 조립. 순서는 pipeline.SECTIONS.

모델에 맡기지 않음 — 지어낸 개화일·단풍일·태풍 이름은 그럴듯해서 알아채기 어려움. 수집이 실패하면 예외를 그대로
올려 pipeline 이 그 영역만 빼고 게시함. 기간은 우리가 정하지 않음 — 다룰 때인지는 자료가 정함:

  벚꽃  기상청 관측 중이거나, 관측 전 올해 첫 개화 예상일까지   예상 웨더아이 + 지도 (기상청은 기간만)
  장마  예보관 서술에 장마·정체전선이 있을 때                     그 주 예보 (따로 받지 않음)
  폭염  기준(낮 최고 33℃·아침 최저 25℃)에 닿는 날이나 예보관 언급이 있을 때  그 주 예보 (따로 받지 않음) + 도시 지도
  태풍  예보관이 태풍을 말하고 기상청 목록에 진행 중일 때     현재·예상 기상청 태풍정보 · 예보관 서술 + 예상 경로 지도
  단풍  기상청 관측 중이거나, 관측 전 올해 첫 예상일까지        관측 기상청 · 예상 웨더아이 + 지도
  첫눈  지난 7일 안에 관측됐거나, 아직인 곳에 그 주 눈 예보가 있을 때  관측 기상청 계절관측 · 평년 + 지도
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from src.advice.rules import RAIN_LIKELY
from src.common.text import bold, short_date
from src.kma import typhoon
from src.kma.page import Narrative
from src.season import narrative
from src.season.basemap import MapInfo
from src.season.blossom import data as blossom
from src.season.blossom import map as blossom_map
from src.season.blossom import text as blossom_text
from src.season.foliage import data as foliage
from src.season.foliage import map as foliage_map
from src.season.foliage import text as foliage_text
from src.season.heat import data as heat
from src.season.heat import map as heat_map
from src.season.heat import text as heat_text
from src.season.monsoon import data as monsoon
from src.season.monsoon import text as monsoon_text
from src.season.snow import data as snow
from src.season.snow import map as snow_map
from src.season.snow import text as snow_text
from src.season.typhoon import map as typhoon_map
from src.weekly.forecast import WeekForecast
from src.weekly.paragraph import Block, Paragraph
from src.weekly.sections import Context

log = logging.getLogger(__name__)


def _with_map(ctx: Context, paragraph: Paragraph, info: MapInfo, render: Callable[[], bytes], sources: str) -> Block:
    """지도를 못 그려도 글은 남김 — 출처의 «X 지도» 도 실린 것에 맞춰 «X» 로."""
    att = ctx.image(info.slug, info.title, info.alt, render)
    return Block(paragraph, f"{info.title if att else info.name} · {sources}", att)


def foliage_block(ctx: Context) -> Block | None:
    snap = foliage.fetch_snapshot(ctx.today)
    if not snap.showing(ctx.week_start):
        return None
    paragraph = (Paragraph("이번 주 단풍", emoji=":maple_leaf:")
                 .add("관측", foliage_text.observed_line(snap, bold, day=ctx.week_start))
                 .add("이번 주", foliage_text.week_line(snap, ctx.week_start, ctx.week_end, bold,
                                                         muted=lambda s: s)))
    # 출처는 실린 것에 맞춤 — 예상을 못 읽었으면 예상 출처도 뺌
    return _with_map(ctx, paragraph, foliage_map.INFO,
                     lambda: foliage_map.render_png(snap, ctx.week_start, scale=ctx.scale), foliage_text.sources(snap))


def blossom_block(ctx: Context) -> Block | None:
    """싣는 것은 웨더아이 도시 예상뿐 — 기상청 목록은 다룰 때인지만 가름. 예상 수집 실패는 예외로 올림."""
    try:
        status = blossom.fetch_status()
    except blossom.BlossomError as exc:
        log.warning("기상청 벚꽃 관측 기간을 받지 못해 웨더아이 예상만으로 가릅니다 — %s", exc)
        status = None
    # 지난해 표의 평년은 기상청이 관측 중일 때만 실음 — 그 밖엔 받지 않음(철 밖에도 매주 돌기 때문)
    outlook = blossom.fetch_outlook(ctx.week_start.year, borrow_normal=bool(status and status.in_service))
    if not (outlook.expected or outlook.normal) or not blossom.showing(status, outlook, ctx.week_start):
        return None
    paragraph = (Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:")
                 .add("이번 주", blossom_text.week_line(outlook, ctx.week_start, ctx.week_end))
                 .add("올해" if outlook.expected else "평년", blossom_text.year_line(outlook)))
    return _with_map(ctx, paragraph, blossom_map.INFO,
                     lambda: blossom_map.render_png(outlook, ctx.week_start, scale=ctx.scale),
                     blossom_text.sources(outlook))


def typhoon_block(ctx: Context) -> Block | None:
    """예보관이 태풍을 말하고 기상청 목록에 진행 중인 태풍이 있을 때만. 예상 경로 지도는 태풍이 여럿이어도 한 장.

    멀리 있는 태풍(괌 근처 등)은 예보관이 말하지 않으면 싣지 않음(사용자 결정). 태풍정보를 받지 못했어도
    예보관 서술에 태풍이 있으면 그 줄만 글로 실음 — 위험 신호를 영역 실패로 묻지 않게. 그때는 그릴 경로가 없음.
    """
    week = ctx.forecast()
    mentioned = _typhoon_lines(week.narratives if week else [])
    if not mentioned:
        return None                       # 예보관이 태풍을 말하지 않음 — 태풍정보도 받지 않음
    try:
        storms = typhoon.fetch_active()
    except typhoon.TyphoonError as exc:
        log.warning("기상청 태풍정보를 받지 못해 예보관 서술만 싣습니다 — %s", exc)
        storms = None
    if storms == []:
        return None                       # 목록이 비었음 — 서술의 «태풍» 은 발생 가능성만 말하는 줄일 수 있음
    body = ctx.body()
    quotes = [q for q in mentioned if not narrative.in_body(q[0], body)][:narrative.MAX_QUOTES]
    storms = storms or []

    paragraph = Paragraph("이번 주 태풍", emoji=":cyclone:")
    for storm in storms:
        weakened = f" {storm.weakened}" if storm.weakened else ""
        paragraph.add("현재", f"{bold(storm.title)}{weakened} · {storm.now.summary} ({storm.now.when} 기준)")
        ahead = [p for p in storm.forecast if p.at.date() <= ctx.week_end]
        name = f"{storm.name} " if len(storms) > 1 else ""
        paragraph.add("예상", f"{name}{ahead[-1].when} {ahead[-1].place}" if ahead else "")
    paragraph.add("이번 주", " / ".join(narrative.quote(text) for text, _ in quotes))
    sources = _typhoon_sources(storms, quotes)
    if not storms:
        return Block(paragraph, f"태풍 · {sources}")
    return _with_map(ctx, paragraph, typhoon_map.INFO,
                     lambda: typhoon_map.render_png(storms, ctx.week_start, scale=ctx.scale), sources)


def _notice_first(n: Narrative) -> int:
    """통보문(가까운 날)을 중기예보보다 먼저 — 수집 순서는 중기예보가 앞이고, 인용 개수를 넘으면 뒤쪽이 잘림."""
    return 0 if "통보문" in n.title else 1


def _typhoon_lines(narratives: list[Narrative]) -> list[tuple[str, Narrative]]:
    """예보관 서술에서 태풍을 말한 줄과 그 서술 — 출처 줄에 실린 서술만 적으려고 짝지음."""
    out: list[tuple[str, Narrative]] = []
    for source in sorted(narratives, key=_notice_first):
        out += [(text, source) for text in narrative.mentioning(source.lines, ("태풍",))
                if all(text != seen for seen, _ in out)]
    return out


def _typhoon_sources(storms: list[typhoon.Typhoon], quotes: list[tuple[str, Narrative]]) -> str:
    """실린 줄의 출처만 — «기상청 태풍정보(11/16 16시 발표) · 기상청 예보 통보문»."""
    parts = []
    if storms:
        issued = max((s.issued for s in storms if s.issued), default=None)
        parts.append("기상청 태풍정보" + (f"({short_date(issued)} {issued.hour}시 발표)" if issued else ""))
    parts.extend(dict.fromkeys(n.title for _, n in quotes))
    return " · ".join(parts)


def snow_block(ctx: Context) -> Block | None:
    """«이번 주» 줄과 다룰지는 1번 날씨 예보의 하늘상태에서 눈을 셈."""
    status = snow.fetch_status(ctx.today, timeout=snow.WEEKLY_TIMEOUT_SEC, retries=1)
    week = ctx.forecast()
    days = week.days if week else None
    # «최근» 은 오늘까지 — 주 중간에 돌리면 월요일 뒤의 관측도 셈. 다음 주 미리 보기는 그 월요일 기준
    as_of = max(ctx.today, ctx.week_start)
    if not snow.showing(status, as_of, snowy=bool(days and snow_text.snow_days(days))):
        return None
    paragraph = (Paragraph("이번 주 첫눈", emoji=":snowflake:")
                 .add("관측", snow_text.observed_line(status, bold))
                 .add("이번 주", snow_text.week_line(status, days, muted=lambda s: s)))
    # days 가 None 이면 지도도 «예보를 받지 못했습니다» — 글과 같은 말을 하게 그대로 넘김
    return _with_map(ctx, paragraph, snow_map.INFO,
                     lambda: snow_map.render_png(status, ctx.week_start, days, scale=ctx.scale),
                     snow_text.SOURCES)


def _lines(week: WeekForecast) -> list[str]:
    return [line for n in sorted(week.narratives, key=_notice_first) for line in n.lines]


def _quote_rows(paragraph: Paragraph, mentioned: list[str], ctx: Context) -> Paragraph:
    for text in narrative.unquoted(mentioned, ctx.body()):
        paragraph.add("예보관", narrative.quote(text))
    return paragraph


def monsoon_block(ctx: Context) -> Block | None:
    """예보관이 장마·정체전선을 말할 때만. 비 오는 날은 본문 조언과 같은 문턱(RAIN_LIKELY)."""
    week = ctx.forecast()
    if week is None:
        return None
    found = monsoon.read(week.days, _lines(week), pop_at=RAIN_LIKELY)
    if not found.showing:
        return None
    paragraph = _quote_rows(Paragraph(monsoon_text.title(found), emoji=":rain_cloud:"), found.mentioned, ctx)
    paragraph.add("비 예보", monsoon_text.rain_line(found))
    return Block(paragraph, f"장마 · {monsoon_text.SOURCES}")


def heat_block(ctx: Context) -> Block | None:
    """기상청 폭염일·열대야 기준에 닿는 날이나 예보관 언급이 있을 때만. 조언은 본문 2문단에 맡기고 사실만."""
    week = ctx.forecast()
    if week is None:
        return None
    found = heat.read(week.days, _lines(week))
    if not found.showing:
        return None
    paragraph = _quote_rows(Paragraph("이번 주 더위", emoji=":hot_face:")
                            .add(heat_text.HOT_LABEL, heat_text.hot_line(found))
                            .add(heat_text.NIGHT_LABEL, heat_text.night_line(found)), found.mentioned, ctx)
    if not found.cities:            # 도시별 값(중기예보)이 없는 주 — 그릴 것이 없어 글만
        return Block(paragraph, f"더위 · {heat_text.SOURCES}")
    return _with_map(ctx, paragraph, heat_map.INFO,
                     lambda: heat_map.render_png(found, ctx.week_start, scale=ctx.scale),
                     heat_text.SOURCES)
