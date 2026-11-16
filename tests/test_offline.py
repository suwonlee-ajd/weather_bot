"""API 키 없이 도는 검증 — python -m tests.test_offline (일기도만 실제 기상청을 부름)."""
from __future__ import annotations

import datetime as dt
import os
import pathlib

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_CHANNEL_ID", "C_TEST")

from src.common.config import KST  # noqa: E402
from src.kma.chart import PNG_MAGIC, fetch_latest_chart  # noqa: E402
from src.kma.page import Narrative, ScrapedDay, _resolve_date
from src.kma.regions import find_region, resolve_region
from src.mention.answer import build_reply  # noqa: E402
from src.weekly.body import fallback  # noqa: E402
from src.weekly.card import render_png  # noqa: E402
from src.weekly.forecast import DayForecast, WeekForecast  # noqa: E402
from src.weekly.writer import extract_json  # noqa: E402

# 본 실행과 같은 자리 — .gitignore·보존 정리가 이곳만 봄
IMG = pathlib.Path("data/img")
WEEK_START = dt.date(2026, 9, 7)


def fake_week() -> WeekForecast:
    days = [
        DayForecast(
            date=WEEK_START + dt.timedelta(days=i),
            tmin_lo=18, tmin_hi=24,
            tmax_lo=25 if i < 4 else 22, tmax_hi=33 if i < 4 else 29,
            sky="구름많음" if i < 4 else "흐리고 비",
            pop=30 if i < 4 else 80,
            source="통보문" if i < 4 else "중기예보",
        )
        for i in range(7)
    ]
    narratives = [
        Narrative("기상청 예보 통보문", "https://www.weather.go.kr/w/forecast/notice.do",
                  dt.datetime(2026, 9, 7, 6, 0, tzinfo=KST),
                  ["□ (종합) 당분간 낮과 밤 기온차 큼, 내일까지 풍랑과 너울 유의"]),
        Narrative("기상청 중기예보", "https://www.weather.go.kr/w/forecast/overall/mid-term.do",
                  dt.datetime(2026, 9, 7, 6, 0, tzinfo=KST),
                  ["○ (기온) 이번 예보기간 아침 기온은 18~24℃, 낮 기온은 25~33℃로 평년과 비슷하겠습니다."]),
    ]
    week = WeekForecast(area="전국", week_start=WEEK_START, days=days, narratives=narratives)
    written = fallback(week)
    week.lead, week.sections, week.alerts = written.lead, written.sections, written.alerts
    return week


def test_log_dir() -> None:
    """LOG_DIR 이 없으면 저장소의 logs/ — 패키지를 옮겨도 src/ 아래로 새지 않음."""
    from src.common.logsetup import log_dir

    saved = os.environ.pop("LOG_DIR", None)
    try:
        assert log_dir() == pathlib.Path(__file__).resolve().parents[1] / "logs", log_dir()
    finally:
        if saved is not None:
            os.environ["LOG_DIR"] = saved
    print("[ok] 로그 위치 — 저장소의 logs/")


def test_session_log_filter() -> None:
    """Bolt 연결 잡담은 버리고 세션 수립 줄과 WARNING 이상만 남김 — 재연결 확인용."""
    import logging

    from src.mention.bot import session_only

    def record(level: int, msg: str) -> logging.LogRecord:
        return logging.LogRecord("slack_bolt.App", level, __file__, 0, msg, None, None)

    assert session_only(record(logging.INFO, "A new session has been established (session id: x)"))
    assert not session_only(record(logging.INFO, "Connecting to a new endpoint..."))
    assert not session_only(record(logging.INFO, "The connection has been closed (session id: x)"))
    assert session_only(record(logging.WARNING, "Failed to check the current session or reconnect"))
    print("[ok] 슬랙 로그 — 세션 수립과 WARNING 이상만")


def test_extract_json() -> None:
    assert extract_json('```json\n{"lead": "가"}\n```')["lead"] == "가"
    assert extract_json('설명입니다.\n{"lead": "나"}\n끝')["lead"] == "나"
    print("[ok] JSON 추출 (코드펜스/잡설 제거)")


def test_find_region() -> None:
    cases = {
        "전국": "전국", "": "전국", None: "전국",
        "부산": "부산·울산·경남", "울산": "부산·울산·경남", "창원": "부산·울산·경남",
        "대구": "대구·경북", "포항": "대구·경북",
        "서울": "서울·인천·경기", "경기도": "서울·인천·경기",
        "청주": "충북", "대전": "대전·세종·충남",
        "제주도": "제주", "강릉": "강원 영동",
        "부산 날씨 알려줘": "부산·울산·경남",
    }
    for query, want in cases.items():
        got = find_region(query)
        assert got is not None and got.label == want, f"{query!r} -> {got and got.label} != {want}"
    assert find_region("화성") is None, "모르는 지역은 None 이어야 합니다"
    assert find_region("도쿄") is None
    print(f"[ok] 지역 해석 {len(cases)}건 + 미지원 지역 거절")


def test_wide_areas() -> None:
    """중부·남부·영남·호남 같은 말과 영동/영서를 알아듣는지."""
    cases = {
        "중부": "서울·인천·경기", "남부": "부산·울산·경남",
        "영남": "부산·울산·경남", "호남": "광주·전남", "충청": "대전·세종·충남",
        "영동": "강원 영동", "영서": "강원 영서", "관동": "강원",
    }
    for query, want in cases.items():
        region, note = resolve_region(query)
        assert region is not None and region.label == want, f"{query} -> {region and region.label}"
        # 기상청 구역이 아닌 말에만 해석 안내를 붙임
        if query in ("중부", "남부", "영남", "호남", "충청"):
            assert note, f"{query}: 해석 안내문이 없습니다"
    assert resolve_region("영동")[1] == ""
    print(f"[ok] 광역 표현 {len(cases)}건 + 대체 해석 안내")


def test_find_dong() -> None:
    """동 검색 — 접미사 보정(역삼동 → 역삼1동), 행정동코드 직접 입력, 모르는 동 거절."""
    import src.kma.dong_zone as dong_mod
    from src.kma.dong_zone import Dong

    fake = [
        Dong("1168064000", "서울특별시", "강남구", "역삼1동"),
        Dong("1168065000", "서울특별시", "강남구", "역삼2동"),
        Dong("5115061500", "강원특별자치도", "강릉시", "강남동"),
        Dong("4113565000", "경기도", "성남시분당구", "판교동"),
    ]
    orig_all, orig_cand = dong_mod._all_dongs, dong_mod._candidate_cities
    dong_mod._all_dongs = lambda: fake
    dong_mod._candidate_cities = lambda text: []
    try:
        assert [d.name for d in dong_mod.search_dong("역삼동", 2)] == ["역삼1동", "역삼2동"]
        assert dong_mod.search_dong("판교", 1)[0].name == "판교동"
        assert dong_mod.search_dong("없는동네", 1) == [], "모르는 동을 추측했습니다"
        assert dong_mod.search_dong("", 1) == []
        assert dong_mod.find_dong("1168064000")[0] == "1168064000"
        print("[ok] 동 검색 — 접미사 보정, 코드 직접 입력, 미지원 동 거절")
    finally:
        dong_mod._all_dongs, dong_mod._candidate_cities = orig_all, orig_cand


def test_greeting() -> None:
    """인사·잡담은 자기소개로, 감사는 짧게. 지역이 섞이면 날씨가 우선."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast

    calls: list = []

    def fake_scrape(now, start, span, region):
        calls.append(region.key)
        from src.kma.page import Scrape
        return Scrape(days={}, narratives=[])

    from src.common.cache import clear

    orig_scrape, orig_dong = forecast.scrape_range, answer_mod.search_dong
    forecast.scrape_range = fake_scrape
    answer_mod.search_dong = lambda q, limit=5: []
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        for greeting in ("안녕?", "하이", "너 누구야", "뭐해"):
            reply = build_reply(f"<@U1> {greeting}", now)
            # 첫 인사말은 날짜마다 바뀌어 뒤따르는 기능 안내로 확인
            assert "날씨 알리미" in reply, f"{greeting}: {reply[:40]}"
            assert "동네예보" in reply, f"{greeting}: {reply[:80]}"
        assert not calls, "인사인데 예보를 수집했습니다"

        for thanks in ("고마워!", "감사합니다", "수고했어"):
            reply = build_reply(f"<@U1> {thanks}", now)
            assert "천만에요" in reply, f"{thanks}: {reply[:40]}"

        assert "•" in build_reply("<@U1> 도움말", now), "도움말이 사용법을 안 보여줍니다"

        # 지역이 섞이면 날씨 — '부산' 은 동네예보로 빠져 구역명으로 확인
        build_reply("<@U1> 경남 안녕", now)
        assert calls == ["경남"], calls
        print("[ok] 인사 응답 — 자기소개/감사/도움말 구분, 지역 우선")
    finally:
        forecast.scrape_range, answer_mod.search_dong = orig_scrape, orig_dong
        clear()


def test_long_range_routing() -> None:
    """10일 너머 요청의 세 갈래: 1개월 전망 / 너무 먼 미래 / 정상 조회."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    from src.common.cache import clear
    from src.kma.page import Scrape

    calls: list = []

    def fake_scrape(now, start, span, region):
        calls.append(region.key)
        return Scrape(days={}, narratives=[])

    outlook_calls: list = []

    def fake_outlook(region_key="전국", now=None):
        outlook_calls.append(region_key)
        from src.kma.outlook import Outlook, WeekOutlook
        return Outlook(
            issued="2026년 9월 10일 11시", period="2026년 9월 21일 ~ 10월 18일",
            region=region_key,
            weeks=[WeekOutlook("09.21.~09.27.", "맑겠습니다.", "18.2~19.2",
                               (20, 40, 40), (50, 30, 20))],
            url="https://example.invalid",
        )

    orig = (forecast.scrape_range, answer_mod.search_dong, answer_mod.fetch_outlook, answer_mod.find_wide)
    forecast.scrape_range, answer_mod.search_dong = fake_scrape, lambda q, limit=5: []
    answer_mod.find_wide = lambda q: None               # 행정구역 목록을 받으러 가지 않게
    answer_mod.fetch_outlook = fake_outlook
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        for q in ("다음 달 날씨", "올해 겨울은 어때?", "올여름", "10월 날씨"):
            clear()
            reply = build_reply(f"<@U1> {q}", now)
            assert "1개월 전망" in reply, f"{q}: {reply[:50]}"
            assert "확률" in reply, f"{q}: 확률이라는 점이 안 드러남"
        assert not calls, "전망 요청인데 일별 예보를 수집했습니다"
        assert outlook_calls, "전망을 조회하지 않았습니다"

        clear()
        outlook_calls.clear()
        build_reply("<@U1> 다음 달 부산", now)
        assert outlook_calls == ["경남"], outlook_calls

        for q in ("내년 봄", "3개월 전망"):
            clear()
            assert "예보하지 않습니다" in build_reply(f"<@U1> {q}", now)

        # 과거는 계절 말이 있어도 전망으로 새지 않음
        clear()
        outlook_calls.clear()
        for q in ("지난 해 여름은 어땠어?", "작년 여름", "어제 서울", "지난주 부산"):
            reply = build_reply(f"<@U1> {q}", now)
            assert "지난 날씨는" in reply, f"{q}: {reply[:50]}"
        assert not outlook_calls, "과거 질문인데 전망을 조회했습니다"

        clear()
        calls.clear()
        build_reply("<@U1> 다음 주 부산", now)
        assert calls == ["경남"], calls
        print("[ok] 장기 요청 분기 — 1개월 전망 / 먼 미래 거절 / 주간 정상")
    finally:
        forecast.scrape_range, answer_mod.search_dong, answer_mod.fetch_outlook, answer_mod.find_wide = orig
        clear()


def test_topic_advice() -> None:
    """활동·복장 질문에 맞춘 조언. 지역·날짜와 함께 와도 해석함."""
    from types import SimpleNamespace

    from src.advice.topics import detect_topic, topic_advice
    from src.kma.regions import extract_region

    assert detect_topic("내일 뭐 입지?") == "옷차림"
    assert detect_topic("주말 무등산 등산 괜찮아?") == "야외"
    assert detect_topic("빨래 널어도 될까") == "빨래"
    assert detect_topic("부산 날씨") is None, "평범한 조회를 조언으로 오해했습니다"

    # '무등산' 의 '등산' 을 활동어로 지우지 않음
    assert extract_region("주말 무등산 등산 괜찮아?")[0] is None
    assert extract_region("광주 등산 갈만해?")[0].key == "전남"
    assert extract_region("부산 뭐 입지")[0].key == "경남"

    def day(d, lo, hi, sky=None, pop=None):
        return SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo,
                               tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)

    base = dt.date(2026, 9, 14)
    rainy = [day(base, 18, 24, "흐리고 비", 80), day(base + dt.timedelta(days=1), 17, 25, "맑음", 10)]
    assert "우산" in " ".join(t.text for t in topic_advice("우산", rainy))
    outdoor = " ".join(t.text for t in topic_advice("야외", rainy))
    assert "09/14" in outdoor and "09/15" in outdoor, outdoor
    assert topic_advice("야외", []) == []
    print("[ok] 활동별 조언 — 의도 인식, 문장에서 지역 추출, 근거 없으면 침묵")


def _quiet_season_notes() -> tuple:
    """날씨 답 끝의 단풍·첫눈 한 줄이 기상청을 부르지 않게 — 기간 없이 답마다 자료를 보므로 늘 바꿔 둠.

    돌려줄 원래 함수(단풍, 첫눈)를 반환함. 단풍은 철 밖, 첫눈은 관측도 눈 예보도 없는 자료."""
    import src.season.foliage.data as foliage_mod
    from src.season.snow import data as snow

    orig = (foliage_mod.fetch_snapshot, snow.fetch_status)
    foliage_mod.fetch_snapshot = lambda today, **k: fake_snapshot(in_service=False, outlook=False)
    snow.fetch_status = lambda today, **_: snow.Status(snow.season_year(today))
    return orig


def _restore_season_notes(orig: tuple) -> None:
    import src.season.foliage.data as foliage_mod
    from src.season.snow import data as snow

    foliage_mod.fetch_snapshot, snow.fetch_status = orig


def test_cache_shared_across_spans() -> None:
    """지역 캐시 하나를 «이번 주»·«다음 주»·«기본» 이 나눠 써도 날이 빠지지 않음."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    from src.common.cache import clear
    from src.kma.page import Narrative, Scrape, ScrapedDay

    base = dt.date(2026, 9, 12)
    full = {base + dt.timedelta(days=i): ScrapedDay(
        date=base + dt.timedelta(days=i), tmin_lo=15.0, tmin_hi=20.0,
        tmax_lo=25.0, tmax_hi=28.0) for i in range(10)}

    def fake_scrape(now, start, span, region):
        window = {start + dt.timedelta(days=i) for i in range(span)}
        return Scrape(days={d: v for d, v in full.items() if d in window},
                      narratives=[Narrative("통보문", "", None, [])])

    orig = (forecast.scrape_range, *_quiet_season_notes())
    forecast.scrape_range = fake_scrape
    try:
        now = dt.datetime(2026, 9, 12, 9, 0, tzinfo=KST)   # 토요일
        clear()
        # «다음 주» 로 캐시를 채운 뒤 «기본(오늘부터 7일)» 을 물음
        answer_mod.build_reply("<@U123> 경남 다음주", now)
        reply = answer_mod.build_reply("<@U123> 경남 날씨", now)
    finally:
        forecast.scrape_range = orig[0]
        _restore_season_notes(orig[1:])
        clear()

    for day in ("09/12", "09/13", "09/18"):
        assert day in reply, (day, reply)
    print("[ok] 캐시 공유 — 기간을 바꿔 물어도 날이 빠지지 않는다")


def test_city_uses_dong_forecast() -> None:
    """'부산' 은 구역이 아니라 부산광역시 값으로 답함 — 기간이 닿는 한."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    from src.common.cache import clear
    from src.kma.page import Scrape

    calls: list = []

    def fake_scrape(now, start, span, region):
        calls.append(region.key)
        return Scrape(days={}, narratives=[])

    dong_calls: list = []

    def fake_dong_reply(zone, name, days=4, start=None, **_):
        dong_calls.append((name, days, start))
        return f"*{name}* 동네예보"

    orig = (forecast.scrape_range, answer_mod._dong_reply, answer_mod.find_wide)
    forecast.scrape_range = fake_scrape
    answer_mod._dong_reply = fake_dong_reply
    answer_mod.find_wide = lambda q: ("2600000000", "부산광역시") if "부산" in q else None
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)   # 월요일
    try:
        clear()
        answer_mod.build_reply("<@U1> 부산 날씨", now)
        assert dong_calls and not calls, (dong_calls, calls)

        # 주 단위는 광역 — 동네예보(5일)로 잘라 주지 않음
        dong_calls.clear()
        clear()
        answer_mod.build_reply("<@U1> 부산 이번주", now)
        assert calls and not dong_calls, (dong_calls, calls)

        dong_calls.clear()
        calls.clear()
        clear()
        answer_mod.build_reply("<@U1> 부산 다음주", now)
        assert calls and not dong_calls, (dong_calls, calls)
    finally:
        forecast.scrape_range, answer_mod._dong_reply, answer_mod.find_wide = orig
        clear()
    print("[ok] 시도 조회 — 가까운 날은 시 단위, 주 단위는 광역")


