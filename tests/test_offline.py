"""API 키 없이 도는 검증 스크립트.

    python -m tests.test_offline

- 일기도 다운로드는 실제 기상청 서버를 호출한다(공개 URL, 인증 불필요).
- 예보 파싱·검증 / 카드 렌더링 / 본문 템플릿은 가짜 데이터로 검증한다.
- Gemini·Claude 호출은 키가 필요하므로 여기서는 건너뛴다.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_CHANNEL_ID", "C_TEST")

from src.config import KST  # noqa: E402
from src.forecast import DayForecast, WeekForecast  # noqa: E402
from src.kma_scrape import (  # noqa: E402
    Narrative, ScrapedDay, _resolve_date, find_region, resolve_region,
)
from src.kma_chart import PNG_MAGIC, fetch_latest_chart  # noqa: E402
from src.render_card import render_png  # noqa: E402
from src.mention import build_reply  # noqa: E402
from src.writer import extract_json, fallback  # noqa: E402

# 본 실행과 같은 자리에 쓴다 — .gitignore 도 보존 기간 정리도 그쪽만 본다
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
        "제주도": "제주", "강릉": "강원 영동",   # 강릉은 영동 — 더 정확한 구역으로 간다
        "부산 날씨 알려줘": "부산·울산·경남",   # 문장에서도 집어낸다
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
        # 대응하는 기상청 페이지가 없는 말은 어떻게 해석했는지 반드시 알려야 한다
        if query in ("중부", "남부", "영남", "호남", "충청"):
            assert note, f"{query}: 해석 안내문이 없습니다"
    # 영동/영서는 안내문이 필요 없다 — 실제 중기예보 구역이다
    assert resolve_region("영동")[1] == ""
    print(f"[ok] 광역 표현 {len(cases)}건 + 대체 해석 안내")


def test_find_dong() -> None:
    """동 검색 점수 규칙. 기상청 호출 없이 가짜 목록으로 확인한다."""
    import src.dong as dong_mod
    from src.dong import Dong

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
        # 접미사를 떼고 재시도해야 '역삼동' → '역삼1동' 이 걸린다
        assert [d.name for d in dong_mod.search_dong("역삼동", 2)] == ["역삼1동", "역삼2동"]
        assert dong_mod.search_dong("판교", 1)[0].name == "판교동"
        assert dong_mod.search_dong("없는동네", 1) == [], "모르는 동을 추측했습니다"
        assert dong_mod.search_dong("", 1) == []
        # 행정동코드는 검색 없이 그대로 통과
        assert dong_mod.find_dong("1168064000")[0] == "1168064000"
        print("[ok] 동 검색 — 접미사 보정, 코드 직접 입력, 미지원 동 거절")
    finally:
        dong_mod._all_dongs, dong_mod._candidate_cities = orig_all, orig_cand


def test_greeting() -> None:
    """인사·잡담은 자기소개로, 감사는 짧게. 지역이 섞이면 날씨가 우선."""
    import src.mention as mention

    calls: list = []

    def fake_scrape(now, start, span, region):
        calls.append(region.key)
        from src.kma_scrape import Scrape
        return Scrape(days={}, narratives=[])

    from src.cache import clear

    orig_scrape, orig_dong = mention.scrape_range, mention.search_dong
    mention.scrape_range = fake_scrape
    mention.search_dong = lambda q, limit=5: []
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        for greeting in ("안녕?", "하이", "너 누구야", "뭐해"):
            reply = build_reply(f"<@U1> {greeting}", now)
            # 자기소개인지는 뒤따르는 기능 안내로 가린다 — 그쪽은 고정이고, 첫 인사말은
            # 날짜에 따라 돌려 쓰므로(HELLO_LINES) 문장에 묶지 않는다.
            assert "날씨 알리미" in reply, f"{greeting}: {reply[:40]}"
            assert "동네예보" in reply, f"{greeting}: {reply[:80]}"
        assert not calls, "인사인데 예보를 수집했습니다"

        for thanks in ("고마워!", "감사합니다", "수고했어"):
            reply = build_reply(f"<@U1> {thanks}", now)
            assert "천만에요" in reply, f"{thanks}: {reply[:40]}"

        assert "•" in build_reply("<@U1> 도움말", now), "도움말이 사용법을 안 보여줍니다"

        # 지역이 함께 오면 인사말이 섞여 있어도 날씨를 보여준다.
        # 구역명으로 확인한다 — '부산' 은 시도 동네예보로 빠진다(find_wide).
        build_reply("<@U1> 경남 안녕", now)
        assert calls == ["경남"], calls
        print("[ok] 인사 응답 — 자기소개/감사/도움말 구분, 지역 우선")
    finally:
        mention.scrape_range, mention.search_dong = orig_scrape, orig_dong
        clear()


def test_long_range_routing() -> None:
    """10일 너머 요청의 세 갈래: 1개월 전망 / 너무 먼 미래 / 정상 조회."""
    import src.mention as mention
    from src.cache import clear
    from src.kma_scrape import Scrape

    calls: list = []

    def fake_scrape(now, start, span, region):
        calls.append(region.key)
        return Scrape(days={}, narratives=[])

    outlook_calls: list = []

    def fake_outlook(region_key="전국", now=None):
        outlook_calls.append(region_key)
        from src.outlook import Outlook, WeekOutlook
        return Outlook(
            issued="2026년 9월 10일 11시", period="2026년 9월 21일 ~ 10월 18일",
            region=region_key,
            weeks=[WeekOutlook("09.21.~09.27.", "맑겠습니다.", "18.2~19.2",
                               (20, 40, 40), (50, 30, 20))],
            url="https://example.invalid",
        )

    orig = (mention.scrape_range, mention.search_dong, mention.fetch_outlook)
    mention.scrape_range, mention.search_dong = fake_scrape, lambda q, limit=5: []
    mention.fetch_outlook = fake_outlook
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        # 1개월 전망으로 답한다 — 계절 표현 포함
        for q in ("다음 달 날씨", "올해 겨울은 어때?", "올여름", "10월 날씨"):
            clear()
            reply = build_reply(f"<@U1> {q}", now)
            assert "1개월 전망" in reply, f"{q}: {reply[:50]}"
            assert "확률" in reply, f"{q}: 확률이라는 점이 안 드러남"
        assert not calls, "전망 요청인데 일별 예보를 수집했습니다"
        assert outlook_calls, "전망을 조회하지 않았습니다"

        # 지역을 함께 주면 그 지역 전망
        clear()
        outlook_calls.clear()
        build_reply("<@U1> 다음 달 부산", now)
        assert outlook_calls == ["경남"], outlook_calls

        # 1개월로도 못 다루는 먼 미래는 거절
        for q in ("내년 봄", "3개월 전망"):
            clear()
            assert "예보하지 않습니다" in build_reply(f"<@U1> {q}", now)

        # 과거는 계절 표현과 겹쳐도 미래 전망으로 새지 않는다
        clear()
        outlook_calls.clear()
        for q in ("지난 해 여름은 어땠어?", "작년 여름", "어제 서울", "지난주 부산"):
            reply = build_reply(f"<@U1> {q}", now)
            assert "지난 날씨는" in reply, f"{q}: {reply[:50]}"
        assert not outlook_calls, "과거 질문인데 전망을 조회했습니다"

        # '다음 주' 는 범위 안이라 평소대로
        clear()
        calls.clear()
        build_reply("<@U1> 다음 주 부산", now)
        assert calls == ["경남"], calls
        print("[ok] 장기 요청 분기 — 1개월 전망 / 먼 미래 거절 / 주간 정상")
    finally:
        mention.scrape_range, mention.search_dong, mention.fetch_outlook = orig
        clear()


def test_topic_advice() -> None:
    """활동·복장 질문에 맞춘 조언. 지역·날짜와 함께 와도 해석한다."""
    from types import SimpleNamespace
    from src.advice import detect_topic, topic_advice
    from src.kma_scrape import extract_region

    assert detect_topic("내일 뭐 입지?") == "옷차림"
    assert detect_topic("주말 무등산 등산 괜찮아?") == "야외"
    assert detect_topic("빨래 널어도 될까") == "빨래"
    assert detect_topic("부산 날씨") is None, "평범한 조회를 조언으로 오해했습니다"

    # '등산' 은 지우지 말고 집어낸다 — '무등산' 의 '등산' 을 지우면 지역까지 잘린다
    assert extract_region("주말 무등산 등산 괜찮아?")[0] is None
    assert extract_region("광주 등산 갈만해?")[0].key == "전남"
    assert extract_region("부산 뭐 입지")[0].key == "경남"

    def day(d, lo, hi, sky=None, pop=None):
        return SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo,
                               tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)

    base = dt.date(2026, 9, 14)
    rainy = [day(base, 18, 24, "흐리고 비", 80), day(base + dt.timedelta(days=1), 17, 25, "맑음", 10)]
    assert "우산" in " ".join(t.text for t in topic_advice("우산", rainy))
    # 야외 활동은 비 오는 날을 피하고 나은 날을 짚어준다
    outdoor = " ".join(t.text for t in topic_advice("야외", rainy))
    assert "09/14" in outdoor and "09/15" in outdoor, outdoor
    # 근거가 없으면 말하지 않는다
    assert topic_advice("야외", []) == []
    print("[ok] 활동별 조언 — 의도 인식, 문장에서 지역 추출, 근거 없으면 침묵")


def test_cache_shared_across_spans() -> None:
    """지역 캐시 하나를 «이번 주»·«다음 주»·«기본» 이 나눠 써도 날이 빠지지 않는다."""
    import src.mention as mention
    from src.cache import clear
    from src.kma_scrape import Narrative, Scrape, ScrapedDay

    base = dt.date(2026, 9, 12)
    full = {base + dt.timedelta(days=i): ScrapedDay(
        date=base + dt.timedelta(days=i), tmin_lo=15.0, tmin_hi=20.0,
        tmax_lo=25.0, tmax_hi=28.0) for i in range(10)}

    def fake_scrape(now, start, span, region):
        # 진짜 scrape_range 처럼 요청 구간만큼 잘라서 돌려준다
        window = {start + dt.timedelta(days=i) for i in range(span)}
        return Scrape(days={d: v for d, v in full.items() if d in window},
                      narratives=[Narrative("통보문", "", None, [])])

    orig = mention.scrape_range
    mention.scrape_range = fake_scrape
    try:
        now = dt.datetime(2026, 9, 12, 9, 0, tzinfo=KST)   # 토요일
        clear()
        # 광역 캐시가 기간을 가로채지 않는지 본다 — «다음 주» 로 캐시를 채운 뒤
        # «기본(오늘부터 7일)» 을 묻는다.
        # 구역명으로 부른다 — '부산' 은 시도 동네예보로 빠진다(find_wide).
        mention.build_reply("<@U123> 경남 다음주", now)
        reply = mention.build_reply("<@U123> 경남 날씨", now)
    finally:
        mention.scrape_range = orig
        clear()

    # 오늘·내일이 빠지면 안 된다 — 캐시에 다음 주만 담겨 통째로 사라진 적이 있다
    for day in ("09/12", "09/13", "09/18"):
        assert day in reply, (day, reply)
    print("[ok] 캐시 공유 — 기간을 바꿔 물어도 날이 빠지지 않는다")


def test_city_uses_dong_forecast() -> None:
    """'부산' 은 구역이 아니라 부산광역시 값으로 답한다 — 기간이 닿는 한."""
    import src.mention as mention
    from src.cache import clear
    from src.kma_scrape import Scrape

    calls: list = []

    def fake_scrape(now, start, span, region):
        calls.append(region.key)
        return Scrape(days={}, narratives=[])

    dong_calls: list = []

    def fake_dong_reply(zone, name, days=4, start=None, **_):
        dong_calls.append((name, days, start))
        return f"*{name}* 동네예보"

    orig = (mention.scrape_range, mention._dong_reply, mention.find_wide)
    mention.scrape_range = fake_scrape
    mention._dong_reply = fake_dong_reply
    mention.find_wide = lambda q: ("2600000000", "부산광역시") if "부산" in q else None
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)   # 월요일
    try:
        clear()
        mention.build_reply("<@U1> 부산 날씨", now)
        assert dong_calls and not calls, (dong_calls, calls)

        # 주 단위는 광역으로 — 이레를 물었는데 동네예보(5일)로 사흘만 주지 않는다
        dong_calls.clear()
        clear()
        mention.build_reply("<@U1> 부산 이번주", now)
        assert calls and not dong_calls, (dong_calls, calls)

        # 동네예보가 닿지 않는 먼 날도 광역으로
        dong_calls.clear()
        calls.clear()
        clear()
        mention.build_reply("<@U1> 부산 다음주", now)
        assert calls and not dong_calls, (dong_calls, calls)
    finally:
        mention.scrape_range, mention._dong_reply, mention.find_wide = orig
        clear()
    print("[ok] 시도 조회 — 가까운 날은 시 단위, 주 단위는 광역")


def test_partial_week_is_declared() -> None:
    """예보가 기간을 못 채우면 머리글이 실제 범위를 말하고, 왜 짧은지 밝힌다."""
    import src.mention as mention
    from src.cache import clear
    from src.kma_scrape import Narrative, Scrape, ScrapedDay

    # 자료는 중기예보처럼 오늘부터 열흘까지만 — 월요일에 «다음 주» 를 물으면 사흘만 걸친다.
    today = dt.date(2026, 9, 14)
    horizon = {today + dt.timedelta(days=i) for i in range(10)}

    def fake_scrape(now, start, span, region):
        days = {d: ScrapedDay(d, 15.0, 20.0, 24.0, 29.0, "맑음", 20, "중기예보")
                for i in range(span) if (d := start + dt.timedelta(days=i)) in horizon}
        return Scrape(days=days, narratives=[Narrative("중기예보", "", None, [])])

    orig = (mention.scrape_range, mention.find_wide, mention.fetch_snapshot)
    mention.scrape_range = fake_scrape
    mention.find_wide = lambda q: None
    mention.fetch_snapshot = lambda today: fake_snapshot(outlook=False)   # 기상청을 부르지 않게 — 단풍철이다
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        clear()
        reply = mention.build_reply("<@U1> 다음주 날씨", now)
    finally:
        mention.scrape_range, mention.find_wide, mention.fetch_snapshot = orig
        clear()

    # 머리글이 09/27 까지라고 말하면 안 된다 — 자료는 09/23 까지다
    assert "09/23" in reply.split("\n")[0], reply.split("\n")[0]
    assert "09/27" not in reply.split("\n")[0], reply.split("\n")[0]
    assert "09/24(목) 이후는 아직 예보가 작성되지 않았습니다" in reply, reply
    # 없는 날을 줄로 만들지 않는다
    assert len([ln for ln in reply.split("\n") if ln.startswith("•")]) == 3, reply
    print("[ok] 기간을 못 채우면 머리글과 안내로 밝힌다")


def test_explicit_date() -> None:
    """"9월 18일" 처럼 날짜를 콕 집으면 그 하루만 답한다."""
    from src.mention import _explicit_date

    today = dt.date(2026, 9, 12)
    assert _explicit_date("9월 18일 부산 날씨", today) == dt.date(2026, 9, 18)
    assert _explicit_date("18일 날씨", today) == dt.date(2026, 9, 18)
    assert _explicit_date("9/18 날씨", today) == dt.date(2026, 9, 18)
    # 월을 안 적으면 가까운 쪽 — 월말에 "2일" 은 다음 달이다
    assert _explicit_date("2일 날씨", dt.date(2026, 9, 28)) == dt.date(2026, 10, 2)
    # 해가 바뀌는 경계
    assert _explicit_date("1월 5일", dt.date(2026, 12, 20)) == dt.date(2027, 1, 5)
    # 기간 표현은 날짜가 아니다
    assert _explicit_date("7일간 날씨", today) is None
    assert _explicit_date("내일 날씨", today) is None
    # 요일 표기가 붙어도 같은 날로 읽고, 찌꺼기를 남기지 않는다.
    # 봇 출력이 «09/16(수)» 형식이라 그대로 복사해 다시 묻는 사람이 많다.
    # 날짜만 맞고 «(금)» 이 남으면 그 뒤 지역 해석이 깨진다(역삼동이 안 잡혔다).
    from src.mention import EXPLICIT_DATE_RE
    for q in ("9/18(금)", "9월 18일(금)", "18일(금)", "9/18 (금)",
              "9월18일(금요일)", "09/18（금）"):
        assert _explicit_date(q, today) == _explicit_date("9/18", today), q
        assert not EXPLICIT_DATE_RE.sub(" ", q).strip(), q   # 요일이 남으면 안 된다

    # 날짜 없이 요일만 있으면 날짜가 아니다 — 괄호만 보고 삼키지 않는다
    assert _explicit_date("금요일 날씨", today) is None
    assert _explicit_date("(금) 날씨", today) is None
    print("[ok] 명시 날짜 해석 — 월 생략·해 넘김·기간 표현·요일 표기 구분")


def test_phrase_rotation() -> None:
    """같은 조건이라도 날짜가 다르면 문구가 달라지고, 같은 날은 늘 같다."""
    import src.advice as advice
    from src.advice import _pick, SPREAD_LINES

    base = dt.date(2026, 9, 13)
    got = {_pick(SPREAD_LINES, base + dt.timedelta(days=i))
           for i in range(len(SPREAD_LINES))}
    assert len(got) == len(SPREAD_LINES), got      # 연속 날짜면 모두 다른 문구

    # 모든 문구 표가 같은 규칙을 따른다 — 하나만 손대고 나머지를 잊으면 여기서 걸린다.
    # (topic_advice 쪽 표가 한동안 고정 문구로 남아 있었다)
    tables = {n: v for n, v in vars(advice).items()
              if n.endswith("_LINES") and isinstance(v, tuple)}
    assert len(tables) >= 12, sorted(tables)
    for name, lines in tables.items():
        assert lines, name                          # 빈 표는 _pick 이 빈 문자열을 낸다
        assert len(set(lines)) == len(lines), name  # 같은 문장이 두 번 들어가면 회전이 준다
        rotated = {_pick(lines, base + dt.timedelta(days=i)) for i in range(len(lines))}
        assert len(rotated) == len(lines), (name, rotated)
    # 한 바퀴 돌면 제자리 — 날짜에만 달린 값이어야 한다. 무작위로 바꾸면 깨진다.
    later = base + dt.timedelta(days=len(SPREAD_LINES))
    assert _pick(SPREAD_LINES, later) == _pick(SPREAD_LINES, base)
    # 표를 비워도 응답 경로가 죽지 않는다
    assert _pick((), base) == ""

    # 같은 날이라도 지역이 다르면 문장이 갈린다 — 한 채널에서 서울과 부산을
    # 잇달아 물었을 때 같은 말이 두 번 나가지 않게 한 장치다.
    by_region = {_pick(SPREAD_LINES, base, r) for r in ("서울", "부산", "대구")}
    assert len(by_region) > 1, by_region
    # 그러면서 같은 곳·같은 날은 늘 같아야 한다 (무작위가 아니다)
    assert _pick(SPREAD_LINES, base, "서울") == _pick(SPREAD_LINES, base, "서울")
    # 소금이 없으면 예전 동작 그대로 — 기본값 호출부가 조용히 바뀌지 않는다
    assert _pick(SPREAD_LINES, base) == SPREAD_LINES[base.toordinal() % len(SPREAD_LINES)]
    print("[ok] 문구 회전 — 날짜·지역별로 다르고 같은 조건은 고정")


def test_advice() -> None:
    """수치에서 조언을 뽑되, 근거가 없으면 말하지 않는다."""
    from src.advice import build_advice
    from types import SimpleNamespace

    def day(d, lo, hi, sky=None, pop=None):
        return SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo,
                               tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)

    base = dt.date(2026, 9, 14)
    # 일교차 15도 + 폭염 + 비
    tips = build_advice([
        day(base, 18, 33), day(base + dt.timedelta(days=1), 20, 26, "비", 80),
    ])
    joined = " ".join(t.text for t in tips)
    # 어떤 조언이 나왔는지는 이모지로 가린다 — 문구는 날짜에 따라
    # 돌려 쓰므로(advice.py _pick) 특정 문장에 묶지 않는다.
    emojis = {t.emoji for t in tips}
    assert ":thermometer:" in emojis, joined          # 일교차
    assert ":sun_with_face:" in emojis, joined        # 폭염
    assert ":umbrella_with_rain_drops:" in emojis, joined   # 비

    # 한파는 폭염보다 우선하고, 둘이 같이 나오지 않는다
    # 한파 조언이 나오고 폭염 조언과 섞이지 않으면 된다 (문구 자체에는 묶지 않는다)
    cold_tips = build_advice([day(base, 2, 10)])
    assert any(t.emoji == ":cold_face:" for t in cold_tips), cold_tips
    assert "온열질환" not in " ".join(t.text for t in cold_tips)
    # (사실, 권하는 말) 짝 표를 비워도 죽지 않고 그 조언만 빠진다
    import src.advice as advice_mod
    orig_cold = advice_mod.COLD_LINES
    advice_mod.COLD_LINES = ()
    try:
        assert not any(t.emoji == ":cold_face:" for t in build_advice([day(base, 2, 10)]))
    finally:
        advice_mod.COLD_LINES = orig_cold

    # 예보관 서술의 특이사항을 집어온다
    typhoon = " ".join(t.text for t in build_advice(
        [day(base, 20, 26)], ["○ (특이사항) 제13호 태풍 북상"]))
    assert "태풍" in typhoon, typhoon

    # 근거가 없으면 빈 목록 — 지어내지 않는다
    assert build_advice([]) == []
    assert build_advice([SimpleNamespace(date=base, tmin_lo=None, tmin_hi=None,
                                         tmax_lo=None, tmax_hi=None, sky=None, pop=None)]) == []
    print("[ok] 생활 조언 — 일교차·폭염·한파·비·특이사항, 근거 없으면 침묵")


def test_resolve_date() -> None:
    """'14일' 같은 표기를 기준일 근처 실제 날짜로 되돌린다 (월 넘어감 포함)."""
    assert _resolve_date(14, dt.date(2026, 9, 10)) == dt.date(2026, 9, 14)
    assert _resolve_date(2, dt.date(2026, 9, 30)) == dt.date(2026, 10, 2)   # 월 넘김
    assert _resolve_date(28, dt.date(2026, 3, 2)) == dt.date(2026, 2, 28)   # 앞 달
    # ±16일 안에 그 '일'이 없으면 None. 2월 10일 기준 32일은 어느 달에도 없다.
    assert _resolve_date(32, dt.date(2026, 2, 10)) is None
    print("[ok] 날짜 해석 (월말·월초 넘어감)")


def test_forecast_validation() -> None:
    """스크랩 값이 이상하면 바로잡거나 버린다."""
    import src.kma_scrape as scrape_mod
    from src.forecast import ForecastError, build_week
    from src.kma_scrape import Scrape

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
        days[d5] = ScrapedDay(d5, 24, 18, 31, 25, "흐림", 40, "중기예보")     # 뒤집힘
        d6 = week_start + dt.timedelta(days=6)
        days[d6] = ScrapedDay(d6, 999, 24, 25, 31, "맑음", 500, "중기예보")   # 범위 밖
        return Scrape(days=days, narratives=[])

    scrape_mod_orig = scrape_mod.scrape_week
    import src.forecast as fc
    fc.scrape_week = fake_scrape
    try:
        week = build_week(Cfg(), now)
        assert len(week.days) == 7
        assert (week.days[5].tmin_lo, week.days[5].tmin_hi) == (18.0, 24.0), "뒤집힌 범위 미보정"
        assert week.days[6].tmin_lo is None, "범위 밖 값을 못 버렸습니다"
        assert week.days[6].pop is None, "강수확률 범위 밖 값을 못 버렸습니다"
        assert any("뒤집" in w for w in week.warnings)
        print(f"[ok] 예보 검증 — 경고 {len(week.warnings)}건: {week.warnings[0]}")

        # 기온이 4일 이상 비면 게시를 포기해야 한다
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
    """멘션 문장에서 지역과 기간을 읽어내는지. (네트워크는 타지 않는 경로만 확인)"""
    import src.mention as mention
    from src.cache import clear
    from src.kma_scrape import Scrape

    calls: list[tuple] = []

    def fake_scrape(now, start, span, region):
        calls.append((region.key, start, span))
        return Scrape(days={}, narratives=[])

    orig = mention.scrape_range
    mention.scrape_range = fake_scrape
    try:
        now = dt.datetime(2026, 9, 12, 9, 0, tzinfo=KST)   # 토요일
        # 광역 조회의 수집 범위를 본다 — 시도 이름('부산'·'제주')은 동네예보로
        # 빠지므로(find_wide) 구역명으로 부른다.
        for text in ("<@U123> 경남 날씨 알려줘", "<@U123> 전북 다음주", "<@U123> 강원 이번주"):
            clear()
            build_reply(text, now)

        # 수집은 늘 «오늘부터 열흘» 이다 — 지역당 캐시 한 항목을 나눠 쓰기 위해서다.
        # 어느 기간을 물었는지는 아래 show 검사가 본다.
        assert [c[0] for c in calls] == ["경남", "전북", "강원"], calls
        assert all(c[1] == dt.date(2026, 9, 12) and c[2] == 10 for c in calls), calls

        # 광역에도 동에도 없는 말이면 긁지 않고 안내한다 (동 검색은 격리)
        import src.dong as dong_mod
        orig = dong_mod.search_dong
        mention.search_dong = lambda q, limit=5: []
        try:
            before = len(calls)
            reply = build_reply("<@U123> 존재하지않는지명", now)
            assert len(calls) == before, "모르는 지역인데 수집을 시도했습니다"
            assert "아는 지역이 아닙니다" in reply
        finally:
            mention.search_dong = orig
        print("[ok] 멘션 파싱 — 기본 '오늘부터 7일', 이번주/다음주 인식, 미지원 지역 거절")
    finally:
        mention.scrape_range = orig
        clear()


def test_card_render() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    week = fake_week()

    png = render_png(week, scale=2)
    assert png.startswith(PNG_MAGIC), "PNG가 아님"
    (IMG / "card.png").write_bytes(png)
    print(f"[ok] 카드 렌더링 {len(png):,}B -> {IMG / 'card.png'}")

    # 서술 없이 숫자만 있어도(=부분 실패) 카드가 나와야 한다
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
    """규칙 기반 본문 — 1문단은 문장으로 맺고, 2문단은 같은 날 조언을 한 문장으로 엮는다.

    10/5 게시물처럼 «…유의*이라 전하고 있사오니 / *10/07* 일교차가 … *10/07* 아침 최저 …» 로
    끊겨 읽히면 안 된다 — 연결어미를 2문단이 이어받지 못했고, 한 줄짜리 조언을 그대로 붙였었다.
    """
    import re
    from types import SimpleNamespace
    from src.advice import SPREAD_LINES, build_advice
    from src.writer import quote_josa, theme_paragraph

    first, second = fallback(fake_week()).body.split("\n\n")
    assert first.endswith("습니다."), first                   # 열어 두지 않는다
    assert '유의*"라고 전하고' in first, first                # «유의이라» 가 아니다

    # 닫는 별표 바로 뒤에 한글을 붙이지 않는다 — 슬랙이 굵게로 읽지 않을 수 있다
    for part in (first, second):
        for m in re.finditer(r"\*[^*\n]+\*", part):
            assert not re.match(r"[가-힣]", part[m.end():m.end() + 1]), part

    assert quote_josa("기온차 큼") == "이라고"
    assert quote_josa("높은 물결 유의") == "라고"
    assert quote_josa("기온차 큼(동해안 제외)") == "라고"     # 괄호 꼬리는 건너뛴다

    def day(d, lo, hi, sky=None, pop=None):
        return SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo,
                               tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)

    wed = dt.date(2026, 10, 7)
    # 10/5 과 같은 꼴 — 같은 날 일교차 14도 + 아침 4도
    text = theme_paragraph(build_advice([day(wed - dt.timedelta(days=1), 12, 22), day(wed, 4, 18)]))
    assert text.count("10/7") == 1, text                         # 날짜는 한 번
    assert text.startswith("*10/7(수)에는* 아침 최저 4도까지 내려가고 "
                           "일교차가 14도 안팎으로 벌어지겠습니다. "), text
    assert text.endswith(":cold_face:") and text.count(":") == 2, text     # 이모지 하나

    # 날이 달라도 기온 조언은 한 문장 — 날짜 순으로, 권하는 말은 하나
    text = theme_paragraph(build_advice([day(wed + dt.timedelta(days=1), 6, 22), day(wed, 2, 12)]))
    assert text.startswith("*10/7(수)에는* 아침 최저 2도까지 내려가고, "
                           "*10/8(목)에는* 일교차가 16도 안팎으로 벌어지겠습니다. "), text
    assert not any(act in text for _, act in SPREAD_LINES), text   # 추위 쪽 권하는 말 하나만
    assert text.endswith(":cold_face:"), text

    # 어간에 «고»·«겠습니다» 를 붙인다 — «올라겠습니다» 가 아니다
    text = theme_paragraph(build_advice([day(wed, 20, 34)]))
    assert "34도까지 오르고 일교차가" in text, text
    assert theme_paragraph(build_advice([day(wed, 24, 34)])).startswith(
        "*10/7(수)에는* 낮 최고 34도까지 오르겠습니다. ")

    # 같은 날 비는 따로 권하되 날짜를 되풀이하지 않는다
    text = theme_paragraph(build_advice([day(wed, 4, 18, "비", 80)]))
    assert text.count("10/7") == 1 and "같은 날은 비가 오겠습니다." in text, text

    # 같은 종류의 특이사항(풍랑·너울)은 하나만 — 두 자리를 다 차지하지 않는다
    text = theme_paragraph(build_advice([day(wed, 4, 18)], ["○ 너울 유의", "○ 풍랑 유의"]))
    assert "너울" in text and "풍랑" not in text and "10/7" in text, text

    # 조언이 없으면 인사로 맺는다
    assert theme_paragraph([]).startswith("이번 주도")
    print("[ok] 주간 본문 — 문장으로 맺고, 같은 날 조언은 한 문장으로")


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
    """서로 다른 지역을 물으면 답이 서로 달라 보인다 — 꼬리말·조언 양쪽에서.

    고정 꼬리말 두 줄이 화면의 절반이고 조언 문구를 날짜만 보고 고르면, 서울과 부산을
    잇달아 물었을 때 본문이 달라도 두 답이 같은 메시지로 읽힌다(실제로 그랬다).
    """
    import src.mention as mention
    from types import SimpleNamespace

    def fake_fetch(zone, name, days_n):
        base = dt.date(2026, 9, 16)
        rows = [(base + dt.timedelta(days=i), 16.0, 29.0, "맑음", 10)
                for i in range(days_n)]
        return SimpleNamespace(
            name=name, issued="2026년 09월 15일 (화)요일 17:00",
            daily_summary=lambda: rows,
        )

    orig = mention.fetch_dong
    try:
        # 하루만 물으면 광역 안내를 달지 않는다 — 쓸모가 없는데 자리만 차지한다
        mention.fetch_dong = lambda z, n: fake_fetch(z, n, 1)
        one = mention._dong_reply("1100000000", "서울특별시", days=1)
        assert "더 먼 날이 필요" not in one, one
        assert "발표" in one, one            # 출처는 남는다

        # 동네예보 끝까지 물었으면 안내를 단다 — 그때는 쓸모 있다
        mention.fetch_dong = lambda z, n: fake_fetch(z, n, mention.DONG_MAX_DAYS)
        full = mention._dong_reply("1100000000", "서울특별시", days=mention.DONG_MAX_DAYS)
        assert "더 먼 날이 필요" in full, full

        # 같은 날·같은 수치라도 지역이 다르면 조언 문장이 갈린다
        mention.fetch_dong = lambda z, n: fake_fetch(z, n, 3)
        seoul = mention._dong_reply("1100000000", "서울특별시", days=3)
        busan = mention._dong_reply("2600000000", "부산광역시", days=3)
        def tip(r):
            return [ln for ln in r.split("\n") if ln.startswith(":")]
        assert tip(seoul) and tip(busan), (seoul, busan)
        assert tip(seoul) != tip(busan), (tip(seoul), tip(busan))
    finally:
        mention.fetch_dong = orig
    print("[ok] 꼬리말은 필요할 때만, 조언은 지역마다 다르게")


# --- 단풍 -------------------------------------------------------------------

def fake_snapshot(stages=None, first=None, peak=None, *, in_service=True, outlook=True):
    from src.foliage import Outlook, Snapshot, Status
    from src.mountains import MOUNTAINS

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
    """9월 둘째 월요일 ~ 11월 둘째 월요일이 든 주. 해마다 날짜가 다르다."""
    from src.foliage import in_season, next_season, season_bounds

    d = dt.date
    assert season_bounds(2026) == (d(2026, 9, 14), d(2026, 11, 15))
    assert season_bounds(2027) == (d(2027, 9, 13), d(2027, 11, 14))   # 11/1 이 월요일인 해
    assert not in_season(d(2026, 9, 13)) and in_season(d(2026, 9, 14))
    assert in_season(d(2026, 11, 15)) and not in_season(d(2026, 11, 16))
    assert next_season(d(2026, 9, 1)) == season_bounds(2026)
    assert next_season(d(2026, 12, 1)) == season_bounds(2027)
    print("[ok] 단풍 기간 — 9월 둘째 주 ~ 11월 둘째 주")


def test_foliage_parse() -> None:
    """기상청 JSONP 와 웨더아이 표. 지난 시즌 값·잘못 읽은 표는 버린다."""
    import json

    from src.foliage import FoliageError, _date, parse_outlook_text, parse_status

    def jsonp(service: bool, statuses: dict[str, str], flower: dict) -> str:
        places = [{"obsPlace": n, "status": s, "sts": str(["단풍전", "첫단풍", "절정"].index(s) + 1)}
                  for n, s in statuses.items()]
        return "\r\n\r\napplyMapleData(" + json.dumps(
            {"places": places, "isService": service, "flower": flower}, ensure_ascii=False) + ")"

    stages, live, flower = parse_status(
        jsonp(True, {"설악산": "첫단풍", "오대산": "단풍전", "한라산": "절정"},
              {"obsPlace": "설악산", "cfShotDate": "2026-09-28"}), 2026)
    assert live and stages == {"설악산": 1, "오대산": 0, "한라산": 2}, stages
    assert _date(flower["cfShotDate"], 2026) == dt.date(2026, 9, 28)
    # 서비스 기간 밖의 단계는 올해 현황으로 읽지 않는다 — 지난 시즌 값이 남아 있다
    stages, live, _ = parse_status(jsonp(False, {"설악산": "절정"}, {}), 2026)
    assert not live and stages == {"설악산": 0}, stages
    assert _date("2025-10-20", 2026) is None, "지난해 촬영일을 올해 것으로 읽었습니다"
    try:
        parse_status("<html>점검 중</html>", 2026)
        raise AssertionError("JSONP 가 아닌데 통과했습니다")
    except FoliageError:
        pass

    # 2025~ 는 '10/3', 2024 까지는 '09.27'. 금강산은 기상청 목록에 없어 빠진다.
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
    from src.mountains import MOUNTAINS, find_mountain, unknown_mountain
    from src.render_foliage import LAT0, LAT1, LON0, LON1

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
    # 산 이름이 든 행정구역은 산이 아니다 — 가평 설악면 날씨가 속초로 나가면 안 된다
    for q in ("가평 설악면 날씨", "보은 속리산면은", "청송 주왕산면에서", "가평 설악면으로 가는데 날씨",
              "속리산면에서는 어때"):
        assert find_mountain(q) is None, q
    # 어미 '-면' 은 행정구역이 아니다
    for q, name in (("설악산이면 어때", "설악산"), ("지리산가려면 뭐 입어", "지리산")):
        assert (m := find_mountain(q)) and m.name == name, q
    assert find_mountain("설악산에서 하룻밤").name == "설악산"
    # '산' 만 뗀 줄임말은 낱말로 섰을 때만 — 도시의 학교·경기장을 산으로 보내지 않는다
    for q in ("내일 한라대 근처 날씨", "원주 치악체육관 날씨", "광주 무등경기장 날씨"):
        assert find_mountain(q) is None, q
    assert find_mountain("주말 설악 날씨").name == "설악산"

    from src.mountains import REGION_MOUNTAINS, in_region, in_zone
    from src.kma_scrape import REGIONS

    names = {m.name for m in MOUNTAINS}
    assert set(REGION_MOUNTAINS) <= {r.key for r in REGIONS}, "없는 구역 이름"
    assert all(set(v) <= names for v in REGION_MOUNTAINS.values()), "없는 산 이름"
    assert names == {n for v in REGION_MOUNTAINS.values() for n in v}, "어느 구역에도 없는 산"
    assert [m.name for m in in_region("강원")] == ["설악산", "오대산", "치악산"]
    for code, want in (("1100000000", ["북한산"]), ("2700000000", ["팔공산"]), ("1230000000", ["무등산"]),
                       ("5000000000", ["한라산"]), ("2600000000", [])):
        assert [m.name for m in in_zone(code)] == want, (code, in_zone(code))
    print("[ok] 산 이름 — 별칭 · 목록 밖 산 · 산이 아닌 'X산' · 행정구역 · 구역별 산")


def test_foliage_routing() -> None:
    """단풍·꽃 질문의 갈래. 과거·1개월 전망으로 새지 않는다."""
    import src.mention as mention
    from types import SimpleNamespace

    snap = fake_snapshot({"설악산": 1}, first={"설악산": dt.date(2026, 9, 28)})
    dong_calls: list = []

    def fake_dong(zone, name):
        dong_calls.append((zone, name))
        rows = [(dt.date(2026, 10, 3) + dt.timedelta(days=i), 9.0, 23.0, "맑음", 10) for i in range(2)]
        return SimpleNamespace(name=name, issued="2026년 10월 01일 (목)요일 14:00",
                               daily_summary=lambda: rows)

    from src.cache import clear
    from src.kma_scrape import Scrape

    scraped: list = []
    renders: list = []

    def fake_render(s, start, span_label=""):
        renders.append(start)
        return b"PNG"

    def fake_scrape(now, start, span, region):
        scraped.append(region.key)
        return Scrape(days={}, narratives=[])

    orig = (mention.fetch_snapshot, mention.fetch_dong, mention.render_foliage_png, mention.scrape_range)
    mention.fetch_snapshot = lambda today: snap
    mention.fetch_dong = fake_dong
    mention.render_foliage_png = fake_render          # Chromium 없이
    mention.scrape_range = fake_scrape
    now = dt.datetime(2026, 10, 1, 15, 0, tzinfo=KST)
    clear()
    try:
        def ask(q, when=now):
            return mention.answer(f"<@U1> {q}", when).text

        res = mention.answer("<@U1> 단풍 어디까지 왔어", now)
        overview = res.text
        assert "단풍 현황" in overview and "*설악산* 첫단풍 9/28" in overview, overview
        assert "예상보다 5일 빠름" in overview, overview
        assert res.image == b"PNG", "전체 현황인데 지도가 없습니다"
        assert mention.answer("<@U1> 설악산 단풍", now).image is None, "산 하나에는 글로만 답한다"
        mention.answer("<@U1> 단풍 어때", now)
        assert len(renders) == 1, f"같은 현황인데 지도를 {len(renders)}번 그렸습니다"

        # '었나' 는 과거로, '가을' 은 1개월 전망으로 새지 않는다 (예전엔 샜다)
        seorak = ask("설악산 단풍 물들었나")
        assert "*설악산* 단풍" in seorak and "9/28 관측" in seorak, seorak
        assert "지난 날씨" not in seorak
        assert "1개월 전망" not in ask("올가을 단풍 언제 절정이야")
        assert "지난 날씨" not in ask("작년보다 단풍 늦어?")

        # 날짜·날씨를 함께 물으면 산 아래 마을 예보를 붙인다
        weekend = ask("주말 내장산 단풍 어때")
        assert "11/5 예상" in weekend and "동네예보" in weekend, weekend
        assert dong_calls and dong_calls[-1][0] == "5218053500", dong_calls
        assert "산 아래 마을 예보" in weekend
        dong_calls.clear()
        assert "동네예보" not in ask("내장산 단풍 언제 절정이야") and not dong_calls

        assert "21곳에 없습니다" in ask("화악산 단풍은?")
        assert "21곳에 없습니다" not in ask("부산 근처 단풍")

        # 꽃은 언제든 거절, 단풍은 기간 밖이면 거절
        for when in (now, dt.datetime(2026, 4, 1, tzinfo=KST)):
            assert "꽃 개화 소식은 다루지 않습니다" in ask("벚꽃 피었어?", when)
        late = ask("단풍 어때", dt.datetime(2026, 12, 1, tzinfo=KST))
        assert "9월 둘째 주 ~ 11월 둘째 주" in late and "2027년 9/13" in late, late
        early = ask("설악산 단풍", dt.datetime(2026, 9, 1, tzinfo=KST))
        assert "올해는 9/14(월)부터" in early, early

        # 단풍 말이 없으면 평소 갈래 그대로
        assert "지난 날씨는" in ask("작년 여름")

        # 단풍·꽃 말이 섞인 날씨 질문은 날씨로 답한다
        scraped.clear()
        weather = ask("단풍 구경 가는데 강원도 날씨 어때")
        assert scraped == ["강원"] and "단풍 현황" not in weather, (scraped, weather)
        assert "꽃 개화 소식" not in ask("꽃구경 가는데 내일 강원 날씨")
        # 지역만 있고 날씨를 묻지 않으면 단풍 질문이다
        assert "단풍 현황" in ask("강원도 단풍 어때")

        # 단풍 상태·날짜를 되묻는 말에는 날씨를 붙이지 않는다
        dong_calls.clear()
        for q in ("설악산 단풍 지금 어때", "오대산 단풍 현재 상태", "설악산 단풍 절정 10/25 맞아?"):
            assert "동네예보" not in ask(q), q
        assert not dong_calls, dong_calls
        # 동네예보를 못 받으면 도움말 대신 한 줄로 알린다
        mention.fetch_dong = lambda z, n: (_ for _ in ()).throw(mention.DongError("점검"))
        failed = ask("주말 설악산 단풍")
        assert "가져오지 못했습니다" in failed and "광역" not in failed, failed
        mention.fetch_dong = fake_dong
        # '다음 주 주말' 은 이번 주말이 아니다 — 10/10 은 동네예보(5일) 밖이라 안내만 나간다
        next_weekend = ask("다음 주 주말 설악산 단풍")
        assert "10/03" not in next_weekend and "5일까지" in next_weekend, next_weekend

        # 물들었는데 촬영일이 아직 없으면 — 지난 단계의 예상일을 꺼내지 않는다
        mention.fetch_snapshot = lambda today: fake_snapshot({"설악산": 1})
        bare = ask("설악산 단풍")
        assert "*관측* (촬영일은" in bare and "예상이었지만" not in bare, bare
        assert ask("단풍 어디까지").count("*설악산* 첫단풍") == 1
    finally:
        (mention.fetch_snapshot, mention.fetch_dong, mention.render_foliage_png,
         mention.scrape_range) = orig
        clear()
    print("[ok] 단풍 멘션 — 현황 · 산별 · 산 날씨 · 목록 밖 산 · 꽃/기간 밖 거절")


def test_foliage_in_weather() -> None:
    """단풍 말 없이 물어도 — 산 이름이면 산 날씨와 그 산의 단풍, 지역 날씨면 그 지역 산의 한 줄."""
    import src.mention as mention
    from types import SimpleNamespace

    from src.cache import clear
    from src.foliage import FoliageError
    from src.kma_scrape import Scrape, ScrapedDay

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

    def fake_snap(today):
        if isinstance(snaps[0], Exception):
            raise snaps[0]
        return snaps[0]

    wide = {"제주": ("5000000000", "제주특별자치도"), "서울": ("1100000000", "서울특별시")}
    snaps_base = [now.date()]
    orig = (mention.fetch_snapshot, mention.fetch_dong, mention.scrape_range, mention.find_wide)
    mention.fetch_snapshot = fake_snap
    mention.fetch_dong = fake_dong
    mention.scrape_range = fake_scrape
    mention.find_wide = lambda q: wide.get(q.strip())
    try:
        def ask(q, when=now):
            clear()
            return mention.answer(f"<@U1> {q}", when).text

        # 산 이름만 — 예전에는 "아는 지역이 아닙니다" 였다
        for q in ("설악산", "설악산 날씨"):
            dong_calls.clear()
            reply = ask(q)
            assert dong_calls == ["5121060000"], (q, dong_calls)
            assert "설악산 아래 속초시 대포동" in reply and "*설악산* 단풍 — 지금 *첫단풍*" in reply, reply
            assert reply.index("동네예보") < reply.index("*설악산* 단풍"), "날씨를 물었으니 날씨가 먼저다"
        # 조언 갈래에서 전국으로 빠지던 질문
        dong_calls.clear()
        hike = ask("주말 설악산 등산")
        assert dong_calls == ["5121060000"] and "*전국*" not in hike, (dong_calls, hike)
        dong_calls.clear()
        assert "내장산 아래" in ask("내장산 가는데 다음 주 날씨") and dong_calls == ["5218053500"]
        # 단풍철 밖이면 산 날씨만, 단풍 기간 안내도 없이
        snaps_base[0] = dt.date(2026, 12, 1)
        winter = ask("설악산 날씨", dt.datetime(2026, 12, 1, 9, 0, tzinfo=KST))
        assert "설악산 아래" in winter and "단풍" not in winter, winter
        snaps_base[0] = now.date()

        # 지역 날씨 — 물든 산과 그 기간의 예상만
        gangwon = ask("강원 날씨")
        assert ":maple_leaf: *단풍* — *설악산* 첫단풍 9/28 · *오대산* 첫단풍 10/7 (예상)" in gangwon, gangwon
        assert "치악산" not in gangwon, "기간(10/1~10/7) 밖의 예상이 붙었습니다"
        assert "*치악산* 첫단풍 10/10 (예상)" in ask("강원 다음주")
        # 물든 산에 다음 단계가 다가오면 이어서 적는다 (10/20 부터 7일에 설악산 절정 10/25)
        assert "*설악산* 첫단풍 9/28 → 절정 10/25 (예상)" in ask(
            "영동 날씨", dt.datetime(2026, 10, 20, 9, 0, tzinfo=KST))
        nationwide = ask("전국 날씨")
        assert "나머지 20곳은 단풍 전" in nationwide and "*오대산* 10/7" in nationwide, nationwide
        # 그 지역에 말할 것이 없으면 붙이지 않는다
        assert ":maple_leaf:" not in ask("경남 날씨")
        assert ":maple_leaf:" not in ask("제주")                 # 한라산 첫단풍 예상 10/31 은 기간 밖
        # 시도 동네예보에도 — 서울이면 북한산
        snaps[0] = fake_snapshot({"북한산": 1}, first={"북한산": dt.date(2026, 9, 30)})
        assert "*북한산* 첫단풍 9/30" in ask("서울")
        # 단풍철 밖이거나 단풍을 못 받아 와도 날씨는 그대로
        snaps[0] = FoliageError("점검 중")
        failed = ask("강원 날씨")
        assert "*강원*" in failed and ":maple_leaf:" not in failed, failed
        assert "설악산 아래" in ask("설악산") and "단풍 —" not in ask("설악산")
        assert ":maple_leaf:" not in ask("강원 날씨", dt.datetime(2026, 12, 1, 9, 0, tzinfo=KST))
    finally:
        mention.fetch_snapshot, mention.fetch_dong, mention.scrape_range, mention.find_wide = orig
        clear()
    print("[ok] 날씨 속 단풍 — 산 이름은 산 날씨와 단풍, 지역 날씨는 그 지역 산 한 줄")


def test_period_next_weekend() -> None:
    from src.mention import _period

    thu = dt.datetime(2026, 10, 1, 9, 0, tzinfo=KST)
    assert _period("주말 설악산", thu)[:2] == (dt.date(2026, 10, 3), 2)
    assert _period("다음 주 주말", thu)[:2] == (dt.date(2026, 10, 10), 2)
    assert _period("다음주 토요일 부산", thu)[0] == dt.date(2026, 10, 10)
    print("[ok] 기간 — '다음 주 주말' 은 다음 주의 토·일")


def test_foliage_fetch() -> None:
    """산별 날짜: 목록에 딸려 온 상세는 다시 부르지 않고, 촬영일이 빈 상세는 캐시하지 않는다."""
    import json

    import src.foliage as foliage
    from src.cache import clear

    def jsonp(places: dict[str, str], flower: dict) -> str:
        return "applyMapleData(" + json.dumps({
            "isService": True, "flower": flower,
            "places": [{"obsPlace": n, "status": st, "sts": None} for n, st in places.items()],
        }, ensure_ascii=False) + ")"

    places = {"설악산": "첫단풍", "오대산": "첫단풍", "치악산": "", "한라산": "단풍전"}
    details = {
        "": {"obsPlace": "설악산", "cfShotDate": "2026-09-28"},
        "오대산": {"obsPlace": "오대산", "cfShotDate": ""},       # 단계만 먼저 바뀌었다
    }
    calls: list = []

    def fake_kma(place=""):
        calls.append(place)
        return jsonp(places, details[place])

    orig = foliage._kma
    foliage._kma = fake_kma
    clear()
    try:
        status = foliage.fetch_status(dt.date(2026, 10, 1))
        # "sts": null + 모르는 글자는 단풍전으로 — 예외로 새지 않는다
        assert status.stage("치악산") == 0 and status.stage("오대산") == 1
        assert status.first == {"설악산": dt.date(2026, 9, 28)}, status.first
        assert calls == ["", "오대산"], f"설악산 상세를 다시 불렀습니다: {calls}"
        # 빈 상세는 캐시하지 않는다 — 다음 조회에서 날짜가 올라왔으면 받는다
        details["오대산"]["cfShotDate"] = "2026-10-06"
        assert foliage._detail("오대산", 1, 2026) == (dt.date(2026, 10, 6), None)
        details["오대산"]["cfShotDate"] = ""
        assert foliage._detail("오대산", 1, 2026)[0] == dt.date(2026, 10, 6), "날짜가 생기면 캐시한다"
    finally:
        foliage._kma = orig
        clear()

    # 웨더아이 예상이 아직 없으면 None — 30분만 기억한다
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
    """실패를 잠시 기억하고, 지난 항목은 새 값을 넣을 때 걷어낸다."""
    import time

    import src.cache as cache

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
    # errors 에 없는 예외는 기억하지 않는다
    try:
        cache.get_or_set("j", 60, boom)
    except ValueError:
        pass
    assert "j" not in cache._STORE

    cache.get_or_set("old", 0.01, lambda: "x")
    time.sleep(0.02)
    cache.get_or_set("new", 60, lambda: "y")
    assert "old" not in cache._STORE and "new" in cache._STORE
    cache.clear()
    print("[ok] 캐시 — 실패 기억, 지난 항목 정리")


def test_foliage_render() -> None:
    from src.foliage import STAGES
    from src.render_foliage import build_html, observed_line, render_png as render_map

    d = dt.date
    early = fake_snapshot({"설악산": 1}, first={"설악산": d(2026, 9, 28)})
    html_text = build_html(early, d(2026, 10, 5))
    assert "첫단풍 <b>오대산</b> 10/7 · <b>치악산</b> 10/10" in html_text, "이번 주 예상이 빠졌습니다"
    assert "9/4 발표" in html_text

    # 물든 곳이 많아지면 이름을 늘어놓지 않고 개수와 최근 변화로 줄인다
    late = fake_snapshot(
        {"설악산": 2, "오대산": 2, "치악산": 1, "북한산": 1, "한라산": 1},
        first={"설악산": d(2026, 9, 28), "오대산": d(2026, 10, 6), "치악산": d(2026, 10, 12),
               "북한산": d(2026, 10, 20), "한라산": d(2026, 10, 25)},
        peak={"설악산": d(2026, 10, 18), "오대산": d(2026, 10, 15)},
    )
    line = observed_line(late)
    assert line.startswith(f"{STAGES[2]} 2곳 · {STAGES[1]} 3곳 · {STAGES[0]} 16곳"), line
    assert "한라산</b> 첫단풍 10/25" in line, line

    # 물들었는데 촬영일이 없어도 문장이 깨지지 않는다
    assert observed_line(fake_snapshot({"설악산": 1})) == "<b>설악산</b> 첫단풍, 나머지 20곳은 단풍 전"

    # 예상이 없어도 현황만으로 그린다
    assert "올해 예상이 아직 나오지 않았습니다" in build_html(fake_snapshot(outlook=False), d(2026, 9, 14))

    IMG.mkdir(parents=True, exist_ok=True)
    png = render_map(late, d(2026, 10, 26))
    assert png.startswith(PNG_MAGIC)
    (IMG / "foliage-test.png").write_bytes(png)
    print(f"[ok] 단풍 지도 {len(png):,}B -> {IMG / 'foliage-test.png'}")


# --- 게시물 문단 --------------------------------------------------------------

def test_paragraph() -> None:
    """문단 부품. 줄을 조립하고, 빈 줄·빈 문단은 빠지고, 게시물은 본문 → 문단 → 출처 순이다."""
    from src.paragraph import Attachment, Block, Message, Paragraph

    p = Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:").add("관측", "*진해* 개화 3/24").add("올해", "")
    assert [r.label for r in p.rows] == ["관측"], "빈 내용 줄이 들어갔습니다"
    assert p.to_slack() == ":cherry_blossom: *이번 주 벚꽃*\n• 관측 — *진해* 개화 3/24"
    assert Paragraph("제목").add("줄", "내용").to_slack() == "*제목*\n• 줄 — 내용"

    att = Attachment("foliage", b"PNG", "단풍 지도", "지도")
    msg = (Message("날씨 본문", credits=["지상일기도 · 기상청"])
           .add(Block(Paragraph("이번 주 단풍", ":maple_leaf:").add("관측", "설악산"), "단풍 지도 · 기상청", att))
           .add(Block(Paragraph("빈 문단"), "쓰이지 않는 출처"))
           .add(Block(p, "벚꽃 · 기상청")))
    assert msg.attachments == [att]
    assert msg.to_slack() == (
        "날씨 본문\n\n"
        ":maple_leaf: *이번 주 단풍*\n• 관측 — 설악산\n\n"
        ":cherry_blossom: *이번 주 벚꽃*\n• 관측 — *진해* 개화 3/24\n\n"
        "_지상일기도 · 기상청_\n_단풍 지도 · 기상청_\n_벚꽃 · 기상청_"
    ), msg.to_slack()
    assert Message("본문만").to_slack() == "본문만"
    print("[ok] 문단 조립 — 줄 · 빈 줄/빈 문단 제외 · 본문 → 문단 → 출처 · 첨부")


# --- 벚꽃 -------------------------------------------------------------------

def test_blossom_season() -> None:
    """2월 마지막 월요일 ~ 3월 마지막 월요일이 든 주. 윤년·월말 요일에 따라 달라진다."""
    from src.blossom import in_season, season_bounds

    d = dt.date
    assert season_bounds(2026) == (d(2026, 2, 23), d(2026, 4, 5))
    assert season_bounds(2027) == (d(2027, 2, 22), d(2027, 4, 4))
    assert season_bounds(2028) == (d(2028, 2, 28), d(2028, 4, 2))      # 2/29 가 화요일인 윤년
    assert not in_season(d(2026, 2, 22)) and in_season(d(2026, 2, 23))
    assert in_season(d(2026, 4, 5)) and not in_season(d(2026, 4, 6))
    print("[ok] 벚꽃 기간 — 2월 마지막 주 ~ 3월 마지막 주")


def test_blossom_parse() -> None:
    """기상청 JSONP 와 웨더아이 표. 해마다 바뀐 날짜 표기, 군락지·평균 줄, 깨진 표."""
    import json

    from src.blossom import BlossomError, parse_outlook_text, parse_status, posted_on

    def jsonp(service: bool) -> str:
        places = [{"obsPlace": n, "status": s, "sts": str(["개화 전", "개화", "만발"].index(s) + 1)}
                  for n, s in (("진해 여좌천", "만발"), ("여의도 윤중로", "개화"), ("춘천 소양강댐", "개화 전"))]
        return "\r\n\r\napplyFlowerData(" + json.dumps(
            {"places": places, "isService": service, "flower": {}}, ensure_ascii=False) + ")"

    stages, live = parse_status(jsonp(True))
    assert live and stages == {"진해 여좌천": 2, "여의도 윤중로": 1, "춘천 소양강댐": 0}, stages
    # 서비스 기간 밖의 단계는 올해 것으로 읽지 않는다 — 지난 봄의 만발이 남아 있다
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

    # 게시일 — 특보 띠의 오늘 날짜가 아니라 머리 표의 날짜 칸. 작성자 칸이 빈 해도 있다.
    page = ('<marquee>2026-10-02 강풍주의보</marquee><font color="#124c78"></font>'
            '<font color="#124c78">2026-02-26 </font>')
    assert posted_on(page, 2026) == dt.date(2026, 2, 26)
    assert posted_on(page.replace("2026-02-26", "관리자"), 2026) is None
    print("[ok] 벚꽃 자료 읽기 — 날짜 표기 세 가지 · 군락지/평균 줄 제외 · 깨진 표 버림 · 게시일")


def test_blossom_text() -> None:
    """벚꽃 줄 문구. 예상 전엔 평년, 이번 주가 비면 다음 개화, 출처는 받은 쪽만."""
    from src.blossom import Outlook, Status, observed_line, sources, week_line, year_line

    d = dt.date
    normal = {"서귀포": d(2026, 3, 24), "부산": d(2026, 3, 28), "서울": d(2026, 4, 8)}
    outlook = Outlook(expected={"서귀포": d(2026, 3, 25), "부산": d(2026, 3, 25), "울산": d(2026, 3, 26),
                                "서울": d(2026, 4, 3)},
                      normal=normal | {"울산": d(2026, 3, 30)}, published=d(2026, 2, 26))
    unpublished = Outlook(expected={}, normal=normal)
    idle = Status(stages={"진해 여좌천": 0, "여의도 윤중로": 0}, in_service=False)

    assert "아직 시작되지 않았습니다" in observed_line(idle)
    assert "아직 나오지 않았습니다" in week_line(unpublished, d(2026, 2, 23), d(2026, 3, 1))
    assert year_line(unpublished) == "*서귀포* 3/24 무렵 시작해 *서울* 4/8 무렵 핍니다"

    assert week_line(outlook, d(2026, 3, 2), d(2026, 3, 8)) == "개화 예상 없음 · 다음은 *서귀포*·*부산* 3/25 (예상)"
    # 평년차 +1 · -3 · -4 · -5 → 평균 -2.75 → 3일
    assert year_line(outlook) == "평년보다 3일가량 이르겠습니다 (서울 4/3, 평년 4/8)"

    bloom = Status(stages={"진해 여좌천": 1, "여의도 윤중로": 0}, bloom={"진해 여좌천": d(2026, 3, 24)})
    assert observed_line(bloom) == "*진해 여좌천* 개화 3/24, 나머지 1곳은 개화 전"
    assert week_line(outlook, d(2026, 3, 23), d(2026, 3, 29)) == \
        "개화 *서귀포*·*부산* 3/25 · *울산* 3/26 (예상)"

    assert sources(bloom, outlook) == "관측 기상청 날씨누리 · 예상 웨더아이(2/26 발표)"
    assert sources(None, unpublished) == "평년 웨더아이"
    print("[ok] 벚꽃 문구 — 평년 · 다음 개화 · 이번 주 묶음 · 출처")


def test_weekly_themes() -> None:
    """주간 게시의 철 소식. 단풍은 글과 지도, 벚꽃은 글. 못 만들어도 날씨 게시는 나간다."""
    import src.blossom as blossom
    import src.foliage as foliage
    import src.render_foliage as render_foliage
    from src import themes
    from src.blossom import BlossomError, Outlook, Status
    from src.foliage import FoliageError

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

    orig = (foliage.fetch_snapshot, render_foliage.render_png, blossom.fetch_status, blossom.fetch_outlook)
    foliage.fetch_snapshot = lambda today: fake_snapshot({"설악산": 1}, first={"설악산": d(2026, 9, 28)})
    render_foliage.render_png = fake_render
    blossom.fetch_status = lambda today: Status(stages={"진해 여좌천": 0}, in_service=False)
    blossom.fetch_outlook = lambda year: Outlook(expected={"서귀포": d(2026, 3, 25)},
                                                normal={"서귀포": d(2026, 3, 24)}, published=d(2026, 2, 26))
    try:
        (autumn,) = themes.blocks_for(d(2026, 10, 5), d(2026, 10, 2), 2)
        assert autumn.paragraph.title == "이번 주 단풍" and labels(autumn) == ["관측", "이번 주"]
        text = autumn.paragraph.to_slack()
        assert "*설악산* 첫단풍 9/28" in text and "첫단풍 *오대산* 10/7 · *치악산* 10/10 (예상)" in text, text
        assert autumn.attachment.slug == "foliage" and autumn.attachment.png == b"PNG"
        assert autumn.credit.startswith("단풍 지도 · "), autumn.credit
        # 지도를 못 그려도 글은 남고, 출처에서 '지도' 가 빠진다
        fail_render[0] = True
        (autumn,) = themes.blocks_for(d(2026, 10, 5), d(2026, 10, 2), 2)
        assert autumn.attachment is None and autumn.credit.startswith("단풍 · ") and autumn.paragraph.rows

        (spring,) = themes.blocks_for(d(2026, 3, 23), d(2026, 3, 23), 2)
        assert spring.paragraph.title == "이번 주 벚꽃" and spring.attachment is None
        assert labels(spring) == ["관측", "이번 주", "올해"], labels(spring)
        assert "*서귀포* 3/25" in spring.paragraph.to_slack() and spring.credit.startswith("벚꽃 · ")
        # 예상이 아직이면 '올해' 대신 '평년'
        blossom.fetch_outlook = lambda year: Outlook(expected={}, normal={"서귀포": d(2026, 3, 24)})
        (spring,) = themes.blocks_for(d(2026, 2, 23), d(2026, 2, 23), 2)
        assert labels(spring) == ["관측", "이번 주", "평년"], labels(spring)
        # 관측만 실패하면 예상 줄만, 둘 다 실패하면 벚꽃 소식 없이
        blossom.fetch_status = lambda today: (_ for _ in ()).throw(BlossomError("점검"))
        (spring,) = themes.blocks_for(d(2026, 3, 23), d(2026, 3, 23), 2)
        assert labels(spring) == ["이번 주", "평년"], labels(spring)
        blossom.fetch_outlook = lambda year: (_ for _ in ()).throw(BlossomError("점검"))
        assert themes.blocks_for(d(2026, 3, 23), d(2026, 3, 23), 2) == []
        foliage.fetch_snapshot = lambda today: (_ for _ in ()).throw(FoliageError("점검"))
        assert themes.blocks_for(d(2026, 10, 5), d(2026, 10, 2), 2) == []

        # 어느 철도 아니면 아무것도 붙이지 않고, 자료도 부르지 않는다
        renders.clear()
        assert themes.blocks_for(d(2026, 6, 1), d(2026, 6, 1), 2) == [] and not renders
    finally:
        foliage.fetch_snapshot, render_foliage.render_png, blossom.fetch_status, blossom.fetch_outlook = orig
    print("[ok] 철 소식 — 단풍 글·지도, 벚꽃 글, 실패해도 날씨는 나간다")


if __name__ == "__main__":
    test_extract_json()
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
    test_paragraph()
    test_blossom_season()
    test_blossom_parse()
    test_blossom_text()
    test_weekly_themes()
    print("\n전부 통과")
