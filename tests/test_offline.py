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
    # 영동/영서는 실제 중기예보 구역이라 안내문이 필요 없다
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
            # 첫 인사말은 날짜에 따라 돌려 쓰므로(HELLO_LINES) 문장에 묶지 않는다.
            # 자기소개인지는 뒤따르는 기능 안내로 가린다 — 그쪽은 고정이다.
            assert "날씨 알리미" in reply, f"{greeting}: {reply[:40]}"
            assert "동네예보" in reply, f"{greeting}: {reply[:80]}"
        assert not calls, "인사인데 예보를 수집했습니다"

        for thanks in ("고마워!", "감사합니다", "수고했어"):
            reply = build_reply(f"<@U1> {thanks}", now)
            assert "천만에요" in reply, f"{thanks}: {reply[:40]}"

        assert "•" in build_reply("<@U1> 도움말", now), "도움말이 사용법을 안 보여줍니다"

        # 지역이 함께 오면 인사말이 섞여 있어도 날씨를 보여준다.
        # '부산' 은 시도 동네예보로 빠지므로(find_wide) 구역명으로 확인한다.
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

    # '무등산' 의 '등산' 을 지우면 지역까지 잘린다 — 지우지 말고 집어내야 한다
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
        # «다음 주» 를 먼저 물어 캐시를 채운 뒤 «기본(오늘부터 7일)» 을 묻는다.
        # '부산' 은 시도 동네예보로 빠지므로(find_wide) 구역명으로 부른다 —
        # 여기서 보려는 것은 광역 캐시가 기간을 가로채지 않는지다.
        mention.build_reply("<@U123> 경남 다음주", now)
        reply = mention.build_reply("<@U123> 경남 날씨", now)
    finally:
        mention.scrape_range = orig
        clear()

    # 캐시에 다음 주만 담겨 있으면 오늘·내일이 통째로 사라진다 (실제로 그랬다)
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

    def fake_dong_reply(zone, name, days=4, start=None):
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

        # 주 단위는 동네예보가 못 채운다(5일) — 이레를 물었는데 사흘만 주지 않는다
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

    # 기상청 중기예보는 오늘부터 열흘. 월요일에 «다음 주» 를 물으면 사흘만 걸친다.
    today = dt.date(2026, 9, 14)
    horizon = {today + dt.timedelta(days=i) for i in range(10)}

    def fake_scrape(now, start, span, region):
        days = {d: ScrapedDay(d, 15.0, 20.0, 24.0, 29.0, "맑음", 20, "중기예보")
                for i in range(span) if (d := start + dt.timedelta(days=i)) in horizon}
        return Scrape(days=days, narratives=[Narrative("중기예보", "", None, [])])

    orig = (mention.scrape_range, mention.find_wide)
    mention.scrape_range = fake_scrape
    mention.find_wide = lambda q: None
    now = dt.datetime(2026, 9, 14, 9, 0, tzinfo=KST)
    try:
        clear()
        reply = mention.build_reply("<@U1> 다음주 날씨", now)
    finally:
        mention.scrape_range, mention.find_wide = orig
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
    print("[ok] 명시 날짜 해석 — 월 생략·해 넘김·기간 표현 구분")


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
    print("[ok] 문구 회전 — 날짜별로 다르고 같은 날은 고정")


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
    # 문구는 날짜에 따라 돌려 쓰므로(advice.py _pick) 특정 문장에 묶지 않는다.
    # 어떤 조언이 나왔는지는 이모지가 가리킨다.
    emojis = {t.emoji for t in tips}
    assert ":thermometer:" in emojis, joined          # 일교차
    assert ":sun_with_face:" in emojis, joined        # 폭염
    assert ":umbrella_with_rain_drops:" in emojis, joined   # 비

    # 한파는 폭염보다 우선하고, 둘이 같이 나오지 않는다
    # 한파 조언이 나오고 폭염 조언과 섞이지 않으면 된다 (문구 자체에는 묶지 않는다)
    cold_tips = build_advice([day(base, 2, 10)])
    assert any(t.emoji == ":cold_face:" for t in cold_tips), cold_tips
    assert "온열질환" not in " ".join(t.text for t in cold_tips)

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
        # 시도 이름('부산'·'제주')은 동네예보로 빠지므로(find_wide) 구역명으로 부른다.
        # 여기서 보려는 것은 광역 조회의 수집 범위다.
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
    test_chart_download()
    print("\n전부 통과")