def test_partial_week_is_declared() -> None:
    """예보가 기간을 못 채우면 머리글이 실제 범위를 말하고, 왜 짧은지 밝힘."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    import src.season.foliage.data as foliage_mod
    from src.common.cache import clear
    from src.kma.page import Narrative, Scrape, ScrapedDay

    # 자료는 오늘부터 열흘 — 월요일에 «다음 주» 를 물으면 사흘만 걸침
    today = dt.date(2026, 9, 14)
    horizon = {today + dt.timedelta(days=i) for i in range(10)}

    def fake_scrape(now, start, span, region):
        days = {d: ScrapedDay(d, 15.0, 20.0, 24.0, 29.0, "맑음", 20, "중기예보")
                for i in range(span) if (d := start + dt.timedelta(days=i)) in horizon}
        return Scrape(days=days, narratives=[Narrative("중기예보", "", None, [])])

    orig = (forecast.scrape_range, answer_mod.find_wide, *_quiet_season_notes())
    forecast.scrape_range = fake_scrape
    answer_mod.find_wide = lambda q: None
    foliage_mod.fetch_snapshot = lambda today, **k: fake_snapshot(outlook=False)   # 단풍철 — 기상청을 부르지 않게
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        clear()
        reply = answer_mod.build_reply("<@U1> 다음주 날씨", now)
    finally:
        forecast.scrape_range, answer_mod.find_wide = orig[:2]
        _restore_season_notes(orig[2:])
        clear()

    assert "09/23" in reply.split("\n")[0], reply.split("\n")[0]
    assert "09/27" not in reply.split("\n")[0], reply.split("\n")[0]
    assert "09/24(목) 이후는 아직 예보가 작성되지 않았습니다" in reply, reply
    assert len([ln for ln in reply.split("\n") if ln.startswith("•")]) == 3, reply
    print("[ok] 기간을 못 채우면 머리글과 안내로 밝힌다")


def test_explicit_date() -> None:
    """«9월 18일»·«9/18(금)» 처럼 콕 집은 날짜를 읽음."""
    from src.mention.parse import _explicit_date

    today = dt.date(2026, 9, 12)
    assert _explicit_date("9월 18일 부산 날씨", today) == dt.date(2026, 9, 18)
    assert _explicit_date("18일 날씨", today) == dt.date(2026, 9, 18)
    assert _explicit_date("9/18 날씨", today) == dt.date(2026, 9, 18)
    # 월을 안 적으면 가까운 쪽 — 월말의 "2일" 은 다음 달
    assert _explicit_date("2일 날씨", dt.date(2026, 9, 28)) == dt.date(2026, 10, 2)
    assert _explicit_date("1월 5일", dt.date(2026, 12, 20)) == dt.date(2027, 1, 5)
    assert _explicit_date("7일간 날씨", today) is None
    assert _explicit_date("내일 날씨", today) is None
    # 봇 출력 «09/16(수)» 를 복사해 물어도 같은 날로 읽고 요일을 남기지 않음
    from src.mention.parse import EXPLICIT_DATE_RE
    for q in ("9/18(금)", "9월 18일(금)", "18일(금)", "9/18 (금)",
              "9월18일(금요일)", "09/18（금）"):
        assert _explicit_date(q, today) == _explicit_date("9/18", today), q
        assert not EXPLICIT_DATE_RE.sub(" ", q).strip(), q

    assert _explicit_date("금요일 날씨", today) is None
    assert _explicit_date("(금) 날씨", today) is None
    print("[ok] 명시 날짜 해석 — 월 생략·해 넘김·기간 표현·요일 표기 구분")


def test_phrase_rotation() -> None:
    """같은 조건이라도 날짜가 다르면 문구가 달라지고, 같은 날은 늘 같음."""
    import math

    import src.advice.phrases as phrases
    from src.advice.phrases import SPREAD_LINES
    from src.advice.rules import _pick, _pick_pair

    facts = SPREAD_LINES[0]
    base = dt.date(2026, 9, 13)
    got = {_pick(facts, base + dt.timedelta(days=i)) for i in range(len(facts))}
    assert len(got) == len(facts), got

    tables = {n: v for n, v in vars(phrases).items()
              if n.endswith("_LINES") and isinstance(v, tuple)}
    assert len(tables) >= 12, sorted(tables)
    mixed = {n: v for n, v in tables.items() if isinstance(v[0], tuple)}
    for name, table in tables.items():
        for lines in table if name in mixed else (table,):
            assert lines, name
            assert len(set(lines)) == len(lines), name
            rotated = {_pick(lines, base + dt.timedelta(days=i)) for i in range(len(lines))}
            assert len(rotated) == len(lines), (name, rotated)
    # 한 바퀴 돌면 제자리 — 날짜에만 달림
    later = base + dt.timedelta(days=len(facts))
    assert _pick(facts, later) == _pick(facts, base)
    assert _pick((), base) == ""

    by_region = {_pick(facts, base, r) for r in ("서울", "부산", "대구")}
    assert len(by_region) > 1, by_region
    assert _pick(facts, base, "서울") == _pick(facts, base, "서울")
    assert _pick(facts, base) == facts[base.toordinal() % len(facts)]

    # 사실과 권하는 말은 따로 돌아 모든 짝이 나옴 — 같은 줄끼리 묶이지 않음
    assert {"SPREAD_LINES", "COLD_LINES", "RAIN_LINES", "FOG_LINES"} <= set(mixed), sorted(mixed)
    for name, (fs, acts) in mixed.items():
        span = math.lcm(len(fs), len(acts)) * (len(acts) + 1)
        pairs = [_pick_pair((fs, acts), base + dt.timedelta(days=i), "서울") for i in range(span)]
        assert len(set(pairs)) == len(fs) * len(acts), (name, len(set(pairs)))
        assert all(a[1] != b[1] for a, b in zip(pairs, pairs[1:])), name   # 권하는 말도 날마다 바뀜
    assert _pick_pair(SPREAD_LINES, base, "서울")[0] == _pick(facts, base, "서울")
    assert _pick_pair(((), ()), base) is None
    print("[ok] 문구 회전 — 날짜·지역별로 다르고 같은 조건은 고정, 사실과 권하는 말은 섞임")


def test_advice() -> None:
    """수치에서 조언을 뽑되, 근거가 없으면 말하지 않음."""
    from types import SimpleNamespace

    from src.advice.rules import build_advice

    def day(d, lo, hi, sky=None, pop=None):
        return SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo,
                               tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)

    base = dt.date(2026, 9, 14)
    # 일교차 15도 + 폭염 + 비
    tips = build_advice([
        day(base, 18, 33), day(base + dt.timedelta(days=1), 20, 26, "비", 80),
    ])
    joined = " ".join(t.text for t in tips)
    # 문구는 날짜마다 바뀌어 이모지로 확인
    emojis = {t.emoji for t in tips}
    assert ":thermometer:" in emojis, joined
    assert ":sun_with_face:" in emojis, joined
    assert ":umbrella_with_rain_drops:" in emojis, joined

    # 한파는 폭염보다 우선 — 둘이 같이 나오지 않음
    cold_tips = build_advice([day(base, 2, 10)])
    assert any(t.emoji == ":cold_face:" for t in cold_tips), cold_tips
    assert "온열질환" not in " ".join(t.text for t in cold_tips)
    import src.advice.rules as advice_mod
    orig_cold = advice_mod.COLD_LINES
    advice_mod.COLD_LINES = ((), ())
    try:
        assert not any(t.emoji == ":cold_face:" for t in build_advice([day(base, 2, 10)]))
    finally:
        advice_mod.COLD_LINES = orig_cold

    typhoon = " ".join(t.text for t in build_advice(
        [day(base, 20, 26)], ["○ (특이사항) 제13호 태풍 북상"]))
    assert "태풍" in typhoon, typhoon

    assert build_advice([]) == []
    assert build_advice([SimpleNamespace(date=base, tmin_lo=None, tmin_hi=None,
                                         tmax_lo=None, tmax_hi=None, sky=None, pop=None)]) == []
    print("[ok] 생활 조언 — 일교차·폭염·한파·비·특이사항, 근거 없으면 침묵")


def test_resolve_date() -> None:
    """'14일' 같은 표기를 기준일 근처 실제 날짜로 되돌림 (월 넘어감 포함)."""
    assert _resolve_date(14, dt.date(2026, 9, 10)) == dt.date(2026, 9, 14)
    assert _resolve_date(2, dt.date(2026, 9, 30)) == dt.date(2026, 10, 2)
    assert _resolve_date(28, dt.date(2026, 3, 2)) == dt.date(2026, 2, 28)
    assert _resolve_date(32, dt.date(2026, 2, 10)) is None
    print("[ok] 날짜 해석 (월말·월초 넘어감)")


def test_forecast_validation() -> None:
    """스크랩 값이 이상하면 바로잡거나 버림."""
    import src.kma.scrape as scrape_mod
    from src.kma.page import Scrape
    from src.weekly.forecast import ForecastError, build_week

    class Cfg:
        area_label = "전국"

    now = dt.datetime(2026, 9, 7, 8, 0, tzinfo=KST)

    def fake_scrape(_now, week_start, _region=None):
        days = {}
        # 정상 5일 + 범위 뒤집힘 1일 + 물리적으로 불가능한 값 1일
        for i in range(5):
            d = week_start + dt.timedelta(days=i)
            days[d] = ScrapedDay(d, 18, 24, 25, 31, "구름많음", 30, "통보문")
        d5 = week_start + dt.timedelta(days=5)
        days[d5] = ScrapedDay(d5, 24, 18, 31, 25, "흐림", 40, "중기예보")
        d6 = week_start + dt.timedelta(days=6)
        days[d6] = ScrapedDay(d6, 999, 24, 25, 31, "맑음", 500, "중기예보")
        return Scrape(days=days, narratives=[])

    scrape_mod_orig = scrape_mod.scrape_week
    import src.weekly.forecast as fc
    fc.scrape_week = fake_scrape
    try:
        week = build_week(Cfg(), now)
        assert len(week.days) == 7
        assert (week.days[5].tmin_lo, week.days[5].tmin_hi) == (18.0, 24.0), "뒤집힌 범위 미보정"
        assert week.days[6].tmin_lo is None, "범위 밖 값을 못 버렸습니다"
        assert week.days[6].pop is None, "강수확률 범위 밖 값을 못 버렸습니다"
        assert any("뒤집" in w for w in week.warnings)
        print(f"[ok] 예보 검증 — 경고 {len(week.warnings)}건: {week.warnings[0]}")

        fc.scrape_week = lambda _n, ws, _r=None: Scrape(
            days={ws: ScrapedDay(ws, 18, 24, 25, 31, "맑음", 10, "통보문")}, narratives=[]
        )
        try:
            build_week(Cfg(), now)
        except ForecastError as exc:
            print(f"[ok] 자료 부족 시 게시 포기: {str(exc)[:60]}…")
        else:
            raise AssertionError("자료가 부족한데도 예외를 던지지 않았습니다")
    finally:
        fc.scrape_week = scrape_mod_orig


def test_mention_parsing() -> None:
    """멘션 문장에서 지역과 수집 범위를 읽고, 모르는 지명은 수집하지 않음."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    from src.common.cache import clear
    from src.kma.page import Scrape

    calls: list[tuple] = []

    def fake_scrape(now, start, span, region):
        calls.append((region.key, start, span))
        return Scrape(days={}, narratives=[])

    orig = forecast.scrape_range
    forecast.scrape_range = fake_scrape
    try:
        now = dt.datetime(2026, 9, 12, 9, 0, tzinfo=KST)   # 토요일
        # 구역명으로 — 시도 이름은 동네예보로 빠짐(find_wide)
        for text in ("<@U123> 경남 날씨 알려줘", "<@U123> 전북 다음주", "<@U123> 강원 이번주"):
            clear()
            build_reply(text, now)

        # 수집은 늘 «오늘부터 열흘» — 지역당 캐시 한 항목을 나눠 씀
        assert [c[0] for c in calls] == ["경남", "전북", "강원"], calls
        assert all(c[1] == dt.date(2026, 9, 12) and c[2] == 10 for c in calls), calls

        # «요즘» 만 오면 전국 — 조사가 붙어도 지역 이름으로 읽지 않음
        for text in ("<@U123> 요즘", "<@U123> 요즘 날씨 어때?", "<@U123> 요즘은 날씨 어때", "<@U123> 요즘엔 어때"):
            calls.clear()
            clear()
            reply = build_reply(text, now)
            assert [c[0] for c in calls] == ["전국"], (text, calls, reply)

        import src.kma.dong_zone as dong_mod
        orig = dong_mod.search_dong
        answer_mod.search_dong = lambda q, limit=5: []
        try:
            before = len(calls)
            reply = build_reply("<@U123> 존재하지않는지명", now)
            assert len(calls) == before, "모르는 지역인데 수집을 시도했습니다"
            assert "아는 지역이 아닙니다" in reply
        finally:
            answer_mod.search_dong = orig
        print("[ok] 멘션 파싱 — 기본 '오늘부터 7일', 이번주/다음주 인식, '요즘' 은 전국, 미지원 지역 거절")
    finally:
        forecast.scrape_range = orig
        clear()


def test_card_render() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    week = fake_week()

    png = render_png(week, scale=2)
    assert png.startswith(PNG_MAGIC), "PNG가 아님"
    (IMG / "card.png").write_bytes(png)
    print(f"[ok] 카드 렌더링 {len(png):,}B -> {IMG / 'card.png'}")

    bare = WeekForecast(area=week.area, week_start=WEEK_START, days=week.days)
    png2 = render_png(bare, scale=2)
    assert png2.startswith(PNG_MAGIC)
    (IMG / "card-bare.png").write_bytes(png2)
    print(f"[ok] 서술 없는 폴백 카드 {len(png2):,}B -> {IMG / 'card-bare.png'}")


def test_message_template() -> None:
    text = fallback(fake_week()).body
    assert "**" not in text, "슬랙 mrkdwn 에 마크다운 볼드가 섞였습니다"
    print("[ok] 본문 템플릿 폴백")
    print("-" * 60)
    print(text)
    print("-" * 60)


def test_weekly_body() -> None:
    """규칙 기반 본문 — 1문단은 문장으로 맺고, 2문단은 같은 날 조언을 한 문장으로 엮음."""
    import re
    from types import SimpleNamespace

    from src.advice.phrases import SPREAD_LINES
    from src.advice.rules import build_advice
    from src.weekly.body import quote_josa, theme_paragraph

    first, second = fallback(fake_week()).body.split("\n\n")
    assert first.endswith("습니다."), first
    assert '유의*"라고 전하고' in first, first                # «유의이라» 가 아님

    # 닫는 별표 뒤에 한글을 붙이지 않음 — 슬랙이 굵게로 못 읽음
    for part in (first, second):
        for m in re.finditer(r"\*[^*\n]+\*", part):
            assert not re.match(r"[가-힣]", part[m.end():m.end() + 1]), part

    assert quote_josa("기온차 큼") == "이라고"
    assert quote_josa("높은 물결 유의") == "라고"
    assert quote_josa("기온차 큼(동해안 제외)") == "라고"     # 괄호 꼬리는 건너뜀

    def day(d, lo, hi, sky=None, pop=None):
        return SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo,
                               tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)

    wed = dt.date(2026, 10, 7)
    # 같은 날 일교차 14도 + 아침 4도
    text = theme_paragraph(build_advice([day(wed - dt.timedelta(days=1), 12, 22), day(wed, 4, 18)]))
    assert text.count("10/7") == 1, text
    assert text.startswith("*10/7(수)에는* 아침 최저 4도까지 내려가고 "
                           "일교차가 14도 안팎으로 벌어지겠습니다. "), text
    assert text.endswith(":cold_face:") and text.count(":") == 2, text

    # 날이 달라도 기온 조언은 한 문장 — 날짜 순으로, 권하는 말은 하나
    text = theme_paragraph(build_advice([day(wed + dt.timedelta(days=1), 6, 22), day(wed, 2, 12)]))
    assert text.startswith("*10/7(수)에는* 아침 최저 2도까지 내려가고, "
                           "*10/8(목)에는* 일교차가 16도 안팎으로 벌어지겠습니다. "), text
    assert not any(act in text for act in SPREAD_LINES[1]), text
    assert text.endswith(":cold_face:"), text

    # 어간에 «고»·«겠습니다» 를 붙임 — «올라겠습니다» 가 아님
    text = theme_paragraph(build_advice([day(wed, 20, 34)]))
    assert "34도까지 오르고 일교차가" in text, text
    assert theme_paragraph(build_advice([day(wed, 24, 34)])).startswith(
        "*10/7(수)에는* 낮 최고 34도까지 오르겠습니다. ")

    text = theme_paragraph(build_advice([day(wed, 4, 18, "비", 80)]))
    assert text.count("10/7") == 1 and "같은 날은 비가 오겠습니다." in text, text

    text = theme_paragraph(build_advice([day(wed, 4, 18)], ["○ 너울 유의", "○ 풍랑 유의"]))
    assert "너울" in text and "풍랑" not in text and "10/7" in text, text

    assert theme_paragraph([]).startswith("이번 주도")
    print("[ok] 주간 본문 — 문장으로 맺고, 같은 날 조언은 한 문장으로")


def test_writer_backend() -> None:
    """WRITER 고르기 — 기본은 규칙 기반, 모르는 값도 규칙 기반, 패키지가 없어도 게시는 됨."""
    import src.weekly.writer as writer

    calls: list[str] = []

    def no_package(*_a, **_k):
        calls.append("gemini")
        raise ImportError("No module named 'google'")

    saved = {k: os.environ.pop(k, None) for k in ("WRITER", "GEMINI_API_KEY")}
    orig = writer._write_gemini
    writer._write_gemini = no_package
    try:
        base = writer.fallback(fake_week()).body
        assert writer.write(fake_week()).body == base and not calls
        os.environ["WRITER"], os.environ["GEMINI_API_KEY"] = "rules", "x"
        assert writer.write(fake_week()).body == base and not calls
        os.environ["WRITER"] = "gemini"
        assert writer.write(fake_week()).body == base and calls == ["gemini"]
    finally:
        writer._write_gemini = orig
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    print("[ok] WRITER — 기본 none, 모르는 값·패키지 없음은 규칙 기반")


def test_mention_delivery() -> None:
    """멘션 답 보내기 — 바로 답, 느리면 로딩 메시지를 결과로 교체, 지도는 글과 함께, 실패하면 글로."""
    import time

    import src.mention.bot as bot
    from src.mention.reply import Reply

    class FakeClient:
        def __init__(self, upload_fails=False):
            self.calls, self.upload_fails = [], upload_fails

        def chat_postMessage(self, **kw):
            self.calls.append(("post", kw["text"]))
            return {"ts": "L1"}

        def chat_update(self, **kw):
            self.calls.append(("update", kw["ts"], kw["text"]))

        def chat_delete(self, **kw):
            self.calls.append(("delete", kw["ts"]))

        def files_upload_v2(self, **kw):
            if self.upload_fails:
                raise TimeoutError("업로드 시간 초과")
            self.calls.append(("upload", kw["initial_comment"]))
            self.calls.append(("file", kw["filename"].split("-")[0], kw["title"]))

    def run(reply, *, slow=False, upload_fails=False):
        client, said = FakeClient(upload_fails), []

        def fake_answer(text):
            if slow:
                time.sleep(0.15)
            if isinstance(reply, Exception):
                raise reply
            return reply

        bot.answer = fake_answer
        bot.handle_mention({"text": "<@U1> 부산", "channel": "C1", "ts": "1.0", "user": "U2"},
                           lambda **kw: said.append(kw["text"]), client, ":loading:")
        return client.calls, said

    orig = (bot.answer, bot.SLOW_REPLY_SEC)
    bot.SLOW_REPLY_SEC = 0.05
    try:
        assert run(Reply("맑음")) == ([], ["맑음"])
        calls, said = run(Reply("맑음"), slow=True)
        assert calls == [("post", ":loading: 기상청 자료를 받아오는 중이에요…"), ("update", "L1", "맑음")] and not said
        calls, said = run(Reply("단풍", image=b"png"), slow=True)
        assert ("upload", "단풍") in calls and ("delete", "L1") in calls and not said, calls
        assert run(Reply("단풍", image=b"png"), upload_fails=True) == ([], ["단풍"])
        calls, _ = run(Reply("첫눈", image=b"png", slug="snow", title="첫눈 지도"))
        assert ("file", "snow", "첫눈 지도") in calls, calls
        calls, said = run(RuntimeError("파서 고장"))
        assert said == ["예보를 정리하는 중에 문제가 생겼습니다. 잠시 뒤 다시 불러 주세요."], said
    finally:
        bot.answer, bot.SLOW_REPLY_SEC = orig
    print("[ok] 멘션 답 보내기 — 로딩 교체 · 지도 · 실패 시 글로")


def test_chart_download() -> None:
    import requests

    chart = fetch_latest_chart("surf")
    assert chart.png.startswith(PNG_MAGIC) and len(chart.png) > 100_000
    IMG.mkdir(parents=True, exist_ok=True)
    (IMG / chart.filename).write_bytes(chart.png)
    print(f"[ok] 일기도 {chart.url} ({len(chart.png):,}B)")

    bogus = requests.get(
        "https://www.weather.go.kr/w/repositary/image/cht/img/surf_2000010103.png", timeout=20
    )
    assert bogus.status_code == 200 and not bogus.content.startswith(PNG_MAGIC)
    print("[ok] 없는 일기도는 200+HTML 로 응답 -> 매직바이트 검증 필요 확인")


def test_footer_and_region_variation() -> None:
    """동네예보 꼬리말은 자료 끝까지 보여 줄 때만 붙고, 조언 문장은 지역마다 갈림."""
    from types import SimpleNamespace

    import src.mention.weather.dong as dong

    def fake_fetch(zone, name, days_n):
        base = dt.date(2026, 9, 16)
        rows = [(base + dt.timedelta(days=i), 16.0, 29.0, "맑음", 10)
                for i in range(days_n)]
        return SimpleNamespace(
            name=name, issued="2026년 09월 15일 (화)요일 17:00",
            daily_summary=lambda: rows,
        )

    orig = dong.fetch_dong
    try:
        dong.fetch_dong = lambda z, n: fake_fetch(z, n, 1)
        one = dong._dong_reply("1100000000", "서울특별시", days=1)
        assert "더 먼 날이 필요" not in one, one
        assert "발표" in one, one

        dong.fetch_dong = lambda z, n: fake_fetch(z, n, dong.DONG_MAX_DAYS)
        full = dong._dong_reply("1100000000", "서울특별시", days=dong.DONG_MAX_DAYS)
        assert "더 먼 날이 필요" in full, full
        # 오전·낮 발표(4일치)도 자료 끝까지 보여 주면 광역 안내가 붙음
        dong.fetch_dong = lambda z, n: fake_fetch(z, n, 4)
        four = dong._dong_reply("1100000000", "서울특별시", days=dong.DONG_MAX_DAYS)
        assert "더 먼 날이 필요" in four, four
        part = dong._dong_reply("1100000000", "서울특별시", days=2)
        assert "더 먼 날이 필요" not in part, part

        # 오늘 줄은 남은 시간의 값 — «N시 이후» 를 붙이고 굵게(주 최저·최고)에서 뺌
        late = fake_fetch("", "서울특별시", 3)
        first = late.daily_summary()[0][0]
        late.points = ([SimpleNamespace(when=dt.datetime.combine(first, dt.time(h))) for h in (21, 22, 23)]
                       + [SimpleNamespace(when=dt.datetime.combine(first + dt.timedelta(days=1), dt.time(h)))
                          for h in range(24)])
        rows = late.daily_summary()
        rows[0] = (first, 10.0, 12.0, "맑음", 0)             # 밤 몇 시간 값이 주 최저처럼 보임
        late.daily_summary = lambda: rows
        dong.fetch_dong = lambda z, n: late
        tonight = dong._dong_reply("1100000000", "서울특별시", days=3)
        assert f"`{dong.day_label(first)}` 21시 이후 10~12℃" in tonight, tonight
        assert "시 이후" not in tonight.split("\n")[2], tonight
        # 오늘 줄의 밤 기온은 조언에 쓰지 않음
        rows[0] = (first, 2.0, 4.0, "맑음", 0)
        cold_night = dong._dong_reply("1100000000", "서울특별시", days=3)
        assert ":cold_face:" not in cold_night and "아침 최저" not in cold_night, cold_night

        dong.fetch_dong = lambda z, n: fake_fetch(z, n, 4)
        mountain = dong._quiet_dong_reply("5121060000", "설악산 아래 속초시 대포동", 4,
                                          dt.date(2026, 9, 16))
        assert mountain and "더 먼 날이 필요" not in mountain, mountain

        dong.fetch_dong = lambda z, n: fake_fetch(z, n, 3)
        seoul = dong._dong_reply("1100000000", "서울특별시", days=3)
        busan = dong._dong_reply("2600000000", "부산광역시", days=3)
        def tip(r):
            return [ln for ln in r.split("\n") if ln.startswith(":")]
        assert tip(seoul) and tip(busan), (seoul, busan)
        assert tip(seoul) != tip(busan), (tip(seoul), tip(busan))
    finally:
        dong.fetch_dong = orig
    print("[ok] 꼬리말은 필요할 때만, 조언은 지역마다 다르게")


# --- 단풍 -------------------------------------------------------------------

def fake_snapshot(stages=None, first=None, peak=None, *, in_service=True, outlook=True):
    from src.season.foliage.data import Outlook, Snapshot, Status
    from src.season.foliage.mountains import MOUNTAINS

    d = dt.date
    status = Status(
        stages={m.name: 0 for m in MOUNTAINS} | (stages or {}),
        first=first or {}, peak=peak or {}, in_service=in_service,
    )
    o = Outlook(
        first={"설악산": d(2026, 10, 3), "오대산": d(2026, 10, 7), "치악산": d(2026, 10, 10),
               "북한산": d(2026, 10, 23), "내장산": d(2026, 11, 5), "한라산": d(2026, 10, 31)},
        peak={"설악산": d(2026, 10, 25), "오대산": d(2026, 10, 16), "치악산": d(2026, 10, 31),
              "북한산": d(2026, 11, 4), "내장산": d(2026, 11, 11), "한라산": d(2026, 11, 13)},
        published=d(2026, 9, 4), url="https://example.invalid",
    ) if outlook else None
    return Snapshot(status=status, outlook=o)


def test_foliage_season() -> None:
    """기간은 자료가 정함 — 기상청 관측 중이거나, 관측 전이라도 올해 예상일이 남았을 때만."""
    d = dt.date
    peaked = fake_snapshot({"두륜산": 2}, peak={"두륜산": d(2026, 11, 9)})
    assert peaked.showing(d(2026, 11, 16)) and peaked.showing(d(2026, 12, 7))     # 기상청이 관측을 이어 가는 동안
    before = fake_snapshot(in_service=False)                                      # 웨더아이 예상만 나온 9월 초
    assert before.showing(d(2026, 9, 7)) and before.showing(d(2026, 10, 3))       # 첫 예상일(설악산 첫단풍 10/3)까지
    # 첫 예상일이 지났는데 서비스가 꺼져 있으면 접은 것 — 한라산 절정 예상(11/13)이 남아도 «아직 시작 안 함» 이 아님
    assert not before.showing(d(2026, 10, 4)) and not before.showing(d(2026, 11, 10))
    assert not fake_snapshot(in_service=False, outlook=False).showing(d(2026, 6, 1))
    print("[ok] 단풍 기간 — 기상청 관측 중이거나 남은 예상일이 있을 때만 (고정 기간 없음)")


def test_foliage_parse() -> None:
    """기상청 JSONP 와 웨더아이 표. 지난 시즌 값·잘못 읽은 표는 버림."""
    import json

    from src.season.foliage.data import FoliageError, parse_outlook_text, parse_status
    from src.season.sources import shot_date

    def jsonp(service: bool, statuses: dict[str, str], flower: dict) -> str:
        places = [{"obsPlace": n, "status": s, "sts": str(["단풍전", "첫단풍", "절정"].index(s) + 1)}
                  for n, s in statuses.items()]
        return "\r\n\r\napplyMapleData(" + json.dumps(
            {"places": places, "isService": service, "flower": flower}, ensure_ascii=False) + ")"

    stages, live, flower = parse_status(
        jsonp(True, {"설악산": "첫단풍", "오대산": "단풍전", "한라산": "절정"},
              {"obsPlace": "설악산", "cfShotDate": "2026-09-28"}), 2026)
    assert live and stages == {"설악산": 1, "오대산": 0, "한라산": 2}, stages
    assert shot_date(flower["cfShotDate"], 2026) == dt.date(2026, 9, 28)
    # 서비스 기간 밖이면 지난 시즌 값이라 버림
    stages, live, _ = parse_status(jsonp(False, {"설악산": "절정"}, {}), 2026)
    assert not live and stages == {"설악산": 0}, stages
    assert shot_date("2025-10-20", 2026) is None, "지난해 촬영일을 올해 것으로 읽었습니다"
    try:
        parse_status("<html>점검 중</html>", 2026)
        raise AssertionError("JSONP 가 아닌데 통과했습니다")
    except FoliageError:
        pass

    # 표기는 '10/3'(2025~)·'09.27'(~2024). 금강산은 기상청 목록에 없어 빠짐
    rows = [
        "금강산    1,638   10/1      -              -      10/23     -        -",
        "설악산    1,708   10/3      5              1      10/25     8        1",
        "오대산    1,565   10.07     6              0      10.16     1        0",
    ] + [f"{n}    1,000   10/2{i}     1   0    11/{i + 1}    1   0"
         for i, n in enumerate(["북한산", "치악산", "월악산", "속리산", "계룡산", "팔공산",
                                "가야산", "내장산", "지리산"])]
    first, peak = parse_outlook_text("\n".join(rows), 2026)
    assert "금강산" not in first and len(first) == 11
    assert first["설악산"] == dt.date(2026, 10, 3) and peak["오대산"] == dt.date(2026, 10, 16)
    for bad, why in (
        (rows[:5], "산을 너무 적게 읽었는데 통과했습니다"),
        ([rows[1].replace("10/25", "9/25")] + rows[2:], "절정이 첫단풍보다 이른데 통과했습니다"),
    ):
        try:
            parse_outlook_text("\n".join(bad), 2026)
            raise AssertionError(why)
        except FoliageError:
            pass
    print("[ok] 단풍 자료 읽기 — 지난 시즌·형식 변경은 버림")


def test_mountain_lookup() -> None:
    from src.season.basemap import LAT0, LAT1, LON0, LON1
    from src.season.foliage.mountains import MOUNTAINS, find_mountain, unknown_mountain

    assert len(MOUNTAINS) == 21 and len({m.zone for m in MOUNTAINS}) == 21
    assert all(LON0 < m.lon < LON1 and LAT0 < m.lat < LAT1 for m in MOUNTAINS), "지도 밖 좌표"
    for q, want in (("설악산 단풍 어때", "설악산"), ("한라 단풍", "한라산"), ("노고단 단풍", "지리산"),
                    ("주말 내장산 단풍", "내장산"), ("단풍 어디까지", None), ("부산 근처 단풍", None)):
        m = find_mountain(q)
        assert (m.name if m else None) == want, (q, m)
    assert unknown_mountain("화악산 단풍은?") == "화악산"
    assert unknown_mountain("명지산은 단풍 들었어") == "명지산"
    for q in ("부산 근처 단풍", "등산 가는데 단풍", "설악산 단풍", "단풍 어느산이 좋아?",
              "가까운산 단풍", "근교산 추천"):
        assert unknown_mountain(q) is None, q
    # 산 이름이 든 행정구역(설악면 등)은 산이 아님
    for q in ("가평 설악면 날씨", "보은 속리산면은", "청송 주왕산면에서", "가평 설악면으로 가는데 날씨",
              "속리산면에서는 어때"):
        assert find_mountain(q) is None, q
    # 어미 '-면' 은 행정구역이 아님
    for q, name in (("설악산이면 어때", "설악산"), ("지리산가려면 뭐 입어", "지리산")):
        assert (m := find_mountain(q)) and m.name == name, q
    assert find_mountain("설악산에서 하룻밤").name == "설악산"
    # '산' 을 뗀 줄임말은 낱말일 때만 — 한라대·치악체육관은 산이 아님
    for q in ("내일 한라대 근처 날씨", "원주 치악체육관 날씨", "광주 무등경기장 날씨"):
        assert find_mountain(q) is None, q
    assert find_mountain("주말 설악 날씨").name == "설악산"

    from src.kma.regions import REGIONS
    from src.season.foliage.mountains import in_region, in_zone

    assert {k for m in MOUNTAINS for k in m.regions} <= {r.key for r in REGIONS}, "없는 구역 이름"
    assert all(m.regions for m in MOUNTAINS), "어느 구역에도 없는 산"
    assert [m.name for m in in_region("강원")] == ["설악산", "오대산", "치악산"]
    for code, want in (("1100000000", ["북한산"]), ("2700000000", ["팔공산"]), ("1230000000", ["무등산"]),
                       ("5000000000", ["한라산"]), ("2600000000", [])):
        assert [m.name for m in in_zone(code)] == want, (code, in_zone(code))
    print("[ok] 산 이름 — 별칭 · 목록 밖 산 · 산이 아닌 'X산' · 행정구역 · 구역별 산")


def test_foliage_routing() -> None:
    """단풍·꽃 질문의 갈래. 과거·1개월 전망으로 새지 않음."""
    from types import SimpleNamespace

    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    import src.mention.weather.dong as dong
    import src.season.foliage.data as foliage_mod
    import src.season.foliage.map as foliage_map

    snap = fake_snapshot({"설악산": 1}, first={"설악산": dt.date(2026, 9, 28)})
    dong_calls: list = []

    def fake_dong(zone, name):
        dong_calls.append((zone, name))
        rows = [(dt.date(2026, 10, 3) + dt.timedelta(days=i), 9.0, 23.0, "맑음", 10) for i in range(2)]
        return SimpleNamespace(name=name, issued="2026년 10월 01일 (목)요일 14:00",
                               daily_summary=lambda: rows)

    from src.common.cache import clear
    from src.kma.page import Scrape

    scraped: list = []
    renders: list = []

    def fake_render(s, start, span_label=""):
        renders.append(start)
        return b"PNG"

    def fake_scrape(now, start, span, region):
        scraped.append(region.key)
        return Scrape(days={}, narratives=[])

    orig = (foliage_mod.fetch_snapshot, dong.fetch_dong, foliage_map.render_png, forecast.scrape_range)
    foliage_mod.fetch_snapshot = lambda today, **k: snap
    dong.fetch_dong = fake_dong
    foliage_map.render_png = fake_render                 # Chromium 없이
    forecast.scrape_range = fake_scrape
    now = dt.datetime(2026, 10, 1, 15, 0, tzinfo=KST)
    clear()
    try:
        def ask(q, when=now):
            return answer_mod.answer(f"<@U1> {q}", when).text

        res = answer_mod.answer("<@U1> 단풍 어디까지 왔어", now)
        overview = res.text
        assert "단풍 현황" in overview and "*설악산* 첫단풍 9/28" in overview, overview
        assert "예상보다 5일 빠름" in overview, overview
        assert res.image == b"PNG", "전체 현황인데 지도가 없습니다"
        assert answer_mod.answer("<@U1> 설악산 단풍", now).image is None, "산 하나에는 글로만 답한다"
        answer_mod.answer("<@U1> 단풍 어때", now)
        assert len(renders) == 1, f"같은 현황인데 지도를 {len(renders)}번 그렸습니다"

        # '었나' 는 과거로, '가을' 은 1개월 전망으로 새지 않음
        seorak = ask("설악산 단풍 물들었나")
        assert "*설악산* 단풍" in seorak and "9/28 관측" in seorak, seorak
        assert "지난 날씨" not in seorak
        assert "1개월 전망" not in ask("올가을 단풍 언제 절정이야")
        assert "지난 날씨" not in ask("작년보다 단풍 늦어?")

        # 날짜·날씨를 함께 물으면 산 아래 마을 예보를 붙임
        weekend = ask("주말 내장산 단풍 어때")
        assert "11/5 예상" in weekend and "동네예보" in weekend, weekend
        assert dong_calls and dong_calls[-1][0] == "5218053500", dong_calls
        assert "산 아래 마을 예보" in weekend
        dong_calls.clear()
        assert "동네예보" not in ask("내장산 단풍 언제 절정이야") and not dong_calls

        assert "21곳에 없습니다" in ask("화악산 단풍은?")
        assert "21곳에 없습니다" not in ask("부산 근처 단풍")

        for when in (now, dt.datetime(2026, 4, 1, tzinfo=KST)):
            assert "꽃 개화 소식은 다루지 않습니다" in ask("벚꽃 피었어?", when)
        # 기간은 자료가 정함 — 기상청 관측 중이면 12월에도 답하고, 관측을 접었고 예상도 지났으면 철이 아님
        assert "단풍 현황" in ask("단풍 어때", dt.datetime(2026, 12, 1, tzinfo=KST))
        foliage_mod.fetch_snapshot = lambda today, **k: fake_snapshot(in_service=False)
        late = ask("단풍 어때", dt.datetime(2026, 12, 1, tzinfo=KST))
        assert "단풍 관측 기간이 아닙니다" in late and "단풍 현황" not in late, late
        early = ask("설악산 단풍", dt.datetime(2026, 9, 7, tzinfo=KST))          # 관측 전, 웨더아이 예상만
        assert "아직 시작되지 않았습니다" in early and "10/3 예상" in early, early
        foliage_mod.fetch_snapshot = lambda today, **k: snap

        assert "지난 날씨는" in ask("작년 여름")

        # 단풍·꽃 말이 섞인 날씨 질문은 날씨로 답함
        scraped.clear()
        weather = ask("단풍 구경 가는데 강원도 날씨 어때")
        assert scraped == ["강원"] and "단풍 현황" not in weather, (scraped, weather)
        assert "꽃 개화 소식" not in ask("꽃구경 가는데 내일 강원 날씨")
        assert "단풍 현황" in ask("강원도 단풍 어때")

        # 단풍 상태·날짜를 되묻는 말에는 날씨를 붙이지 않음
        dong_calls.clear()
        for q in ("설악산 단풍 지금 어때", "설악산 단풍 요즘 어때", "오대산 단풍 현재 상태",
                  "설악산 단풍 절정 10/25 맞아?"):
            assert "동네예보" not in ask(q), q
        assert not dong_calls, dong_calls
        dong.fetch_dong = lambda z, n: (_ for _ in ()).throw(dong.DongError("점검"))
        failed = ask("주말 설악산 단풍")
        assert "가져오지 못했습니다" in failed and "광역" not in failed, failed
        dong.fetch_dong = fake_dong
        # '다음 주 주말' 은 10/10 — 동네예보(5일) 밖이라 안내만
        next_weekend = ask("다음 주 주말 설악산 단풍")
        assert "10/03" not in next_weekend and "5일까지" in next_weekend, next_weekend

        # 촬영일이 아직 없으면 지난 단계의 예상일을 꺼내지 않음
        foliage_mod.fetch_snapshot = lambda today, **k: fake_snapshot({"설악산": 1})
        bare = ask("설악산 단풍")
        assert "*관측* (촬영일은" in bare and "예상이었지만" not in bare, bare
        assert ask("단풍 어디까지").count("*설악산* 첫단풍") == 1
    finally:
        (foliage_mod.fetch_snapshot, dong.fetch_dong, foliage_map.render_png,
         forecast.scrape_range) = orig
        clear()
    print("[ok] 단풍 멘션 — 현황 · 산별 · 산 날씨 · 목록 밖 산 · 꽃/기간 밖 거절")


def test_foliage_in_weather() -> None:
    """단풍 말 없이 물어도 — 산 이름이면 산 날씨와 그 산의 단풍, 지역 날씨면 그 지역 산의 한 줄."""
    from types import SimpleNamespace

    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    import src.mention.weather.dong as dong
    import src.season.foliage.data as foliage_mod
    from src.common.cache import clear
    from src.kma.page import Scrape, ScrapedDay
    from src.season.foliage.data import FoliageError
    from src.season.snow import data as snow

    now = dt.datetime(2026, 10, 1, 15, 0, tzinfo=KST)        # 단풍철, 목요일
    snaps = [fake_snapshot({"설악산": 1}, first={"설악산": dt.date(2026, 9, 28)})]
    dong_calls: list = []

    def fake_dong(zone, name):
        dong_calls.append(zone)
        base = snaps_base[0]
        rows = [(base + dt.timedelta(days=i), 9.0, 23.0, "맑음", 10) for i in range(5)]
        return SimpleNamespace(name=name, issued="2026년 10월 01일 (목)요일 14:00",
                               daily_summary=lambda: rows)

    def fake_scrape(now_, start, span, region):
        days = {d: ScrapedDay(d, 10.0, 15.0, 20.0, 25.0, "맑음", 10, "중기예보")
                for d in (start + dt.timedelta(days=i) for i in range(span))}
        return Scrape(days=days, narratives=[])

    def fake_snap(today, **k):
        if isinstance(snaps[0], Exception):
            raise snaps[0]
        return snaps[0]

    wide = {"제주": ("5000000000", "제주특별자치도"), "서울": ("1100000000", "서울특별시")}
    snaps_base = [now.date()]
    orig = (foliage_mod.fetch_snapshot, dong.fetch_dong, forecast.scrape_range, answer_mod.find_wide,
            snow.fetch_status)
    snow.fetch_status = lambda day: snow.Status(day.year)   # 날씨 답마다 첫눈 한 줄을 봄(기간 없음)
    foliage_mod.fetch_snapshot = fake_snap
    dong.fetch_dong = fake_dong
    forecast.scrape_range = fake_scrape
    answer_mod.find_wide = lambda q: wide.get(q.strip())
    try:
        def ask(q, when=now):
            clear()
            return answer_mod.answer(f"<@U1> {q}", when).text

        for q in ("설악산", "설악산 날씨"):
            dong_calls.clear()
            reply = ask(q)
            assert dong_calls == ["5121060000"], (q, dong_calls)
            assert "설악산 아래 속초시 대포동" in reply and "*설악산* 단풍 — 지금 *첫단풍*" in reply, reply
            assert reply.index("동네예보") < reply.index("*설악산* 단풍"), "날씨를 물었으니 날씨가 먼저다"
        dong_calls.clear()
        hike = ask("주말 설악산 등산")
        assert dong_calls == ["5121060000"] and "*전국*" not in hike, (dong_calls, hike)
        dong_calls.clear()
        assert "내장산 아래" in ask("내장산 가는데 다음 주 날씨") and dong_calls == ["5218053500"]
        # 기상청이 관측을 접었고 올해 예상도 지났으면 산 날씨만 — 기간은 자료가 정함
        snaps_base[0], kept = dt.date(2026, 12, 1), snaps[0]
        snaps[0] = fake_snapshot(in_service=False)
        winter = ask("설악산 날씨", dt.datetime(2026, 12, 1, 9, 0, tzinfo=KST))
        assert "설악산 아래" in winter and "단풍" not in winter, winter
        assert ":maple_leaf:" not in ask("강원 날씨", dt.datetime(2026, 12, 1, 9, 0, tzinfo=KST))
        snaps_base[0], snaps[0] = now.date(), kept

        # 지역 날씨 — 물든 산과 그 기간의 예상만
        gangwon = ask("강원 날씨")
        assert ":maple_leaf: *단풍* — *설악산* 첫단풍 9/28 · *오대산* 첫단풍 10/7 (예상)" in gangwon, gangwon
        assert "치악산" not in gangwon, "기간(10/1~10/7) 밖의 예상이 붙었습니다"
        assert "*치악산* 첫단풍 10/10 (예상)" in ask("강원 다음주")
        # 다음 단계가 기간 안이면 이어서 적음
        assert "*설악산* 첫단풍 9/28 → 절정 10/25 (예상)" in ask(
            "영동 날씨", dt.datetime(2026, 10, 20, 9, 0, tzinfo=KST))
        nationwide = ask("전국 날씨")
        assert "나머지 20곳은 단풍 전" in nationwide and "*오대산* 10/7" in nationwide, nationwide
        assert ":maple_leaf:" not in ask("경남 날씨")
        assert ":maple_leaf:" not in ask("제주")                 # 한라산 첫단풍 예상 10/31 은 답의 날짜 밖
        snaps[0] = fake_snapshot({"북한산": 1}, first={"북한산": dt.date(2026, 9, 30)})
        assert "*북한산* 첫단풍 9/30" in ask("서울")
        # 단풍철 밖이거나 단풍을 못 받아 와도 날씨는 그대로
        snaps[0] = FoliageError("점검 중")
        failed = ask("강원 날씨")
        assert "*강원*" in failed and ":maple_leaf:" not in failed, failed
        assert "설악산 아래" in ask("설악산") and "단풍 —" not in ask("설악산")
    finally:
        (foliage_mod.fetch_snapshot, dong.fetch_dong, forecast.scrape_range, answer_mod.find_wide,
         snow.fetch_status) = orig
        clear()
    print("[ok] 날씨 속 단풍 — 산 이름은 산 날씨와 단풍, 지역 날씨는 그 지역 산 한 줄")


def test_period_next_weekend() -> None:
    from src.mention.parse import _period

    thu = dt.datetime(2026, 10, 1, 9, 0, tzinfo=KST)
    assert _period("주말 설악산", thu)[:2] == (dt.date(2026, 10, 3), 2)
    assert _period("다음 주 주말", thu)[:2] == (dt.date(2026, 10, 10), 2)
    assert _period("다음주 토요일 부산", thu)[0] == dt.date(2026, 10, 10)
    # «요즘» 은 다른 기간·날짜가 없을 때만 이번 주
    assert _period("요즘", thu) == (dt.date(2026, 9, 28), 7, "이번 주")
    assert _period("요즘 내일 날씨", thu)[2] == "내일"
    assert _period("요즘 다음 주", thu)[2] == "다음 주"
    assert _period("요즘 10/3", thu)[0] == dt.date(2026, 10, 3)
    print("[ok] 기간 — '다음 주 주말' 은 다음 주의 토·일, '요즘' 은 다른 기간이 없을 때 이번 주")


def test_foliage_fetch() -> None:
    """산별 날짜: 목록에 딸려 온 상세는 다시 부르지 않고, 촬영일이 빈 상세는 캐시하지 않음."""
    import json

    import src.season.foliage.data as foliage
    from src.common.cache import clear

    def jsonp(places: dict[str, str], flower: dict) -> str:
        return "applyMapleData(" + json.dumps({
            "isService": True, "flower": flower,
            "places": [{"obsPlace": n, "status": st, "sts": None} for n, st in places.items()],
        }, ensure_ascii=False) + ")"

    places = {"설악산": "첫단풍", "오대산": "첫단풍", "치악산": "", "한라산": "단풍전"}
    details = {
        "": {"obsPlace": "설악산", "cfShotDate": "2026-09-28"},
        "오대산": {"obsPlace": "오대산", "cfShotDate": ""},       # 단계만 먼저 바뀌었음
    }
    calls: list = []

    def fake_kma(place="", timeout=None):
        calls.append(place)
        return jsonp(places, details[place])

    orig = foliage._kma
    foliage._kma = fake_kma
    clear()
    try:
        status = foliage.fetch_status(dt.date(2026, 10, 1))
        # "sts": null·모르는 글자는 단풍전
        assert status.stage("치악산") == 0 and status.stage("오대산") == 1
        assert status.first == {"설악산": dt.date(2026, 9, 28)}, status.first
        assert calls == ["", "오대산"], f"설악산 상세를 다시 불렀습니다: {calls}"
        details["오대산"]["cfShotDate"] = "2026-10-06"
        assert foliage._detail("오대산", 1, 2026) == (dt.date(2026, 10, 6), None)
        details["오대산"]["cfShotDate"] = ""
        assert foliage._detail("오대산", 1, 2026)[0] == dt.date(2026, 10, 6), "날짜가 생기면 캐시한다"
    finally:
        foliage._kma = orig
        clear()

    # 웨더아이 예상이 아직 없으면 None — 30분만 기억함
    gets: list = []
    orig_get = foliage._get

    def fake_get(url, **kw):
        gets.append(url)
        from types import SimpleNamespace
        return SimpleNamespace(text="<html>공지 없음</html>", encoding="utf-8")

    foliage._get = fake_get
    try:
        assert foliage.fetch_outlook(2026) is None and foliage.fetch_outlook(2026) is None
        assert len(gets) == 1, f"아직 없는 예상을 {len(gets)}번 받으러 갔습니다"
    finally:
        foliage._get = orig_get
        clear()
    print("[ok] 단풍 수집 — 목록 상세 재사용 · 빈 상세 미캐시 · 미발표 짧게 기억")


def test_cache_failures() -> None:
    """실패를 잠시 기억하고, 지난 항목은 새 값을 넣을 때 걷어냄."""
    import time

    import src.common.cache as cache

    cache.clear()
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("점검 중")

    for _ in range(3):
        try:
            cache.get_or_set("k", 60, boom, errors=(ValueError,), error_ttl=60)
        except ValueError as exc:
            assert str(exc) == "점검 중"
    assert len(calls) == 1, f"실패를 기억하지 못하고 {len(calls)}번 불렀습니다"
    # errors 에 없는 예외는 기억하지 않음
    try:
        cache.get_or_set("j", 60, boom)
    except ValueError:
        pass
    assert "j" not in cache._STORE

    cache.get_or_set("old", 0.01, lambda: "x")
    time.sleep(0.02)
    cache.get_or_set("new", 60, lambda: "y")
    assert "old" not in cache._STORE and "new" in cache._STORE

    # 같은 키를 동시에 찾으면 한 번만 만들고 뒤에 온 쪽은 그 값을 씀
    import threading
    made, started, got = [], threading.Event(), []

    def slow():
        made.append(1)
        started.set()
        time.sleep(0.05)
        return "v"

    first = threading.Thread(target=lambda: got.append(cache.get_or_set("s", 60, slow)))
    first.start()
    started.wait(1)
    got.append(cache.get_or_set("s", 60, slow))
    first.join()
    assert made == [1] and got == ["v", "v"], (made, got)

    # 기억하지 않는 실패도 기다린 쪽은 같은 실패를 받음 — 줄지어 다시 만들지 않음
    made.clear()
    started.clear()

    def slow_fail():
        made.append(1)
        started.set()
        time.sleep(0.05)
        raise ValueError("점검 중")

    failed: list[str] = []

    def ask():
        try:
            cache.get_or_set("f", 60, slow_fail)
        except ValueError as exc:
            failed.append(str(exc))

    first = threading.Thread(target=ask)
    first.start()
    started.wait(1)
    ask()
    first.join()
    assert made == [1] and failed == ["점검 중", "점검 중"], (made, failed)
    assert not cache._FLIGHTS and "f" not in cache._STORE
    cache.clear()
    print("[ok] 캐시 — 실패 기억, 지난 항목 정리, 동시에 찾은 같은 키는 한 번만")


def test_foliage_render() -> None:
    from src.season.foliage.data import STAGES
    from src.season.foliage.map import build_html
    from src.season.foliage.map import render_png as render_map
    from src.season.foliage.text import observed_line

    d = dt.date
    early = fake_snapshot({"설악산": 1}, first={"설악산": d(2026, 9, 28)})
    html_text = build_html(early, d(2026, 10, 5))
    assert "첫단풍 <b>오대산</b> 10/7 · <b>치악산</b> 10/10" in html_text, "이번 주 예상이 빠졌습니다"
    assert "9/4 발표" in html_text

    # 물든 곳이 많아지면 이름을 늘어놓지 않고 개수와 최근 변화로 줄임
    late = fake_snapshot(
        {"설악산": 2, "오대산": 2, "치악산": 1, "북한산": 1, "한라산": 1},
        first={"설악산": d(2026, 9, 28), "오대산": d(2026, 10, 6), "치악산": d(2026, 10, 12),
               "북한산": d(2026, 10, 20), "한라산": d(2026, 10, 25)},
        peak={"설악산": d(2026, 10, 18), "오대산": d(2026, 10, 15)},
    )
    line = observed_line(late)
    assert line.startswith(f"{STAGES[2]} 2곳 · {STAGES[1]} 3곳 · {STAGES[0]} 16곳"), line
    assert "한라산</b> 첫단풍 10/25" in line, line

    assert observed_line(fake_snapshot({"설악산": 1})) == "<b>설악산</b> 첫단풍, 나머지 20곳은 단풍 전"

    assert "올해 예상이 아직 나오지 않았습니다" in build_html(fake_snapshot(outlook=False), d(2026, 9, 14))

    IMG.mkdir(parents=True, exist_ok=True)
    png = render_map(late, d(2026, 10, 26))
    assert png.startswith(PNG_MAGIC)
    (IMG / "foliage-test.png").write_bytes(png)
    print(f"[ok] 단풍 지도 {len(png):,}B -> {IMG / 'foliage-test.png'}")


def test_map_emoji() -> None:
    """지도 표지 그림(Noto Emoji) — 편집기 자료는 빼고, 한 장에 여럿 넣어도 그러데이션 id 가 겹치지 않음."""
    import re

    from src.season.basemap import EMOJI, emoji

    svg = "".join(emoji(name, 10, 10, 20) for name in EMOJI) + emoji("maple", 40, 10, 20, opacity=0.45)
    assert "i:" not in svg and "<?xml" not in svg and "DOCTYPE" not in svg
    ids = re.findall(r'id="([^"]+)"', svg)
    assert all(i.split("-", 1)[0] in EMOJI for i in ids), ids
    once = re.findall(r'id="([^"]+)"', "".join(emoji(name, 10, 10, 20) for name in EMOJI))
    assert len(set(once)) == len(once), "같은 그림 두 번 말고는 id 가 겹치면 안 됨"
    assert all(ref in ids for ref in re.findall(r"url\(#([^)]+)\)", svg)), "가리키는 그러데이션이 없음"
    assert 'opacity="0.45"' in svg and svg.count('viewBox="0 0 128 128"') == len(EMOJI) + 1
    print("[ok] 지도 표지 그림 — Noto 🍁 🍂 ❄️, 편집기 자료 제거, id 겹침 없음, 옅게 그리기")


def test_foliage_after_peak() -> None:
    """절정 뒤 — 기상청은 낙엽을 관측하지 않아 «졌다» 대신 절정 사진 뒤 지난 날수만 사실로 적음."""
    from src.common.text import bold
    from src.season.foliage.map import build_html
    from src.season.foliage.map import render_png as render_map
    from src.season.foliage.mountains import MOUNTAINS
    from src.season.foliage.text import observed_line, past_peak, peak_age, week_line

    d = dt.date
    monday = d(2026, 11, 16)
    late = {"두륜산": d(2026, 11, 9), "금오산": d(2026, 11, 6)}
    snap = fake_snapshot({m.name: 2 for m in MOUNTAINS},
                         peak={m.name: d(2026, 10, 20) for m in MOUNTAINS} | late)

    assert peak_age(snap, "두륜산", monday) == 7 and peak_age(snap, "설악산", monday) == 27
    assert peak_age(snap, "두륜산", d(2026, 11, 8)) is None                  # 앞날의 관측은 셈하지 않음
    assert past_peak(snap, monday) == ([("두륜산", d(2026, 11, 9)), ("금오산", d(2026, 11, 6))], 19)

    line = observed_line(snap, bold, day=monday)
    assert line.startswith("절정 21곳(2주 넘음 19곳) — 최근 *두륜산* 절정 11/9"), line
    assert observed_line(snap, bold).startswith("절정 21곳 — "), "day 없이는 지난 날수를 붙이지 않음"

    # 남은 예상 변화가 없으면 절정 2주 안인 산을 적음 — 늦가을 내내 «예상된 변화가 없습니다» 만 나오지 않게
    week = week_line(snap, monday, monday + dt.timedelta(days=6), bold, muted=lambda s: s)
    assert week == "예상된 변화 없음 · 절정 2주 안 *두륜산* 11/9 · *금오산* 11/6", week
    later = week_line(snap, d(2026, 11, 30), d(2026, 12, 6), bold, muted=lambda s: s)
    assert later == "예상된 변화 없음 · 모든 산이 절정 뒤 2주를 넘겼습니다", later
    many = fake_snapshot({m.name: 2 for m in MOUNTAINS}, peak={m.name: d(2026, 11, 10) for m in MOUNTAINS})
    assert week_line(many, monday, monday, bold).endswith(" 외 17곳"), "많으면 넷만 적고 나머지는 개수로"
    assert "졌" not in week + line + later, "관측하지 않은 낙엽을 말했습니다"

    html_text = build_html(snap, monday)
    assert "절정 2주 넘음" in html_text and "(2주 넘음 19곳)" in html_text
    assert "절정 2주 넘음" not in build_html(fake_snapshot({"설악산": 1}), d(2026, 10, 5)), "옅은 표지가 없으면 범례도 없음"

    IMG.mkdir(parents=True, exist_ok=True)
    png = render_map(snap, monday)
    assert png.startswith(PNG_MAGIC)
    (IMG / "foliage-after-peak.png").write_bytes(png)
    print(f"[ok] 단풍 절정 뒤 — 2주 넘음 개수 · 절정 2주 안 산 · 옅은 표지 {len(png):,}B -> {IMG / 'foliage-after-peak.png'}")


# --- 게시물 문단 --------------------------------------------------------------

def test_paragraph() -> None:
    """문단 부품. 줄을 조립하고, 빈 줄·빈 문단은 빠지고, 게시물은 본문 → 문단 → 출처 순."""
    from src.weekly.paragraph import Block, Message, Paragraph

    p = Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:").add("관측", "*진해* 개화 3/24").add("올해", "")
    assert [r.label for r in p.rows] == ["관측"], "빈 내용 줄이 들어갔습니다"
    assert p.to_slack() == ":cherry_blossom: *이번 주 벚꽃*\n• 관측 — *진해* 개화 3/24"
    assert Paragraph("제목").add("줄", "내용").to_slack() == "*제목*\n• 줄 — 내용"

    chart, leaves = fake_attachment("surf"), fake_attachment("foliage")
    msg = (Message("날씨 본문")
           .add(Block(None, "지상일기도 · 기상청", chart))           # 글 없이 그림·출처만
           .add(Block(Paragraph("이번 주 단풍", ":maple_leaf:").add("관측", "설악산"), "단풍 지도 · 기상청", leaves))
           .add(Block(Paragraph("빈 문단"), "쓰이지 않는 출처"))
           .add(Block(None, "그림도 없는 출처"))
           .add(Block(p, "벚꽃 · 기상청")))
    assert msg.attachments == [chart, leaves]
    assert leaves.upload() == {"filename": "foliage.png", "file": b"PNG", "title": "foliage", "alt_txt": "그림"}
    assert msg.to_slack() == (
        "날씨 본문\n\n"
        ":maple_leaf: *이번 주 단풍*\n• 관측 — 설악산\n\n"
        ":cherry_blossom: *이번 주 벚꽃*\n• 관측 — *진해* 개화 3/24\n\n"
        "_지상일기도 · 기상청_\n_단풍 지도 · 기상청_\n_벚꽃 · 기상청_"
    ), msg.to_slack()
    assert Message("본문만").to_slack() == "본문만"
    print("[ok] 문단 조립 — 줄 · 빈 줄/빈 문단 제외 · 글 없는 그림 덩어리 · 본문 → 문단 → 출처 · 첨부")


# --- 벚꽃 -------------------------------------------------------------------

def test_blossom_season() -> None:
    """기간은 자료가 정함 — 기상청 관측 중이거나, 관측 전이라도 올해 개화 예상일이 남았을 때만."""
    from src.season.blossom.data import Outlook, Status, showing

    d = dt.date
    on, off = Status(stages={"여의도 윤중로": 1}), Status(stages={"여의도 윤중로": 0}, in_service=False)
    expected = Outlook(expected={"서귀포": d(2026, 3, 20), "서울": d(2026, 4, 3)}, normal={})
    borrowed = Outlook(expected={}, normal={"서울": d(2026, 4, 8)})             # 올해 예상 전 — 지난해 표의 평년만
    assert showing(on, borrowed, d(2026, 4, 6)) and showing(on, None, d(2026, 4, 13))   # 4월 서울 개화까지 관측을 따라감
    assert showing(off, expected, d(2026, 2, 23)) and showing(None, expected, d(2026, 3, 20))   # 첫 예상일까지
    assert not showing(off, expected, d(2026, 3, 30))          # 첫 예상일이 지났는데 서비스가 꺼져 있으면 접은 것
    assert not showing(off, borrowed, d(2026, 2, 23)) and not showing(off, None, d(2026, 11, 16))
    print("[ok] 벚꽃 기간 — 기상청 관측 중이거나 남은 개화 예상일이 있을 때만 (고정 기간 없음)")


def test_blossom_parse() -> None:
    """기상청 JSONP 와 웨더아이 표. 해마다 바뀐 날짜 표기, 군락지·평균 줄, 깨진 표."""
    import json

    from src.season.blossom.data import BlossomError, parse_outlook_text, parse_status
    from src.season.sources import posted_on

    def jsonp(service: bool) -> str:
        places = [{"obsPlace": n, "status": s, "sts": str(["개화 전", "개화", "만발"].index(s) + 1)}
                  for n, s in (("진해 여좌천", "만발"), ("여의도 윤중로", "개화"), ("춘천 소양강댐", "개화 전"))]
        return "\r\n\r\napplyFlowerData(" + json.dumps(
            {"places": places, "isService": service, "flower": {}}, ensure_ascii=False) + ")"

    stages, live = parse_status(jsonp(True))
    assert live and stages == {"진해 여좌천": 2, "여의도 윤중로": 1, "춘천 소양강댐": 0}, stages
    # 서비스 기간 밖이면 지난 봄 값이라 버림
    stages, live = parse_status(jsonp(False))
    assert not live and set(stages.values()) == {0}, stages

    cities = ["서귀포", "부산", "창원", "울산", "여수", "광주", "목포", "전주", "대구", "포항",
              "안동", "대전", "청주", "서산", "수원", "서울", "인천", "강릉", "춘천"]
    rows = [f"   {c}      3/{10 + i}      3/{11 + i} (-1)      3/{12 + i} (-2)" for i, c in enumerate(cities)]
    rows[0] = "           서귀포                      3/25                 3/24 (+1)                 3/27 (-2)"
    rows[1] = "            부산                         3.22                   3.28 (-6)                   3.19 (+3)"
    rows[2] = "            창원                         4. 1                   4.06 (-5)                   3 23 (+8)"
    extra = ["           평균                                             (-3.7)                    (-0.7)",
             "                  진해   여좌천                                3/27                    3/29 (-2)",
             "             서울 여의도 여의서로                                  4/03                    4/03 (±0)"]
    expected, normal = parse_outlook_text("\n".join(rows + extra), 2026)
    assert len(expected) == 19 and "평균" not in expected and "진해" not in expected
    assert expected["서귀포"] == dt.date(2026, 3, 25) and normal["서귀포"] == dt.date(2026, 3, 24)
    assert expected["부산"] == dt.date(2026, 3, 22) and expected["창원"] == dt.date(2026, 4, 1)
    for bad, why in ((rows[:10], "도시를 너무 적게 읽었는데 통과했습니다"),
                     ([rows[0].replace("3/25", "5/25")] + rows[1:], "범위 밖 날짜가 통과했습니다")):
        try:
            parse_outlook_text("\n".join(bad), 2026)
            raise AssertionError(why)
        except BlossomError:
            pass

    # 게시일은 특보 띠가 아닌 머리 표의 날짜 칸 (작성자 칸은 빌 수 있음)
    page = ('<marquee>2026-10-02 강풍주의보</marquee><font color="#124c78"></font>'
            '<font color="#124c78">2026-02-26 </font>')
    assert posted_on(page, 2026) == dt.date(2026, 2, 26)
    assert posted_on(page.replace("2026-02-26", "관리자"), 2026) is None
    print("[ok] 벚꽃 자료 읽기 — 날짜 표기 세 가지 · 군락지/평균 줄 제외 · 깨진 표 버림 · 게시일")


def test_blossom_text() -> None:
    """벚꽃 줄 문구. 예상 전엔 평년, 이번 주가 비면 다음 개화, 출처는 웨더아이만."""
    from src.season.blossom.data import Outlook
    from src.season.blossom.text import sources, week_line, year_line

    d = dt.date
    normal = {"서귀포": d(2026, 3, 24), "부산": d(2026, 3, 28), "서울": d(2026, 4, 8)}
    outlook = Outlook(expected={"서귀포": d(2026, 3, 25), "부산": d(2026, 3, 25), "울산": d(2026, 3, 26),
                                "서울": d(2026, 4, 3)},
                      normal=normal | {"울산": d(2026, 3, 30)}, published=d(2026, 2, 26))
    unpublished = Outlook(expected={}, normal=normal)

    assert "아직 나오지 않았습니다" in week_line(unpublished, d(2026, 2, 23), d(2026, 3, 1))
    assert year_line(unpublished) == "*서귀포* 3/24 무렵 시작해 *서울* 4/8 무렵 핍니다"

    assert week_line(outlook, d(2026, 3, 2), d(2026, 3, 8)) == "개화 예상 없음 · 다음은 *서귀포*·*부산* 3/25 (예상)"
    # 평년차 +1 · -3 · -4 · -5 → 평균 -2.75 → 3일
    assert year_line(outlook) == "평년보다 3일가량 이르겠습니다 (서울 4/3, 평년 4/8)"
    assert week_line(outlook, d(2026, 3, 23), d(2026, 3, 29)) == \
        "개화 *서귀포*·*부산* 3/25 · *울산* 3/26 (예상)"

    assert sources(outlook) == "예상 웨더아이(2/26 발표)"
    assert sources(unpublished) == "평년 웨더아이"
    print("[ok] 벚꽃 문구 — 평년 · 다음 개화 · 이번 주 묶음 · 출처")


# 웨더아이 2026년 표의 도시 — 지도 좌표가 빠짐없이 있어야 함
BLOSSOM_CITIES = ("서귀포", "부산", "창원", "울산", "여수", "광주", "목포", "전주", "대구", "포항",
                  "안동", "대전", "청주", "서산", "수원", "서울", "인천", "강릉", "춘천")


def test_blossom_fetch() -> None:
    """기상청 목록은 한 번만 — 다룰 때인지(isService)만 보고 군락지 상세는 부르지 않음. 형식이 바뀌면 BlossomError."""
    import json

    import src.season.blossom.data as blossom

    calls: list = []

    def fake_kma():
        calls.append("목록")
        return "applyFlowerData(" + json.dumps({
            "isService": True, "flower": {"obsPlace": "인천자유공원"},
            "places": [{"obsPlace": "진해 여좌천", "status": "만발"}, {"obsPlace": "여의도 윤중로", "status": "개화"}],
        }, ensure_ascii=False) + ")"

    orig = blossom._kma
    blossom._kma = fake_kma
    try:
        status = blossom.fetch_status()
        assert status.in_service and status.stages == {"진해 여좌천": 2, "여의도 윤중로": 1}, status
        assert calls == ["목록"], calls
        blossom._kma = lambda: 'applyFlowerData({"isService": true, "places": [1]})'
        try:
            blossom.fetch_status()
            raise AssertionError("깨진 목록이 통과했습니다")
        except blossom.BlossomError:
            pass
    finally:
        blossom._kma = orig
    print("[ok] 벚꽃 수집 — 기상청 목록 한 번 · 형식 변경은 BlossomError")


def test_blossom_spots() -> None:
    """벚꽃 지도 좌표 — 웨더아이 도시가 빠짐없이, 바탕 지도 안에, 라벨이 서로·남의 표지와 안 겹치게."""
    from src.season.basemap import (
        INSET_BOX,
        INSET_LON,
        LAT0,
        LAT1,
        LON0,
        LON1,
        hits,
        label_box,
        nudge,
        place,
    )
    from src.season.blossom.map import MARK_R, RING_GAP, RING_LABEL_PAD
    from src.season.blossom.spots import CITIES
    from src.season.mapcard import glyph_size

    assert sorted(s.name for s in CITIES) == sorted(BLOSSOM_CITIES), "웨더아이 도시와 지도 좌표가 다릅니다"
    assert all(LAT0 < s.lat < LAT1 and (LON0 < s.lon < LON1 or s.lon > INSET_LON) for s in CITIES)
    # 가장 나쁜 때로 봄 — 모두 이번 주(고리 · 밀린 라벨)이고 날짜는 가장 넓은 4/12. 고리는 🌸 의 반 + 틈 + 선 굵기
    r = glyph_size(MARK_R) / 2 + RING_GAP + 0.7
    at = {s.name: place(s.lon, s.lat) for s in CITIES}
    boxes = [(s.name, label_box(*nudge(*at[s.name], s.label, RING_LABEL_PAD), f"{s.name} 4/12", s.label))
             for s in CITIES]
    marks = {name: (x - r, y - r, x + r, y + r) for name, (x, y) in at.items()}
    for i, (name, box) in enumerate(boxes):
        assert not hits(box, INSET_BOX), f"{name} 라벨이 울릉도 상자에 걸립니다"
        assert not any(hits(box, other) for _, other in boxes[i + 1:]), f"{name} 라벨이 다른 라벨과 겹칩니다"
        assert not any(hits(box, m) for n, m in marks.items() if n != name), f"{name} 라벨이 남의 표지를 가립니다"
    print("[ok] 벚꽃 지점 — 도시 19 좌표, 지도 안, 라벨 겹침 없음")


def test_blossom_render() -> None:
    """벚꽃 지도 — 한 장, 웨더아이 도시 예상: 남은 곳 회색 원 · 이번 주 옅은 🌸 와 점선 고리 · 지난 곳 🌸. 관측은 싣지 않음."""
    from src.season.blossom.data import Outlook
    from src.season.blossom.map import build_html
    from src.season.blossom.map import render_png as render_map

    d = dt.date
    monday = d(2026, 3, 30)
    outlook = Outlook(expected={"서귀포": d(2026, 3, 25), "부산": d(2026, 3, 25), "대전": d(2026, 3, 31),
                                "서울": d(2026, 4, 3), "춘천": d(2026, 4, 8)},
                      normal={"서귀포": d(2026, 3, 24), "서울": d(2026, 4, 8)}, published=d(2026, 2, 26))
    html_text = build_html(outlook, monday)
    assert html_text.count('role="img"') == 1 and "<th>도시</th>" in html_text
    assert html_text.count('<tr><th scope="row">') == 3                       # 도시 5곳은 두 갈래 3줄
    assert '<span class="prd week">3/31</span>' in html_text and '<span class="prd past">3/25</span>' in html_text
    assert "개화 <b>대전</b> 3/31 · <b>서울</b> 4/3 (예상)" in html_text and "(2/26 발표, 5개 도시)" in html_text
    assert "관측" not in html_text and "기상청" not in html_text, "기상청 군락지 관측이 남았습니다"

    # 지난 곳 2 🌸 · 이번 주 2 옅은 🌸 + 고리 · 남은 곳 1 회색 원
    svg, legend = html_text.split('<div class="legend">')
    assert svg.count('viewBox="0 0 128 128"') == 4 and svg.count('opacity="0.65"') == 2
    assert svg.count('stroke-dasharray="2.6 2.2"') == 2 and svg.count('stroke="#898781"') == 1
    assert svg.count('class="lbl strong"') == 2 and svg.count('<g class="past"><text class="lbl"') == 2
    assert all(w in legend for w in ("개화 예상 전", "이번 주 개화 예상", "개화 예상일 지남"))
    early = build_html(outlook, d(2026, 3, 16)).split('<div class="legend">')[1]
    assert "개화 예상 전" in early and "이번 주" not in early and "지남" not in early, "범례는 지도에 나온 표지만"

    # 올해 예상 전 — 지난해 표의 평년, 표지는 같고 낱말만 «평년»
    borrowed = build_html(Outlook(expected={}, normal=outlook.normal), monday)
    assert "평년 개화일 전" in borrowed and "평년 개화일 지남" in borrowed and "<th>예상</th>" not in borrowed
    assert "평년 웨더아이 지난해 표" in borrowed

    IMG.mkdir(parents=True, exist_ok=True)
    png = render_map(outlook, monday)
    assert png.startswith(PNG_MAGIC)
    (IMG / "blossom-test.png").write_bytes(png)
    print(f"[ok] 벚꽃 지도 {len(png):,}B -> {IMG / 'blossom-test.png'}")


def fake_attachment(slug: str):
    from src.weekly.paragraph import Attachment

    return Attachment(b"PNG", slug, "그림", f"{slug}.png", 14, f"{slug}-*.png")


def weekly_cfg():
    from types import SimpleNamespace

    return SimpleNamespace(card_scale=2, card_keep_days=14, chart_keep_days=30, chart_product="surf")


def weekly_ctx(start: dt.date, today: dt.date | None = None, *, can_render: bool = True, days=None,
               narratives=(), body: str = "본문"):
    """주간 영역의 Context. days 를 주면 1번 날씨가 그 예보(예보관 서술 narratives · 본문 body)로 끝난 것으로 둠."""
    from concurrent.futures import Future

    from src.season.weeks import week_start_of
    from src.weekly.sections import Context, Weather

    today = today or start
    offset = (start - week_start_of(today)).days // 7
    weather = None
    if days is not None:
        weather = Future()
        weather.set_result(Weather(WeekForecast("전국", start, days, narratives=list(narratives)), body))
    ctx = Context(weekly_cfg(), dt.datetime.combine(today, dt.time(7, 50), tzinfo=KST), offset, can_render, weather)
    assert ctx.week_start == start, (ctx.week_start, start)
    return ctx


def test_weekly_themes() -> None:
    """주간 게시의 철 소식. 단풍·벚꽃은 글과 지도. 수집 실패는 예외로 올려 pipeline 이 그 영역만 뺌."""
    import src.season.blossom.data as blossom
    import src.season.blossom.map as blossom_map
    import src.season.foliage.data as foliage
    import src.season.foliage.map as foliage_map
    from src.season.blossom.data import BlossomError, Outlook, Status
    from src.season.foliage.data import FoliageError
    from src.weekly import pipeline, themes

    d = dt.date
    renders: list = []
    fail_render = [False]

    def fake_render(snap, start, scale=2):
        renders.append(start)
        if fail_render[0]:
            raise RuntimeError("Chromium 없음")
        return b"PNG"

    def labels(block):
        return [r.label for r in block.paragraph.rows]

    autumn_ctx = weekly_ctx(d(2026, 10, 5), d(2026, 10, 2))
    spring_ctx = weekly_ctx(d(2026, 3, 23))
    assert [s.name for s in pipeline.SECTIONS] == ["카드", "일기도", "벚꽃", "장마", "폭염", "태풍", "단풍", "첫눈"]   # 기간 없이 늘 돎

    orig = (foliage.fetch_snapshot, foliage_map.render_png, blossom.fetch_status, blossom.fetch_outlook,
            blossom_map.render_png)
    foliage.fetch_snapshot = lambda today, **k: fake_snapshot({"설악산": 1}, first={"설악산": d(2026, 9, 28)})
    foliage_map.render_png = fake_render
    # 실제와 같은 인자 꼴로 받음 — 부르는 쪽 인자가 어긋나면 그림이 빠져 아래 단언에 걸림
    blossom_map.render_png = lambda outlook, start, *, scale=2: fake_render(outlook, start, scale)
    blossom.fetch_status = lambda: Status(stages={"진해 여좌천": 0}, in_service=False)
    blossom.fetch_outlook = lambda year, **k: Outlook(expected={"서귀포": d(2026, 3, 25)},
                                                normal={"서귀포": d(2026, 3, 24)}, published=d(2026, 2, 26))
    try:
        autumn = themes.foliage_block(autumn_ctx)
        assert autumn.paragraph.title == "이번 주 단풍" and labels(autumn) == ["관측", "이번 주"]
        text = autumn.paragraph.to_slack()
        assert "*설악산* 첫단풍 9/28" in text and "첫단풍 *오대산* 10/7 · *치악산* 10/10 (예상)" in text, text
        assert autumn.attachment.png == b"PNG" and autumn.attachment.title == "단풍 지도"
        assert autumn.attachment.filename == "foliage-20261005.png" and autumn.attachment.pattern == "foliage-*.png"
        assert autumn.credit.startswith("단풍 지도 · "), autumn.credit
        # 지도를 못 그려도 글은 남고, 출처에서 '지도' 가 빠짐
        fail_render[0] = True
        autumn = themes.foliage_block(autumn_ctx)
        assert autumn.attachment is None and autumn.credit.startswith("단풍 · ") and autumn.paragraph.rows
        # 헬스체크에서 Chromium 이 실패했으면 그리려 하지도 않음
        fail_render[0] = False
        renders.clear()
        autumn = themes.foliage_block(weekly_ctx(d(2026, 10, 5), d(2026, 10, 2), can_render=False))
        assert autumn.attachment is None and autumn.credit.startswith("단풍 · ") and not renders

        spring = themes.blossom_block(spring_ctx)
        assert spring.paragraph.title == "이번 주 벚꽃" and spring.attachment.title == "벚꽃 지도"
        assert spring.attachment.filename == "blossom-20260323.png" and spring.attachment.pattern == "blossom-*.png"
        assert labels(spring) == ["이번 주", "올해"], labels(spring)       # 기상청 군락지 관측은 싣지 않음
        assert "*서귀포* 3/25" in spring.paragraph.to_slack()
        assert spring.credit == "벚꽃 지도 · 예상 웨더아이(2/26 발표)", spring.credit
        # 벚꽃 지도도 못 그리면 글만, Chromium 이 없으면 그리려 하지도 않음
        fail_render[0] = True
        spring = themes.blossom_block(spring_ctx)
        assert spring.attachment is None and spring.credit.startswith("벚꽃 · ") and spring.paragraph.rows
        fail_render[0] = False
        renders.clear()
        spring = themes.blossom_block(weekly_ctx(d(2026, 3, 23), can_render=False))
        assert spring.attachment is None and spring.credit.startswith("벚꽃 · ") and not renders
        # 관측 중인지 못 받아도 관측 전 첫 예상일까지는 예상으로 실음
        blossom.fetch_status = lambda: (_ for _ in ()).throw(BlossomError("점검"))
        spring = themes.blossom_block(spring_ctx)
        assert labels(spring) == ["이번 주", "올해"], labels(spring)
        # 올해 예상 전 — 기상청이 관측 중이면 평년으로, 관측 전이면 다룰 때가 아님(자료가 기간을 정함)
        blossom.fetch_outlook = lambda year, **k: Outlook(expected={}, normal={"서귀포": d(2026, 3, 24)})
        blossom.fetch_status = lambda: Status(stages={"진해 여좌천": 1})
        spring = themes.blossom_block(weekly_ctx(d(2026, 2, 23)))
        assert labels(spring) == ["이번 주", "평년"] and spring.credit == "벚꽃 지도 · 평년 웨더아이", spring.credit
        blossom.fetch_status = lambda: Status(stages={"진해 여좌천": 0}, in_service=False)
        assert themes.blossom_block(weekly_ctx(d(2026, 2, 23))) is None
        # 관측 중이어도 웨더아이 표가 올해·지난해 모두 없으면 실을 것이 없음
        blossom.fetch_status = lambda: Status(stages={"진해 여좌천": 1})
        blossom.fetch_outlook = lambda year, **k: Outlook(expected={}, normal={})
        assert themes.blossom_block(spring_ctx) is None
        # 웨더아이 수집 실패는 «해당 없음» 이 아니라 실패 — 실을 것이 예상뿐이라 관측 중이든(앞) 기상청까지
        # 실패했든(뒤) 영역 경계가 경고로 남기고 뺌
        blossom.fetch_outlook = lambda year, **k: (_ for _ in ()).throw(BlossomError("점검"))
        for status_of in (blossom.fetch_status, lambda: (_ for _ in ()).throw(BlossomError("점검"))):
            blossom.fetch_status = status_of
            try:
                themes.blossom_block(spring_ctx)
                raise AssertionError("웨더아이 수집 실패가 묻혔습니다")
            except BlossomError:
                pass
        # 단풍도 기상청이 관측을 접었고 올해 예상도 지났으면 해당 없음
        foliage.fetch_snapshot = lambda today, **k: fake_snapshot(in_service=False)
        assert themes.foliage_block(weekly_ctx(d(2026, 11, 16))) is None
        # 단풍 수집 실패는 예외로 올림 — 영역 경계(pipeline)가 빈 결과로 바꿈
        foliage.fetch_snapshot = lambda today, **k: (_ for _ in ()).throw(FoliageError("점검"))
        try:
            themes.foliage_block(autumn_ctx)
            raise AssertionError("단풍 수집 실패가 묻혔습니다")
        except FoliageError:
            pass
    finally:
        (foliage.fetch_snapshot, foliage_map.render_png, blossom.fetch_status, blossom.fetch_outlook,
         blossom_map.render_png) = orig
    print("[ok] 철 소식 — 단풍·벚꽃 글·지도, 지도·Chromium 실패엔 글만, 수집 실패는 영역 경계로")


def test_weekly_pipeline() -> None:
    """영역을 동시에 돌려 합침 — 실패·해당 없음·기한 초과는 빠지고, 날씨가 실패하면 게시하지 않음."""
    import threading
    import time

    from src.weekly import pipeline, sections
    from src.weekly.forecast import ForecastError
    from src.weekly.paragraph import Block, Paragraph
    from src.weekly.sections import Section, Weather

    week = fake_week()
    card, chart = fake_attachment("weekly-weather"), fake_attachment("surf")
    card_drawn = [True]
    met = threading.Event()

    def slow_weather(ctx):
        time.sleep(0.2)                    # 카드·눈이 기다려 받는지 보려고 늦게 끝냄
        return Weather(week, "본문")

    def card_section(ctx):
        assert ctx.forecast() is week
        return Block(None, attachment=card) if card_drawn[0] else None

    def snow(ctx):
        got = ctx.forecast()
        return Block(Paragraph("눈").add("이번 주", f"예보 {len(got.days)}일"), "눈 · 기상청")

    def waits_for_partner(ctx):
        # 동시에 돌아야만 짝이 깃발을 올려 줌 — 차례로 돌면 1초 기다리고 빈 결과
        return Block(Paragraph("동시").add("짝", "만남")) if met.wait(1.0) else None

    def partner(ctx):
        met.set()
        return None

    def too_slow(ctx):
        time.sleep(1.5)
        return Block(Paragraph("느림").add("줄", "기한 초과"))

    fake = (
        Section("카드", card_section),
        Section("일기도", lambda ctx: Block(None, "지상일기도 · 기상청", chart)),
        Section("고장", lambda ctx: (_ for _ in ()).throw(RuntimeError("점검"))),
        Section("없음", lambda ctx: None),
        Section("동시", waits_for_partner),
        Section("짝", partner),
        Section("느림", too_slow),
        Section("눈", snow),
    )
    now = dt.datetime(2026, 11, 16, 7, 50, tzinfo=KST)
    orig = (pipeline.SECTIONS, sections.weather, pipeline.SECTIONS_TIMEOUT_SEC)
    pipeline.SECTIONS, sections.weather, pipeline.SECTIONS_TIMEOUT_SEC = fake, slow_weather, 1.0
    try:
        post = pipeline.compose(weekly_cfg(), now)
        assert post.text == (
            "본문\n\n*동시*\n• 짝 — 만남\n\n*눈*\n• 이번 주 — 예보 7일\n\n_지상일기도 · 기상청_\n_눈 · 기상청_"
        ), post.text
        assert post.attachments == [card, chart] and post.week is week

        # 카드를 못 그렸으면(헬스체크 Chromium 실패 포함) 첨부는 나머지만
        card_drawn[0] = False
        assert pipeline.compose(weekly_cfg(), now).attachments == [chart]

        # 날씨가 실패하면 게시하지 않음 — 지어낸 날씨를 올리지 않기
        sections.weather = lambda ctx: (_ for _ in ()).throw(ForecastError("7일 중 4일의 기온을 얻지 못해"))
        assert pipeline.compose(weekly_cfg(), now) is None
        sections.weather = lambda ctx: (_ for _ in ()).throw(KeyError("버그"))
        assert pipeline.compose(weekly_cfg(), now) is None
    finally:
        pipeline.SECTIONS, sections.weather, pipeline.SECTIONS_TIMEOUT_SEC = orig
    print("[ok] 주간 영역 — 동시 실행, 실패·해당 없음·기한 초과는 빠짐, 카드·눈은 날씨 예보를 받음, 날씨 실패면 게시 안 함")


def test_weekly_health() -> None:
    """헬스체크 — 슬랙이 안 되면 영역을 돌리지 않고 멈춤(dry-run 은 계속), Chromium 결과는 영역에 넘김."""
    from src.weekly import health, pipeline, post
    from src.weekly.health import Health

    calls: list = []
    orig = (post.setup, health.check, pipeline.compose,
            health.check_slack, health.check_kma, health.check_chromium)
    post.setup = lambda name: None
    pipeline.compose = lambda cfg, now, offset, can_render: calls.append(can_render)
    try:
        health.check = lambda cfg: Health(slack=False, chromium=True)
        assert post.main([]) == 1 and calls == [], calls
        assert post.main(["--dry-run"]) == 1 and calls == [True], calls   # compose 가 None — 날씨 실패로 끝남
        health.check = lambda cfg: Health(slack=True, chromium=False)
        calls.clear()
        assert post.main(["--no-wait"]) == 1 and calls == [False], calls

        health.check = orig[1]
        health.check_slack = lambda token, channel: (True, "슬랙")
        health.check_kma = lambda: calls.append("기상청") or (False, "기상청 접속 실패")   # 기록만
        health.check_chromium = lambda: (True, "Chromium")
        calls.clear()
        assert health.check(post.Config()) == Health(slack=True, chromium=True) and calls == ["기상청"]
    finally:
        (post.setup, health.check, pipeline.compose,
         health.check_slack, health.check_kma, health.check_chromium) = orig
    assert health.check_slack("", "C1")[0] is False and health.check_slack("xoxp-1", "C1")[0] is False
    assert health.check_slack("xoxb-1", "")[0] is False

    # 그림이 하나도 없으면(Chromium 실패 + 일기도 실패) 글만 — files_upload_v2 는 빈 첨부를 받지 않음
    from types import SimpleNamespace

    import slack_sdk

    sent: list = []

    class FakeWeb:
        def __init__(self, token):
            pass

        def files_upload_v2(self, **kw):
            sent.append(("files", len(kw["file_uploads"])))
            return {"files": [{"permalink": "p"}]}

        def chat_postMessage(self, **kw):
            sent.append(("text", kw["text"]))
            return {"ts": "1"}

    orig_web, slack_sdk.WebClient = slack_sdk.WebClient, FakeWeb
    try:
        cfg = SimpleNamespace(slack_bot_token="xoxb-1", slack_channel_id="C1")
        assert post._send(pipeline.Post(fake_week(), "본문", []), cfg) == 0
        assert post._send(pipeline.Post(fake_week(), "본문", [fake_attachment("surf")]), cfg) == 0
    finally:
        slack_sdk.WebClient = orig_web
    assert sent == [("text", "본문"), ("files", 1)], sent
    print("[ok] 헬스체크 — 슬랙 실패면 멈춤(dry-run 은 계속), Chromium 결과를 영역에 넘김, 그림 없으면 글만")


def test_snow_data() -> None:
    """첫눈 관측 읽기 — 시즌 연도, 이상 행, 형식 변경, 주간 게시 기간, 지점 찾기."""
    from src.kma.regions import REGIONS
    from src.season.basemap import INSET_LON, LAT0, LAT1, LON0, LON1
    from src.season.snow import data as snow
    from src.season.snow import stations

    def snow_html(rows: dict[str, list[tuple[str, str]]]) -> str:
        """계절관측 조회 화면 꼴 — 지점 머리 뒤에 표 하나, caption 은 지점과 무관한 고정 문구."""
        parts = []
        for name, cells in rows.items():
            body = "".join(f"<tr><td> {y}</td><td> {d}</td><td> 1일</td><td></td><td></td></tr>" for y, d in cells)
            parts.append(f'<div class="info_tbl"><dl><dt>조회기간</dt><dd>2025 ~ 2026년</dd></dl>'
                         f'<dl><dt><b>지점</b></dt><dd>{name}</dd></dl></div><div class="wrap_tbl">'
                         f'<table class="tbl"><caption>코스모스, 매화</caption><thead><tr><th>년도</th>'
                         f'<th>눈</th></tr></thead><tbody>{body}</tbody></table></div>')
        return "<html>" + "".join(parts) + "</html>"

    d = dt.date
    status = snow.parse_status(snow_html({
        "서울": [("2025", "2025-12-04"), ("2026", "2026-11-26")],
        "안동": [("2026", "2026-01-10")],              # 2026 시즌인데 1월 — 실제 응답에 있음
        "부산": [("2025", "2026-02-07")],
        "홍성": [("2026", "2026-11-18")],
        "대구": [],                                      # 아직 — 표머리만 옴
    }), 2026)
    assert status.first == {"서울": d(2026, 11, 26), "홍성": d(2026, 11, 18)}, status.first
    assert status.last == {"서울": d(2025, 12, 4), "부산": d(2026, 2, 7)}, status.last
    # 표가 빠진 지점은 다음 지점의 표를 집지 않고, 머리와 표 사이에 다른 칸이 끼어도 읽음
    odd = ('<dl><dt><b>지점</b></dt><dd>광주</dd></dl>'
           '<dl><dt><b>지점</b></dt><dd>서울</dd></dl><dl><dt>요소</dt><dd>눈</dd></dl>'
           '<table><tr><td>2026</td><td>2026-11-26</td></tr></table>')
    assert snow.parse_status(odd, 2026).first == {"서울": d(2026, 11, 26)}
    try:
        snow.parse_status("<html>점검 중입니다</html>", 2026)
        raise AssertionError("형식이 바뀐 응답을 읽었습니다")
    except snow.SnowError:
        pass

    assert [snow.season_year(x) for x in (d(2026, 7, 31), d(2026, 8, 1), d(2027, 1, 10))] == [2025, 2026, 2026]
    seoul, busan, hongseong = (stations.BY_NAME[n] for n in ("서울", "부산", "홍성"))
    assert snow.gap_days(seoul, d(2026, 11, 26)) == 6 and snow.gap_days(busan, d(2027, 2, 7)) == 46
    assert snow.gap_days(hongseong, d(2026, 11, 18)) is None

    # 기간 없이 자료로 — 7일 안에 관측됐거나, 아직인 곳에 눈 예보가 있을 때만
    assert [s.name for s in snow.recent(status, d(2026, 11, 30))] == ["서울"]          # 홍성 11/18 은 12일 전
    assert [s.name for s in snow.recent(status, d(2026, 11, 25))] == ["홍성"]          # 앞날의 관측은 셈하지 않음
    assert snow.showing(status, d(2026, 11, 30), snowy=False)
    assert not snow.showing(status, d(2026, 12, 7), snowy=False) and snow.showing(status, d(2026, 12, 7), snowy=True)
    nothing = snow.Status(2026)
    assert not snow.showing(nothing, d(2026, 9, 7), snowy=False)                       # 관측도 눈 예보도 없음
    assert snow.showing(nothing, d(2026, 10, 19), snowy=True)                          # 10월이라도 눈 예보면
    everywhere = snow.Status(2026, {s.name: d(2026, 11, 1) for s in stations.STATIONS})
    assert not snow.showing(everywhere, d(2027, 1, 4), snowy=True)                     # 다 관측된 뒤의 눈은 첫눈이 아님

    assert len(stations.STATIONS) == 24 and len({s.stn for s in stations.STATIONS}) == 24
    assert [s.name for s in stations.STATIONS if s.normal is None] == ["홍성"]
    assert all(LAT0 < s.lat < LAT1 and (LON0 < s.lon < LON1 or s.lon > INSET_LON) for s in stations.STATIONS)
    assert {k for s in stations.STATIONS for k in s.regions} <= {r.key for r in REGIONS}
    assert [s.name for s in stations.stations_in_region("영동")] == ["속초", "북강릉"]
    assert [s.name for s in stations.stations_in_zone("1168064000")] == ["서울"]
    assert stations.stations_in_zone("3611000000") == ()                  # 세종 — 관측 지점 없음
    assert stations.find_station("강릉 첫눈 왔어").name == "북강릉" and stations.find_station("첫눈 언제") is None
    # 포털이 가끔 한 번만 늦음 — retries 만큼 더 받고, 그래도 안 되면 실패
    from types import SimpleNamespace

    from src.common.cache import clear
    from src.season import sources

    calls: list = []

    def flaky(url, **kw):
        calls.append(kw.get("timeout"))
        if len(calls) == 1:
            raise snow.SnowError("Read timed out")
        return SimpleNamespace(text=snow_html({"서울": [("2026", "2026-11-08")]}))

    orig = sources.get
    sources.get = flaky
    try:
        clear()
        assert snow.fetch_status(d(2026, 11, 16), timeout=20.0, retries=1).first == {"서울": d(2026, 11, 8)}
        assert calls == [20.0, 20.0], calls
        clear()
        calls.clear()
        try:
            snow.fetch_status(d(2026, 11, 16), timeout=5.0)          # 멘션 덧말은 다시 받지 않음
            raise AssertionError("재시도 없이 첫 실패를 넘겼습니다")
        except snow.SnowError:
            assert calls == [5.0], calls
    finally:
        sources.get = orig
        clear()
    print("[ok] 첫눈 자료 — 시즌 연도 · 이상 행 버림 · 형식 변경 거절 · 게시 기간 · 지점 · 포털 재시도")


def test_snow_text() -> None:
    from types import SimpleNamespace

    from src.common.text import bold, short_day_label
    from src.season.snow.data import Status
    from src.season.snow.text import observed_line, week_line

    d = dt.date
    last = {"서울": d(2025, 12, 4)}
    assert observed_line(Status(2026, {}, last)) == \
        "아직 첫눈이 관측된 곳이 없습니다 — <b>서울</b> 아직 (평년 11/20, 지난겨울 12/4)"
    assert observed_line(Status(2026, {"울릉도": d(2026, 11, 18)}, last), bold) == \
        "*울릉도* 11/18 (평년보다 2일 늦음), 나머지 23곳은 아직 / *서울* 아직 (평년 11/20, 지난겨울 12/4)"
    many = Status(2026, {"울릉도": d(2026, 11, 18), "서울": d(2026, 11, 20), "대전": d(2026, 11, 22)})
    line = observed_line(many, bold)
    assert line == "3곳 관측 · 21곳 아직 — 최근 *대전* 11/22 (평년보다 2일 늦음) · *서울* 11/20 (평년과 같음)", line

    week = d(2026, 11, 30)
    days = [SimpleNamespace(date=week + dt.timedelta(days=i), sky=s)
            for i, s in enumerate(["맑음", "흐리고 비/눈", "흐림", "흐리고 눈", "맑음", "맑음", "맑음"])]
    snowy = f"{short_day_label(d(2026, 12, 1))} · {short_day_label(d(2026, 12, 3))} 눈 예보"
    assert week_line(many, days, muted=lambda s: s) == \
        f"{snowy} (첫눈이 될 수 있음)"
    assert week_line(many, days[:1], muted=lambda s: s) == "예보에 눈 소식이 없습니다"
    print("[ok] 첫눈 문장 — 관측 0·1·여러 곳, 서울 기준, 눈 예보")


def test_snow_weekly() -> None:
    """주간 게시의 첫눈 덩어리 — 새 소식(최근 관측·아직인 곳의 눈 예보)이 있을 때만, «이번 주» 는 날씨 예보에서."""
    from types import SimpleNamespace

    from src.season.snow import data as snow
    from src.season.snow import map as snow_map
    from src.weekly import pipeline, themes

    d = dt.date
    week = d(2026, 11, 30)
    days = [SimpleNamespace(date=week + dt.timedelta(days=1), sky="흐리고 눈")]
    status = snow.Status(2026, {"서울": d(2026, 11, 26)})
    orig = (snow.fetch_status, snow_map.render_png)
    snow.fetch_status = lambda today, **_: status
    drawn: list = []
    snow_map.render_png = lambda st, start, days=(), scale=2: drawn.append(days) or b"PNG"
    try:
        assert [s.name for s in pipeline.SECTIONS] == ["카드", "일기도", "벚꽃", "장마", "폭염", "태풍", "단풍", "첫눈"]
        block = themes.snow_block(weekly_ctx(week, days=days))
        assert block.paragraph.title == "이번 주 첫눈" and [r.label for r in block.paragraph.rows] == ["관측", "이번 주"]
        text = block.paragraph.to_slack()
        assert "*서울* 11/26 (평년보다 6일 늦음)" in text and "눈" in text.split("이번 주 —")[1], text
        assert drawn == [days], drawn
        assert block.attachment.filename == "snow-20261130.png" and block.credit.startswith("첫눈 지도 · ")
        # 날씨 결과가 없으면 «이번 주» 는 예보를 못 받았다고만 함
        assert "예보를 받지 못했습니다" in themes.snow_block(weekly_ctx(week)).paragraph.to_slack()
        assert drawn[-1] is None, drawn                  # 지도도 «눈 소식 없음» 이 아니라 못 받았다고
        # 주 중간에 돌려도 월요일 뒤의 관측을 «최근» 으로 셈
        midweek = snow.Status(2026, {"서울": d(2026, 12, 1)})
        snow.fetch_status = lambda today, **_: midweek
        clear_week = [SimpleNamespace(date=d(2026, 12, 3), sky="맑음")]
        assert themes.snow_block(weekly_ctx(week, d(2026, 12, 2), days=clear_week)) is not None
        snow.fetch_status = lambda today, **_: status
        # 서울 관측 다다음 주 — 새 관측은 없지만 아직인 곳에 눈 예보가 있으면 계속, 눈 예보도 없으면 해당 없음
        later = weekly_ctx(d(2026, 12, 7), week, days=days)
        assert "첫눈이 될 수 있음" in themes.snow_block(later).paragraph.to_slack()
        clear = [SimpleNamespace(date=d(2026, 12, 8), sky="맑음")]
        assert themes.snow_block(weekly_ctx(d(2026, 12, 7), week, days=clear)) is None
        snow_map.render_png = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Chromium 없음"))
        block = themes.snow_block(weekly_ctx(week, days=days))
        assert block.attachment is None and block.credit.startswith("첫눈 · ")
        snow.fetch_status = lambda today, **_: (_ for _ in ()).throw(snow.SnowError("점검"))
        try:
            themes.snow_block(weekly_ctx(week, days=days))
            raise AssertionError("첫눈 수집 실패가 묻혔습니다")
        except snow.SnowError:
            pass
    finally:
        snow.fetch_status, snow_map.render_png = orig
    print("[ok] 첫눈 주간 게시 — 새 소식이 있을 때만(기간 없음), 날씨 예보로 «이번 주», 지도 실패에도 글")


def test_snow_mention() -> None:
    """첫눈 멘션 — 전국 현황(지도), 지점·지역, 날씨 질문은 날씨로, 지역 답 한 줄."""
    import src.mention.answer as answer_mod
    import src.mention.forecast as forecast
    from src.common.cache import clear
    from src.kma.page import Narrative, Scrape, ScrapedDay, ScrapeError
    from src.kma.regions import NATIONWIDE
    from src.mention.snow.note import _snow_note
    from src.season.snow import data as snow
    from src.season.snow import map as snow_map

    d = dt.date
    now = dt.datetime(2026, 11, 25, 9, 0, tzinfo=KST)
    today = now.date()
    status = snow.Status(2026, {}, {"서울": d(2025, 12, 4), "부산": d(2026, 2, 7)})

    def fake_scrape(_now, start, span, region):
        days = {start + dt.timedelta(days=i): ScrapedDay(start + dt.timedelta(days=i), 0.0, 2.0, 5.0, 8.0,
                                                         "흐리고 눈" if i == 2 else "맑음", 60, "중기예보")
                for i in range(span)}
        return Scrape(days=days, narratives=[Narrative("중기예보", "", None, [])])

    orig = (snow.fetch_status, forecast.scrape_range, snow_map.render_png, answer_mod.find_wide,
            *_quiet_season_notes())      # 날씨 답의 단풍 한 줄이 기상청을 부르지 않게
    snow.fetch_status = lambda day: status
    forecast.scrape_range = fake_scrape
    snow_map.render_png = lambda *a, **k: b"PNG"
    answer_mod.find_wide = lambda q: None
    try:
        clear()
        overview = answer_mod.answer("<@U1> 첫눈 언제 와?", now)
        assert overview.text.startswith("*첫눈 현황* (11/25 기준 · 2026~27년 겨울)"), overview.text
        assert overview.image == b"PNG" and "*서울* 아직 (평년 11/20, 지난겨울 12/4)" in overview.text
        assert (overview.slug, overview.title) == ("snow", "첫눈 지도")
        assert "• 앞으로 7일 — 11/27(" in overview.text, overview.text

        busan = answer_mod.answer("<@U1> 부산 첫눈 왔어?", now)
        assert busan.text.startswith("*부산 첫눈*") and busan.image is None, busan.text
        assert "• *부산* 아직 (평년 12/23, 지난겨울 2/7)" in busan.text, busan.text
        assert "눈 예보 (첫눈이 될 수 있음)" in busan.text, busan.text
        gangwon = answer_mod.answer("<@U1> 강원 첫눈", now).text
        assert gangwon.startswith("*강원 첫눈*") and all(n in gangwon for n in ("속초", "북춘천", "북강릉"))

        weather = answer_mod.answer("<@U1> 첫눈 온다는 서울 날씨", now).text
        assert "첫눈 현황" not in weather and "*첫눈* —" in weather, weather   # 날씨 답 + 첫눈 한 줄

        snow.fetch_status = lambda day: (_ for _ in ()).throw(snow.SnowError("점검"))
        assert "가져오지 못했습니다" in answer_mod.answer("<@U1> 첫눈", now).text
        snow.fetch_status = lambda day: status
        # 예보를 못 받으면 «눈 소식이 없다» 고 단정하지 않음
        clear()
        forecast.scrape_range = lambda *a: (_ for _ in ()).throw(ScrapeError("점검"))
        assert "• 앞으로 7일 — 예보를 받지 못했습니다" in answer_mod.answer("<@U1> 첫눈", now).text
        forecast.scrape_range = fake_scrape

        seoul = "1168064000"                                          # 역삼동 — 서울 지점
        snowy = [(d(2026, 11, 27), "흐리고 눈")]
        (_, line, _) = _snow_note(seoul, snowy, today)
        assert line.startswith(":snowflake: *첫눈* — *서울* 아직 (평년 11/20, 지난겨울 12/4) — 11/27("), line
        assert _snow_note(seoul, [(d(2026, 11, 27), "맑음")], today) == []        # 말할 것이 없음
        assert _snow_note(seoul, snowy, d(2026, 11, 28)) == []                   # 지난 눈 예보는 소식이 아님 (기간 없음)
        status.first["서울"] = d(2026, 11, 24)
        (_, line, _) = _snow_note(seoul, [], today)
        assert line == ":snowflake: *첫눈* — *서울* 11/24 (평년보다 4일 늦음)", line
        assert _snow_note(seoul, [], d(2026, 12, 2)) == []                       # 7일 지나면 그만
        (_, line, _) = _snow_note(NATIONWIDE, snowy, today)
        assert "*서울* 11/24" in line and "나머지 23곳은 아직" in line, line
    finally:
        _restore_season_notes(orig[4:])
        snow.fetch_status, forecast.scrape_range, snow_map.render_png, answer_mod.find_wide = orig[:4]
        clear()
    print("[ok] 첫눈 멘션 — 전국 현황·지도, 지점·지역, 날씨 질문은 날씨로, 지역 답 한 줄")


def test_snow_render() -> None:
    from types import SimpleNamespace

    from src.season.snow.data import Status
    from src.season.snow.map import build_html

    d = dt.date
    status = Status(2026, {"서울": d(2026, 11, 26)}, {"서울": d(2025, 12, 4)})
    days = [SimpleNamespace(date=d(2026, 12, 1), sky="흐리고 비/눈"),
            SimpleNamespace(date=d(2026, 12, 9), sky="눈")]           # 머리의 기간 밖 — 빠져야 함
    html_text = build_html(status, d(2026, 11, 30), days)
    assert "12/9" not in html_text, "지도 기간 밖의 눈 예보가 실렸습니다"
    assert "예보를 받지 못했습니다" in build_html(status, d(2026, 11, 30), None)
    assert html_text.count('<tr><th scope="row">') == 24
    assert '<span class="obs">11/26</span> <span class="gap">+6일</span>' in html_text
    assert "<b>서울</b> 11/26 (평년보다 6일 늦음)" in html_text and "눈 예보" in html_text
    assert "2026~27년 겨울" in html_text and html_text.count("울릉도") == 2   # 표 한 줄 + 상자 이름(점 라벨 없음)
    from src.season.blossom.map import INFO as BLOSSOM_MAP
    from src.season.foliage.map import INFO as FOLIAGE_MAP
    from src.season.snow.map import INFO as SNOW_MAP
    from src.season.typhoon.map import INFO as TYPHOON_MAP
    cleanup = (pathlib.Path(__file__).resolve().parents[1] / "bin" / "cleanup.py").read_text(encoding="utf-8")
    assert all(f'"{m.slug}-*.png"' in cleanup for m in (FOLIAGE_MAP, SNOW_MAP, BLOSSOM_MAP, TYPHOON_MAP)), \
        "정리 패턴이 지도 이름과 다릅니다"
    print("[ok] 첫눈 지도 — 24곳 표 · 관측일·평년차 · 눈 예보")


SUMMER_WEEK = dt.date(2027, 7, 19)


def summer_day(i: int, tmin: tuple, tmax: tuple, sky: str = "구름많음", pop: int | None = None) -> DayForecast:
    return DayForecast(SUMMER_WEEK + dt.timedelta(days=i), *tmin, *tmax, sky=sky, pop=pop)


def summer_notes(*lines: str) -> list[Narrative]:
    return [Narrative("기상청 예보 통보문", "", None, list(lines))]


def test_narrative_quote() -> None:
    """예보관 인용 — 짧으면 원문 그대로, 길면 낱말 경계에서 자르고 «…» (말을 보태지 않음)."""
    from src.season import narrative

    assert narrative.quote("(내일) 흐리고 비") == '"(내일) 흐리고 비"'
    long = "(오늘, 16일) 전국 구름많겠으나, " + "강원동해안.산지와 경북동해안.북동산지 곳에 따라 비, " * 6
    quoted = narrative.quote(long)
    assert quoted.endswith('…"') and len(quoted) <= narrative.QUOTE_CHARS + 3, quoted
    assert long.startswith(quoted[1:-2]), "앞부분이 원문과 다릅니다"
    assert not quoted[1:-2].endswith((",", " ")), quoted
    print("[ok] 예보관 인용 — 짧으면 그대로, 길면 낱말 경계에서 자르고 «…»")


def test_heat_weekly() -> None:
    """폭염·열대야 — 기상청 기준(낮 최고 33℃↑ · 아침 최저 25℃↑)의 경계, 예보관 인용, 선선하면 해당 없음."""
    from src.weekly import themes

    days = [summer_day(0, (22, 24.9), (28, 32.9)),          # 둘 다 경계 바로 아래 — 빠짐
            summer_day(1, (23, 25), (29, 33)),              # 경계값은 듦
            summer_day(2, (24, 27), (30, 36)),
            DayForecast(SUMMER_WEEK + dt.timedelta(days=3)),  # 예보 없는 날
            *(summer_day(i, (20, 23), (27, 31)) for i in range(4, 7))]
    block = themes.heat_block(weekly_ctx(SUMMER_WEEK, days=days))
    rows = {r.label: r.text for r in block.paragraph.rows}
    assert block.paragraph.title == "이번 주 더위" and block.paragraph.emoji == ":hot_face:"
    assert list(rows) == ["폭염 기준(33℃↑)", "열대야 기준(25℃↑)"], list(rows)
    assert rows["폭염 기준(33℃↑)"] == "*7/20(화)~7/21(수)* 2일 · 최고 36℃ 7/21(수) (일부 지역 낮 최고)", rows
    assert rows["열대야 기준(25℃↑)"] == "*7/20(화)~7/21(수)* 2일 · 최고 27℃ 7/21(수) (일부 지역 아침 최저)", rows
    # 도시별 값(중기예보)이 없는 주는 지도 없이 글만
    assert block.credit.startswith("더위 · 기상청") and block.attachment is None

    # 날짜는 이어진 구간으로 줄이고 날마다의 값은 늘어놓지 않음 — 최고값이 같으면 이른 날
    from src.season.heat.text import span_text
    d = dt.date
    assert span_text([(d(2027, 7, 21), 36.0)]) == "*7/21(수)* 36℃"
    assert span_text([(d(2027, 7, 19), 34.0), (d(2027, 7, 21), 36.0), (d(2027, 7, 22), 36.0),
                      (d(2027, 7, 25), 33.0)]) == "*7/19(월)* · *7/21(수)~7/22(목)* · *7/25(일)* 4일 · 최고 36℃ 7/21(수)"

    # 예보관 서술은 글머리만 떼고 그대로, 본문이 이미 인용한 (종합) 줄은 되풀이하지 않음, 둘까지
    notes = summer_notes("□ (종합) 무더위 계속, 일부 지역 폭염특보 발효 중",
                         "○ (모레, 21일) 낮 기온 35℃ 이상 오르는 곳 있어 폭염특보 확대 가능성",
                         "○ (기온) 도심과 해안 중심 열대야 나타나는 곳 있겠습니다.",
                         "○ (글피, 22일) 폭염 이어지겠음")
    body = '기상청은 "*무더위 계속, 일부 지역 폭염특보 발효 중*"이라고 전하고 있습니다.'
    quoted = [r.text for r in themes.heat_block(weekly_ctx(SUMMER_WEEK, days=days, narratives=notes,
                                                             body=body)).paragraph.rows if r.label == "예보관"]
    assert quoted == ['"(모레, 21일) 낮 기온 35℃ 이상 오르는 곳 있어 폭염특보 확대 가능성"',
                      '"(기온) 도심과 해안 중심 열대야 나타나는 곳 있겠습니다."'], quoted

    cool = [summer_day(i, (20, 24), (26, 32)) for i in range(7)]
    assert themes.heat_block(weekly_ctx(SUMMER_WEEK, days=cool, narratives=summer_notes("○ (내일) 흐리고 비"))) is None
    # 수치가 기준에 못 미쳐도 예보관이 말했으면 그 인용만
    only = themes.heat_block(weekly_ctx(SUMMER_WEEK, days=cool, narratives=summer_notes("○ (내일) 열대야 나타나겠음")))
    assert [r.label for r in only.paragraph.rows] == ["예보관"], only.paragraph.rows
    assert themes.heat_block(weekly_ctx(SUMMER_WEEK)) is None          # 날씨 결과 없이 부르면 해당 없음
    print("[ok] 폭염·열대야 — 33℃·25℃ 경계, 일부 지역, 예보관 인용(본문과 안 겹치게), 선선하면 해당 없음")


def test_monsoon_weekly() -> None:
    """장마 — 예보관이 장마·정체전선을 말할 때만, 비 오는 날은 하늘상태·강수확률에서. 정체전선만이면 장마라 부르지 않음."""
    from src.weekly import themes

    days = [summer_day(0, (22, 25), (27, 31), sky="흐리고 비"),
            summer_day(1, (22, 25), (27, 31), sky="흐리고 소나기"),
            summer_day(2, (22, 25), (27, 31), sky="흐림"),
            summer_day(3, (22, 25), (27, 31), sky="구름많음", pop=70),     # 하늘상태에 비가 없어도 강수확률로
            summer_day(4, (22, 25), (27, 31), sky="구름많음", pop=30),
            summer_day(5, (22, 25), (27, 31), sky="맑음", pop=59),
            summer_day(6, (22, 25), (27, 31), sky="흐리고 비", pop=60)]
    notes = summer_notes("□ (종합) 제주도 장마 시작, 남부지방 많은 비",
                         "○ (내일, 20일) 정체전선의 영향으로 남부지방과 제주도에 비",
                         "○ (기온) 평년과 비슷")
    block = themes.monsoon_block(weekly_ctx(SUMMER_WEEK, days=days, narratives=notes))
    text = block.paragraph.to_slack()
    assert block.paragraph.title == "이번 주 장마", block.paragraph.title
    assert [r.label for r in block.paragraph.rows] == ["예보관", "예보관", "비 예보"], text
    assert '"(종합) 제주도 장마 시작, 남부지방 많은 비"' in text and "평년과 비슷" not in text, text
    assert block.paragraph.rows[-1].text == "*7/19(월)* · *7/20(화)* · *7/22(목)* · *7/25(일)*", text
    assert "철이 끝난 뒤 확정" in block.credit and block.attachment is None
    # 수집 순서는 중기예보가 앞이지만 인용은 통보문(가까운 날)부터 — 둘을 넘는 중기예보 줄이 잘림
    mid = Narrative("기상청 중기예보", "", None, ["○ (강수) 23일(금)은 장마전선의 영향으로 중부지방에 비"])
    rows = themes.monsoon_block(weekly_ctx(SUMMER_WEEK, days=days, narratives=[mid, *notes])).paragraph.rows
    assert "23일(금)" not in " ".join(r.text for r in rows) and rows[0].text.startswith('"(종합)'), rows

    front = summer_notes("○ (내일, 20일) 정체전선의 영향으로 남부지방에 비")
    assert themes.monsoon_block(weekly_ctx(SUMMER_WEEK, days=days, narratives=front)).paragraph.title == \
        "이번 주 정체전선"
    dry = [summer_day(i, (22, 25), (27, 31), sky="맑음") for i in range(7)]
    rows = themes.monsoon_block(weekly_ctx(SUMMER_WEEK, days=dry, narratives=front)).paragraph.rows
    assert [r.label for r in rows] == ["예보관"], rows                   # 비 없는 주는 «비 예보» 줄을 뺌
    # 비가 잦아도 예보관이 장마·정체전선을 말하지 않으면 해당 없음 — 기간을 정하지 않음
    assert themes.monsoon_block(weekly_ctx(SUMMER_WEEK, days=days, narratives=summer_notes("○ (내일) 비"))) is None
    print("[ok] 장마 — 예보관 서술 인용 + 비 오는 날, 정체전선만이면 «정체전선», 언급 없으면 해당 없음")


MID_TEMP_HTML = """<table><caption>최대 10일 후 까지의 육상예보 최저/최고기온(℃)</caption>
<thead><tr><th colspan="2">지역</th><th>23일 (금)</th><th>24일 (토)</th><th>기온범위</th></tr></thead><tbody>
<tr><td rowspan="2">서울 인천 경기도</td><td>서울</td><td>25 / 34</td><td>26 / 35</td><td>그래프</td></tr>
<tr><td>인천</td><td>24 / 31</td><td>25 / 32</td><td>그래프</td></tr>
<tr><td rowspan="1">강원도 영동</td><td>강릉</td><td>27 / 36</td><td>28 / 37</td><td>그래프</td></tr>
</tbody></table>"""


def test_heat_city_parse() -> None:
    """중기예보 도시 표 — 전국 범위는 그대로, 도시별 값도 남김(구역 행만). 범위 밖 값이 든 도시는 그 도시만 뺌."""
    from bs4 import BeautifulSoup

    from src.kma import mid_term
    from src.kma.regions import NATIONWIDE, find_region
    from src.weekly.forecast import _day

    tbl = BeautifulSoup(MID_TEMP_HTML, "lxml").select_one("table")
    fri, sat = dt.date(2027, 7, 23), dt.date(2027, 7, 24)
    days = mid_term._temperatures(tbl, SUMMER_WEEK, NATIONWIDE)
    assert (days[fri].tmin_lo, days[fri].tmin_hi, days[fri].tmax_lo, days[fri].tmax_hi) == (24, 27, 31, 36)
    assert days[fri].cities == {"서울": (25, 34), "인천": (24, 31), "강릉": (27, 36)}, days[fri].cities
    assert days[sat].cities["강릉"] == (28, 37) and days[sat].source == "중기예보"
    yeongdong = mid_term._temperatures(tbl, SUMMER_WEEK, find_region("영동"))
    assert yeongdong[fri].cities == {"강릉": (27, 36)} and yeongdong[fri].tmax_lo == 36
    raw = ScrapedDay(fri, 24, 27, 31, 36, source="중기예보", cities={"서울": (25, 34), "깨짐": (25, 99)})
    assert _day(fri, raw, []).cities == {"서울": (25, 34)}
    assert ScrapedDay(fri).cities == {} and DayForecast(fri).cities == {}     # 통보문 날은 비어 있음
    print("[ok] 더위 도시값 — 중기예보 도시 표를 범위와 함께 도시별로, 구역 행만, 이상한 도시만 뺌")


def heat_week(cities: dict[str, tuple[float, float]]) -> list[DayForecast]:
    """월~목 통보문(범위만), 금~일 중기예보(도시별) — 토요일이 1도 더 높음."""
    days = [summer_day(i, (22, 26), (29, 35)) for i in range(4)]
    for i, bump in ((4, 0), (5, 1), (6, 0)):
        got = {k: (lo + bump, hi + bump) for k, (lo, hi) in cities.items()}
        lows, highs = [v[0] for v in got.values()], [v[1] for v in got.values()]
        days.append(DayForecast(SUMMER_WEEK + dt.timedelta(days=i), min(lows), max(lows), min(highs), max(highs),
                                "구름많음", 30, "중기예보", got))
    return days


def test_heat_map() -> None:
    """더위 지도 — 🥵 는 낮 최고 33℃↑, 나머지는 회색 빈 원, 라벨은 겹치지 않는 것만, 표는 기준에 닿는 도시 20곳까지."""
    import re

    from src.season.basemap import hits, place, text_box
    from src.season.heat import data as heat
    from src.season.heat import map as heat_map
    from src.season.heat.cities import SPOTS
    from src.season.mapcard import glyph_size
    from src.weekly import themes

    cities = {"대구": (25.0, 36.0), "서울": (24.0, 32.0), "강릉": (23.0, 31.0), "새도시": (20.0, 34.0)}
    found = heat.read(heat_week(cities), [])
    by = {c.name: c for c in found.cities}
    assert by["대구"].high == (dt.date(2027, 7, 24), 37.0) and by["대구"].low == (dt.date(2027, 7, 24), 26.0)
    assert by["서울"].hot and by["서울"].tropical and not (by["강릉"].hot or by["강릉"].tropical)   # 33·25 경계
    assert found.city_days == [dt.date(2027, 7, 23), dt.date(2027, 7, 24), dt.date(2027, 7, 25)]
    html_text = heat_map.build_html(found, SUMMER_WEEK)
    assert "도시별 예보 7/23(금)~7/25(일)" in html_text      # 지도는 도시별 값이 있는 날만
    assert html_text.count('viewBox="0 0 128 128"') == 1 + 2        # 범례 + 대구·서울 (새도시는 좌표가 없어 표에만)
    assert html_text.count('fill="#fcfcfb" stroke="#898781"') == 1 + 1     # 범례 + 강릉
    assert html_text.count('<tr><th scope="row">') == 3 and "새도시" in html_text     # 기준 미만 강릉은 표에 없음
    assert '<td class="met">37 <small>토</small></td>' in html_text and "일 최고기온이 33℃ 이상인 날" in html_text

    # 41곳이 모두 더워도 라벨끼리·남의 표지와 겹치지 않음 — 못 붙인 곳은 라벨 없이
    hot_all = heat.read(heat_week({name: (26.0, 36.0) for name in SPOTS}), [])
    marks = heat_map._marks(hot_all)
    labels = re.findall(r'<text class="lbl[^"]*" x="([\d.-]+)" y="([\d.-]+)" text-anchor="(\w+)">([^<]+)</text>', marks)
    shift = {"start": 0.0, "middle": 0.5, "end": 1.0}
    boxes = [(text_box(float(x), float(y), t, shift[a], heat_map.LABEL_PX), t.split()[0]) for x, y, a, t in labels]
    assert len(boxes) >= 25, len(boxes)
    half = glyph_size(heat_map.HOT_R) / 2
    for i, (box, owner) in enumerate(boxes):
        assert not any(hits(box, other) for other, _ in boxes[i + 1:]), (box, owner)
        for name, spot in SPOTS.items():
            px, py = place(spot.lon, spot.lat)
            assert name == owner or not hits(box, (px - half, py - half, px + half, py + half)), (owner, name)
    rows = heat_map._table(hot_all)
    assert rows.count('<tr><th scope="row">') == heat_map.MAX_ROWS and f"외 {len(SPOTS) - heat_map.MAX_ROWS}곳" in rows

    # 주간 게시: 도시별 값이 있으면 지도, 못 그리면 글만(출처의 «지도» 도 뺌), Chromium 이 없으면 그리지 않음
    orig, drawn = heat_map.render_png, []
    heat_map.render_png = lambda h, start, scale=2: drawn.append(start) or b"PNG"
    try:
        block = themes.heat_block(weekly_ctx(SUMMER_WEEK, days=heat_week(cities)))
        assert block.attachment.filename == "heat-20270719.png" and block.credit.startswith("더위 지도 · ")
        assert block.attachment.pattern == "heat-*.png" and drawn == [SUMMER_WEEK]
        heat_map.render_png = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Chromium 없음"))
        block = themes.heat_block(weekly_ctx(SUMMER_WEEK, days=heat_week(cities)))
        assert block.attachment is None and block.credit.startswith("더위 · ") and block.paragraph.rows
        drawn.clear()
        heat_map.render_png = lambda h, start, scale=2: drawn.append(start) or b"PNG"
        block = themes.heat_block(weekly_ctx(SUMMER_WEEK, can_render=False, days=heat_week(cities)))
        assert block.attachment is None and not drawn
    finally:
        heat_map.render_png = orig
    cleanup = (pathlib.Path(__file__).resolve().parents[1] / "bin" / "cleanup.py").read_text(encoding="utf-8")
    assert f'"{heat_map.INFO.slug}-*.png"' in cleanup, "정리 패턴이 더위 지도 이름과 다릅니다"
    print("[ok] 더위 지도 — 🥵·빈 원, 겹치지 않는 라벨, 표 20곳, 지도 실패·Chromium 없음엔 글만")


# 날씨누리 typhoonContent.js 주석에 실린 2019년 제2호 우딥 경로표 그대로 — 뒤에 붙는 빈 줄까지
WUTIP_OSP = """2019,2,우딥,WUTIP
201902190900,4.8,160.6,괌 동남동쪽 약 1980 km 부근 해상,W,41,1004,15,TD,0,,0,0,,0,0,2019,1,TD
201902191500,5.0,158.6,괌 동남동쪽 약 1780 km 부근 해상,W,37,1004,15,TD,0,,0,0,,0,0,2019,1,TD
201902192100,5.1,156.2,괌 남동쪽 약 1560 km 부근 해상,W,44,1002,15,TD,0,,0,0,,0,0,2019,1,TD
201902200300,5.1,155.2,괌 남동쪽 약 1470 km 부근 해상,W,18,1000,18,TS,,,,250,SW,200,0,,,
201902200900,4.8,154.7,괌 남동쪽 약 1450 km 부근 해상,WSW,11,996,20,TS,,,,250,SW,200,0,,,
201902201500,4.9,153.8,괌 남동쪽 약 1370 km 부근 해상,W,17,990,24,TS,,,,280,SW,230,0,,,
201902211500,6.5,150.0,괌 남동쪽 약 960 km 부근 해상,WNW,19,975,32,0,0,0,0,300,SW,250,110,,,
201902221500,8.9,146.0,괌 남남동쪽 약 520 km 부근 해상,WNW,22,960,39,0,0,0,0,330,SW,280,170,,,
201902231500,11.2,142.9,괌 남서쪽 약 330 km 부근 해상,NW,18,955,40,0,0,0,0,350,SW,300,260,,,
201902241500,12.9,141.2,괌 서쪽 약 390 km 부근 해상,NW,11,950,43,0,0,0,0,370,SW,320,370,,,
201902251500,14.6,140.0,괌 서북서쪽 약 530 km 부근 해상,NW,9,955,40,0,0,0,0,350,WSW,300,480,,,
,,,,,,,0,,0,0,0,0,,,,,,
,,,,,,,0,,0,0,0,0,,,,,,
,,,,,,,0,,0,0,0,0,,,,,,
,,,,,,,0,,0,0,0,0,,,,,,
,,,,,,,0,,0,0,0,0,,,,,,
"""
WUTIP_URL = "/repositary/xml/typ/raw/DAOU/RTKO63/2019/RTKO63_201902201600_2_3.osp?ver=20190220173301"


def test_typhoon_parse() -> None:
    """태풍정보 — 빈 목록은 «없음», 경로표의 현재·예상 구분, 약화, 형식이 바뀌면 TyphoonError."""
    from src.common.cache import clear
    from src.kma import typhoon
    from src.kma.typhoon import TyphoonError, parse_list, parse_track

    def rejects(parse, text: str) -> None:
        try:
            parse(text)
        except TyphoonError:
            return
        raise AssertionError(f"형식 변경을 못 알아챘습니다: {text[:40]!r}")

    at = dt.datetime
    assert parse_list("") == [] and parse_list("\n \n") == []          # 진행 중인 태풍 없음 — 200, 0바이트
    listing = f"{WUTIP_URL},{WUTIP_URL.replace('.osp', '.ini')}\n"
    (url,) = parse_list(listing)
    assert url == "https://www.weather.go.kr/w" + WUTIP_URL, url
    rejects(parse_list, "<!DOCTYPE html><html>오류</html>")            # 없는 경로도 200 + HTML
    rejects(parse_list, "RTKO63_2019.txt,RTKO63_2019.ini")

    storm = parse_track(WUTIP_OSP, typhoon.issued_of(url))
    assert storm.title == "제2호 태풍 우딥(WUTIP)" and storm.weakened == ""
    assert storm.issued == at(2019, 2, 20, 16, 0, tzinfo=KST)
    assert storm.now.at == at(2019, 2, 20, 15, 0, tzinfo=KST) and storm.now.when == "2/20(수) 15시"
    assert storm.now.summary == "괌 남동쪽 약 1370 km 부근 해상 · 중심기압 990hPa · 최대풍속 24m/s"
    assert [p.at.day for p in storm.forecast] == [21, 22, 23, 24, 25]
    assert storm.forecast[-1].place == "괌 서북서쪽 약 530 km 부근 해상"
    # 지도에 쓰는 값 — 좌표, 예상 위치의 70% 확률반경, 현재 위치의 강풍반경(예외 방위·반경 포함), 빈 폭풍반경은 없음
    assert (storm.now.lat, storm.now.lon, storm.now.radius) == (4.9, 153.8, None)
    assert [p.radius for p in storm.forecast] == [110, 170, 260, 370, 480]
    assert storm.now.gale.text == "280km(남서쪽 230km)" and storm.now.storm is None
    assert [p.at.hour for p in storm.past] == [9, 15, 21, 3, 9] and storm.past[0].gale is None   # TD 줄은 반경 0
    # 같은 시각이 두 줄이면 뒤의 것
    current = "201902201500,4.9,153.8,괌 남동쪽 약 1370 km 부근 해상,W,17,990,24,TS,,,,280,SW,230,0,,,"
    fixed = current.replace(",990,24,", ",992,23,")
    assert parse_track(WUTIP_OSP.replace(current, f"{current}\n{fixed}")).now.pressure == 992
    # 약화 — 날씨누리 지도의 문구 그대로, 예상이 없으면 빈 진로
    weakened = WUTIP_OSP.split("\n201902211500")[0] + \
        "\n201902260900,16.0,139.0,괌 서북서쪽 약 700 km 부근 해상,NW,15,1004,15,TD,,,,0,,0,0,,,TD-END\n"
    storm = parse_track(weakened)
    assert storm.weakened == "열대저압부로 약화" and storm.forecast == () and storm.now.wind == 15
    assert storm.issued is None and typhoon.issued_of("RTKO63_201913991600_2_3.osp") is None

    head, rows = WUTIP_OSP.split("\n", 1)
    rejects(parse_track, "")
    rejects(parse_track, "<html><body>오류</body></html>")
    rejects(parse_track, "우딥,WUTIP\n" + rows)                          # 머리가 바뀜
    rejects(parse_track, head + "\n" + rows.replace("201902201500", "2019-02-20 15:00"))
    forecast_only = "\n".join(line for line in rows.splitlines() if line.startswith("2019022") and
                              line > "201902210000")
    rejects(parse_track, f"{head}\n{forecast_only}")                     # 현재 위치가 없음
    assert typhoon._decode("2019,2,우딥".encode("cp949")) == "2019,2,우딥"
    assert typhoon._decode("﻿2019,2,우딥".encode()) == "2019,2,우딥"

    calls: list[str] = []
    orig = typhoon._get
    typhoon._get = lambda u, timeout: calls.append(u) or (listing if u == typhoon.LIST_URL else WUTIP_OSP)
    clear()
    try:
        assert [s.no for s in typhoon.fetch_active()] == [2] and calls == [typhoon.LIST_URL, url], calls
        typhoon.fetch_active()
        assert len(calls) == 2, calls                                     # 캐시
        clear()
        typhoon._get = lambda u, timeout: ""
        assert typhoon.fetch_active() == []
        clear()
        typhoon._get = lambda u, timeout: (_ for _ in ()).throw(TyphoonError("요청 실패"))
        rejects(lambda _: typhoon.fetch_active(), "")
    finally:
        typhoon._get = orig
        clear()
    print("[ok] 태풍정보 — 빈 목록은 없음, 현재·예상 구분, 같은 시각은 뒤의 것, 약화 문구, 형식 변경은 TyphoonError")


def test_typhoon_weekly() -> None:
    """주간 게시의 태풍 덩어리 — 진행 중일 때만 글로, 태풍정보를 못 받으면 예보관 서술만, 둘 다 없으면 실패."""
    from dataclasses import replace

    from src.kma import typhoon
    from src.kma.typhoon import TyphoonError, parse_track
    from src.season.typhoon import map as typhoon_map
    from src.weekly import pipeline, themes

    week = dt.date(2019, 2, 18)
    days = [DayForecast(date=week)]
    storm = parse_track(WUTIP_OSP, typhoon.issued_of(WUTIP_URL))
    headline = "□ (종합) 제2호 태풍 우딥 북상, 주 후반 남해안 너울 유의"
    notice = Narrative("기상청 예보 통보문", "https://www.weather.go.kr/w/forecast/notice.do", None,
                       [headline, "○ (내일, 19일) 대체로 맑음"])
    mid = Narrative("기상청 중기예보", "https://www.weather.go.kr/w/forecast/overall/mid-term.do", None,
                    ["○ (해상) 제2호 태풍 우딥의 영향으로 24일 남해상 물결 매우 높겠음", headline])

    def labels(block) -> list[str]:
        return [r.label for r in block.paragraph.rows]

    drawn: list = []
    fail_render = [False]

    def fake_render(storms, week_start, scale=2):
        drawn.append([s.no for s in storms])
        if fail_render[0]:
            raise RuntimeError("Chromium 없음")
        return b"PNG"

    orig = (typhoon.fetch_active, typhoon_map.render_png)
    typhoon_map.render_png = fake_render
    try:
        assert [s.name for s in pipeline.SECTIONS] == ["카드", "일기도", "벚꽃", "장마", "폭염", "태풍", "단풍", "첫눈"]
        # 기상청 목록이 비면 해당 없음 — 서술의 «태풍» 은 발생 가능성만 말하는 줄일 수 있음
        typhoon.fetch_active = lambda: []
        assert themes.typhoon_block(weekly_ctx(week, days=days, narratives=[notice])) is None

        typhoon.fetch_active = lambda: [storm]
        block = themes.typhoon_block(weekly_ctx(week, days=days, narratives=[mid, notice]))
        rows = block.paragraph.rows
        assert block.paragraph.title == "이번 주 태풍" and block.paragraph.emoji == ":cyclone:"
        assert labels(block) == ["현재", "예상", "이번 주"] and drawn == [[2]]
        assert block.attachment.filename == "typhoon-20190218.png" and block.attachment.title == "태풍 예상 경로 지도"
        assert block.attachment.pattern == "typhoon-*.png"
        assert rows[0].text == ("*제2호 태풍 우딥(WUTIP)* · 괌 남동쪽 약 1370 km 부근 해상 · 중심기압 990hPa · "
                                "최대풍속 24m/s (2/20(수) 15시 기준)"), rows[0].text
        assert rows[1].text == "2/24(일) 15시 괌 서쪽 약 390 km 부근 해상", rows[1].text   # 2/25(월) 은 다음 주
        # 통보문(가까운 날)이 먼저, 같은 줄은 한 번, 원문 그대로
        assert rows[2].text == ('"(종합) 제2호 태풍 우딥 북상, 주 후반 남해안 너울 유의" / '
                                '"(해상) 제2호 태풍 우딥의 영향으로 24일 남해상 물결 매우 높겠음"'), rows[2].text
        assert block.credit == "태풍 예상 경로 지도 · 기상청 태풍정보(2/20 16시 발표) · 기상청 예보 통보문 · 기상청 중기예보", \
            block.credit
        # 지도를 못 그려도 글은 남고 출처의 «예상 경로 지도» 가 빠짐, Chromium 이 없으면 그리지도 않음
        fail_render[0] = True
        block = themes.typhoon_block(weekly_ctx(week, days=days, narratives=[mid, notice]))
        assert block.attachment is None and block.credit.startswith("태풍 · 기상청 태풍정보") and block.paragraph.rows
        fail_render[0] = False
        drawn.clear()
        block = themes.typhoon_block(weekly_ctx(week, days=days, narratives=[notice], can_render=False))
        assert block.attachment is None and not drawn and block.credit.startswith("태풍 · ")
        # 예보관이 태풍을 말하지 않으면 멀리 있는 태풍은 싣지 않음(사용자 결정) — 태풍정보도 받지 않음
        asked: list = []
        typhoon.fetch_active = lambda: asked.append(1) or [storm]
        assert themes.typhoon_block(weekly_ctx(week, days=days)) is None and not asked
        # 본문이 이미 인용한 줄은 «이번 주» 에서 빼되, 태풍 사실(현재·예상)은 실음
        quoted_body = '기상청은 "*제2호 태풍 우딥 북상, 주 후반 남해안 너울 유의*"이라고 전하고 있습니다.'
        block = themes.typhoon_block(weekly_ctx(week, days=days, narratives=[notice], body=quoted_body))
        assert labels(block) == ["현재", "예상"] and block.credit == "태풍 예상 경로 지도 · 기상청 태풍정보(2/20 16시 발표)"
        # 둘이면 «예상» 에 이름을 붙임
        typhoon.fetch_active = lambda: [storm, replace(storm, no=3, name="세파트", en_name="SEPAT")]
        block = themes.typhoon_block(weekly_ctx(week, days=days, narratives=[notice]))
        assert labels(block) == ["현재", "예상"] * 2 + ["이번 주"], labels(block)
        assert block.paragraph.rows[3].text.startswith("세파트 2/24(일)")
        assert drawn[-1] == [2, 3]                                   # 태풍이 여럿이어도 지도는 한 장
        # 태풍정보를 못 받으면 예보관 서술만 — 위험 신호를 영역 실패로 묻지 않음
        typhoon.fetch_active = lambda: (_ for _ in ()).throw(TyphoonError("점검"))
        drawn.clear()
        block = themes.typhoon_block(weekly_ctx(week, days=days, narratives=[notice]))
        assert labels(block) == ["이번 주"] and block.credit == "태풍 · 기상청 예보 통보문", block.credit
        assert block.attachment is None and not drawn                # 그릴 경로가 없음
        assert themes.typhoon_block(weekly_ctx(week, days=days)) is None    # 서술에도 없으면 해당 없음
    finally:
        typhoon.fetch_active, typhoon_map.render_png = orig
    print("[ok] 태풍 주간 게시 — 예보관이 말하고 진행 중일 때만, 이번 주 안의 예상, 본문과 안 겹치는 인용, 실패엔 서술만")


def test_typhoon_map() -> None:
    """태풍 예상 경로 지도 — 시각·중심기압 글자, 경로표에 있는 반경만 그리고 범례도 그만큼, 기압선은 일기도로."""
    from dataclasses import replace

    from src.kma import typhoon
    from src.season.typhoon import pacific
    from src.season.typhoon.map import build_html, render_png

    storm = typhoon.parse_track(WUTIP_OSP, typhoon.issued_of(WUTIP_URL))
    week = dt.date(2019, 2, 18)
    html_text = build_html([storm], week)
    assert "<h1>태풍 예상 경로</h1>" in html_text and "기상청 태풍정보 (2/20 16시 발표)" in html_text
    assert "기압선은 함께 올린 지상일기도에서 볼 수 있습니다" in html_text
    assert ">20일 15시 990hPa<" in html_text and ">제2호 우딥<" in html_text     # 현재 위치
    assert '<text class="when" x="' in html_text and ">24일 15시 950hPa<" in html_text
    assert 'class="when later"' in html_text and ">25일 15시 955hPa<" in html_text   # 다음 주 예상은 옅게
    assert "강풍반경 280km(남서쪽 230km)" in html_text                              # 머리 줄에 원문 반경
    assert "70% 확률반경 —" in html_text and "강풍반경 — 초속 15m" in html_text
    assert "폭풍반경" not in html_text and 'class="storm"' not in html_text        # 경로표가 비워 둔 반경은 없음
    assert "emoji" not in html_text and ">한국<" in html_text
    # 반경이 하나도 없으면 범례 둘째 줄도 없음
    bare = replace(storm, now=replace(storm.now, gale=None), forecast=tuple(replace(p, radius=None) for p in storm.forecast))
    bare_html = build_html([bare], week)
    assert "확률반경" not in bare_html and "강풍반경" not in bare_html and "<ellipse" not in bare_html
    # 범위는 경로·반경과 한국을 다 담고, 카드 높이 안에 맞춤
    view = pacific.fit([(160.6, 4.8), (140.0, 14.6)], 652, 560, 380)
    assert view.lon0 < 124 and view.lon1 > 160.6 and view.lat0 < 4.8 and view.lat1 > 38.8, view
    assert 380 - 1 <= view.height <= 560 + 1, view.height

    IMG.mkdir(parents=True, exist_ok=True)
    png = render_png([storm], week)
    assert png.startswith(PNG_MAGIC)
    (IMG / "typhoon-test.png").write_bytes(png)
    print(f"[ok] 태풍 지도 — 시각·중심기압 글자, 있는 반경만 그림·범례, 기압선은 일기도로 {len(png):,}B -> {IMG / 'typhoon-test.png'}")


if __name__ == "__main__":
    test_extract_json()
    test_log_dir()
    test_session_log_filter()
    test_find_region()
    test_wide_areas()
    test_find_dong()
    test_greeting()
    test_long_range_routing()
    test_topic_advice()
    test_cache_shared_across_spans()
    test_city_uses_dong_forecast()
    test_partial_week_is_declared()
    test_explicit_date()
    test_phrase_rotation()
    test_advice()
    test_resolve_date()
    test_forecast_validation()
    test_mention_parsing()
    test_card_render()
    test_message_template()
    test_weekly_body()
    test_writer_backend()
    test_mention_delivery()
    test_chart_download()
    test_footer_and_region_variation()
    test_foliage_season()
    test_foliage_parse()
    test_mountain_lookup()
    test_foliage_routing()
    test_foliage_in_weather()
    test_period_next_weekend()
    test_foliage_fetch()
    test_cache_failures()
    test_foliage_render()
    test_map_emoji()
    test_foliage_after_peak()
    test_paragraph()
    test_blossom_season()
    test_blossom_parse()
    test_blossom_text()
    test_blossom_fetch()
    test_blossom_spots()
    test_blossom_render()
    test_weekly_themes()
    test_weekly_pipeline()
    test_weekly_health()
    test_snow_data()
    test_snow_text()
    test_snow_weekly()
    test_snow_mention()
    test_snow_render()
    test_narrative_quote()
    test_heat_weekly()
    test_monsoon_weekly()
    test_heat_city_parse()
    test_heat_map()
    test_typhoon_parse()
    test_typhoon_weekly()
    test_typhoon_map()
    print("\n전부 통과")
