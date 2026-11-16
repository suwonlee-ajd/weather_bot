# weather-bot — 주간 날씨 슬랙 봇

기상청 공개 예보로 **매주 월요일 아침 이번 주 날씨를 슬랙 채널에 올리고**, 멘션으로 물으면
지역·동네·산의 날씨와 단풍·첫눈 소식을 답하는 봇.

- **API 키 없이 동작함.** 기상청 날씨누리의 공개 페이지를 읽음. 필수 자격증명은 슬랙 봇 토큰 하나.
- **지어낸 날씨를 올리지 않음.** 기온은 기상청 수치 그대로, 서술은 예보관 원문을 인용하고, 수집이 실패하면 게시를 건너뜀.
- **모델은 선택임.** 기본은 예보관 원문 + 규칙 기반 문장(비용 0). 원하면 Gemini·Claude 로 다듬음.
- **철마다 소식을 붙임.** 벚꽃 · 장마 · 더위 · 단풍 · 첫눈. 기간은 정해 두지 않고 자료가 정함 — 벚꽃·단풍은 기상청이 관측하는
  동안(`isService`)과 관측 전 웨더아이 첫 예상일까지, 장마는 예보관 서술에 장마·정체전선이 있을 때, 더위는 그 주
  예보가 기상청 폭염일(낮 최고 33℃↑)·열대야(밤 최저 25℃↑) 기준에 닿거나 예보관이 폭염·열대야를 말할 때,
  첫눈은 최근 관측이 있거나 아직인 곳에 눈 예보가 있을 때.
- **태풍이 있으면 글로 알림.** 예보관 서술에 태풍이 나오고 기상청 태풍정보에 진행 중인 태풍이 있을 때만 이름 ·
  현재 위치 · 중심기압 · 최대풍속, 그 주 안의 예상 위치, 예보관 서술의 태풍 줄을 실음. 예보관이 말하지 않는 먼
  태풍은 싣지 않음. 지도는 따로 없음 — 지상일기도에 보임.

## 미리 보기

월요일 08:00(KST)에 이런 글 하나와 이미지 2~3장이 한 메시지로 올라감.

```text
이번 주 전국 출/퇴근 날씨는 아침 *2~20℃*, 낮 *20~28℃* 분포가 예상됩니다. 기상청은
"*모레까지 아침 기온 낮아 쌀쌀, 제주도해상 중심 높은 물결 유의*"라고 전하고 있습니다.

*10/7(수)에는* 아침 최저 2도까지 내려가고, *10/8(목)에는* 일교차가 16도 안팎으로
벌어지겠습니다. 따뜻하게 껴입으시고 실내 온도도 살펴 주세요. :cold_face:

:maple_leaf: *이번 주 단풍*
• 관측 — *설악산* 첫단풍 9/28 (예상보다 5일 빠름) · *오대산* 첫단풍 10/1 (예상보다 6일 빠름), 나머지 19곳은 단풍 전
• 이번 주 — 첫단풍 *치악산* 10/10 (예상)

_지상일기도 (10월 04일 21시 KST 기준) · 기상청_
_단풍 지도 · 현황 기상청 날씨누리 · 예상 웨더아이(9/4 발표)_
```

| 첨부 | 내용 |
|---|---|
| 주간 전망 카드 | 리드 문장 + 예보관 서술 불릿을 그린 PNG (헤드리스 Chromium) |
| 지상일기도 | 기상청이 올린 최신 PNG 그대로 |
| 단풍 지도 | 기상청 단풍 관측 중에만 — 21개 명산의 현황과 예상 |
| 첫눈 지도 | 첫눈 소식이 있을 때만 — 계절관측 24곳의 올해 첫눈과 평년·지난겨울 |
| 벚꽃 지도 | 벚꽃 소식이 있을 때만 — 웨더아이 19개 도시의 개화 예상 (한 장, 기상청 군락지 관측은 글로) |
| 더위 지도 | 더위 소식이 있고 중기예보 도시별 값이 있을 때만 — 41곳의 그 기간 낮 최고(🥵 33℃↑)와 기준에 닿는 도시 표 |

멘션 봇은 이렇게 답함.

| 물음 | 답 |
|---|---|
| `@날씨 알리미 제주 다음주` | 광역 구역의 7일 예보 (최대 10일) |
| `@날씨 알리미 부산` · `@날씨 알리미 역삼동` | 시도·동 단위 동네예보 (오늘부터 4일, 17시 이후 발표면 5일) |
| `@날씨 알리미 주말 지리산 등산` | 산 아래 마을 동네예보 + 단풍철이면 그 산의 단풍 |
| `@날씨 알리미 단풍 어디까지 왔어` | 21개 명산 단풍 지도 |
| `@날씨 알리미 첫눈 언제 와` · `@날씨 알리미 서울 첫눈` | 24곳 첫눈 지도 · 지점별 관측과 평년 |
| `@날씨 알리미 다음 달` | 1개월 전망 (주 단위 확률) |
| `@날씨 알리미 우산 챙길까` | 물은 것(우산·옷차림·야외 등)에 맞춘 조언 |

## 빠른 시작

필요한 것: [uv](https://docs.astral.sh/uv/), 앱을 설치할 수 있는 슬랙 워크스페이스.
파이썬은 uv 가 `.python-version` 대로 받음(3.12 이상).

### 1. 슬랙 앱

1. https://api.slack.com/apps → **Create New App → From an app manifest** →
   [`slack_app_manifest.yaml`](slack_app_manifest.yaml) 붙여넣기
2. **Install App** → Bot User OAuth Token(`xoxb-…`) 복사
3. 게시할 채널에서 `/invite @날씨 알리미` — 비공개 채널은 초대 전까지 `channel_not_found` 로 나옴
4. 멘션 봇도 쓸 거라면 **Basic Information → App-Level Tokens** 에서 `connections:write`
   스코프로 토큰(`xapp-…`)을 만듦. 매니페스트로는 만들 수 없음.

### 2. 설치와 점검

```bash
git clone <this repo> weather_bot && cd weather_bot
uv sync                                         # .venv + uv.lock 대로 설치
uv run python -m playwright install chromium    # 카드·지도 렌더링용
cp .env.example .env                            # SLACK_BOT_TOKEN · SLACK_CHANNEL_ID (멘션 봇은 SLACK_APP_TOKEN 도)
chmod 600 .env

set -a && . ./.env && set +a
.venv/bin/python -m tests.check_credentials     # 슬랙·기상청·Chromium 점검 (토큰 값은 출력하지 않음)
.venv/bin/python -m src.weekly --dry-run          # 슬랙에 보내지 않고 본문 출력 + data/img/ 에 이미지 저장
```

리눅스에서는 한글 글꼴(`fonts-noto-cjk`)이 없으면 카드가 □□□ 로 그려짐.

### 3. 실행

```bash
.venv/bin/python -m src.weekly              # POST_AT(기본 08:00 KST) 60분 전 안쪽이면 그때까지 기다렸다가 게시, 아니면 바로 게시
.venv/bin/python -m src.weekly --no-wait    # 지금 바로 게시
.venv/bin/python -m src.mention           # 멘션 봇 (Socket Mode, 상시 실행)
```

서버에 상시로 두는 방법(systemd 유닛·타이머, sudo 없는 서버의 `systemd --user`)은
[`deploy/DEPLOY.md`](deploy/DEPLOY.md) 에 있음.

## 설정

`.env` 로 정함. 전체 목록과 설명은 [`.env.example`](.env.example).

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SLACK_BOT_TOKEN` | — | **필수.** `xoxb-` 로 시작하는 Bot User OAuth Token |
| `SLACK_CHANNEL_ID` | — | **필수.** `C` 로 시작하는 채널 ID (채널 이름이 아님) |
| `SLACK_APP_TOKEN` | — | 멘션 봇에만 필요. `xapp-` (Socket Mode) |
| `TZ` | — | **`Asia/Seoul` 로 둠.** 로그 파일명·자정 회전이 따름 (`POST_AT` 은 TZ 와 무관하게 늘 KST) |
| `REGION` | `전국` | 주간 게시의 광역 구역. `부산`·`청주` 같은 도시명, `영남`·`영동` 같은 지명도 알아들음 |
| `AREA_LABEL` | 구역 정식명 | 카드·본문에 쓸 지역 이름 |
| `POST_AT` | `08:00` | 게시 시각(KST). 기동이 이 시각 60분 전 안쪽이어야 기다림 — 더 이르면 바로 게시함. 일기도는 기동 시각 기준 최신 판(월 07:50 기동이면 전날 21시 판) |
| `CHART_PRODUCT` | `surf` | `surf`=지상일기도, `ghmd_s24`=24시간 예상일기도 |
| `WRITER` | `none` | 문장을 쓸 모델. `none`(규칙 기반) · `gemini` · `claude`. **키나 패키지가 없으면 규칙 기반으로 떨어짐** |
| `CARD_SCALE` | `2` | 카드 PNG 배율 |
| `MENTION_CACHE_TTL` | `3600` | 멘션 봇이 광역 예보·단풍 지도·첫눈 지도를 들고 있는 시간(초). 시도·동 동네예보는 멘션마다 새로 받음 |
| `LOG_LEVEL` | `INFO` | `DEBUG` 면 요청 URL·응답 크기까지 남음 |
| `CARD_KEEP_DAYS` · `CHART_KEEP_DAYS` | `14` · `30` | dry-run 산출물 보존일. `0` 이면 지우지 않음 |
| `LOG_KEEP_DAYS` | `90` | 로그 보존일 — `bin/cleanup.py`(정리 타이머)만 씀. 주간 게시·정리 로그는 이 값으로만 지워짐. 멘션 봇 로그는 loguru 가 이 값과 무관하게 90일 뒤 지움. `0` 이면 정리 타이머가 로그를 지우지 않음 |

### 모델을 쓰고 싶다면

| `WRITER` | 설치 | 필요한 키 | 비고 |
|---|---|---|---|
| `none` (기본) | — | — | 예보관 원문 + 규칙 기반 문장 (비용 0) |
| `gemini` | `uv sync --extra gemini` | `GEMINI_API_KEY` | 검색 없이 생성만 하므로 무료 티어로 동작함 |
| `claude` | `uv sync --extra claude` | `ANTHROPIC_API_KEY` | 선불 크레딧 필요 |

`tests.check_credentials` 가 고른 모델의 패키지와 키를 점검함.

extra 는 이후 `uv sync` 마다 함께 줌 — `uv sync` 는 요청하지 않은 패키지를 지우므로, 빼면
그 패키지가 사라져 규칙 기반 문장으로 떨어짐.

어느 모델이든 실패하면 규칙 기반 문장으로 게시함 — 주 1회뿐인 게시를 거르지 않음.

## 동작 방식

```
systemd timer (월 07:50 KST 기동) — 또는 크론을 넣은 GitHub Actions (deploy/DEPLOY.md §4)
  ├─ 기상청 예보 통보문 ─── 전국 아침·낮 기온 범위 + 총괄예보관 서술  (오늘~3일 뒤, 오전 발표 기준)
  ├─ 기상청 중기예보 ───── 기상전망 + 도시별 기온 + 하늘상태·강수확률 (4~10일 뒤)
  ├─ 날씨누리 저장소 ───── 지상일기도 PNG
  ├─ (태풍) 날씨누리 태풍정보 목록 + 경로표 ─ 태풍 문단 (글만)
  ├─ (단풍철) 기상청 단풍 현황 + 웨더아이 예상 PDF ── 단풍 문단 + 지도
  ├─ (첫눈철) 기상자료개방포털 계절관측 + 그 주 예보의 눈 ─ 첫눈 문단 + 지도
  ├─ (벚꽃철) 기상청 군락지 관측 + 웨더아이 예상 PDF ─ 벚꽃 문단 + 지도
  ├─ (여름) 위 예보의 기온·하늘상태와 예보관 서술 ─── 장마 · 더위 문단 + 더위 지도(중기예보 도시별, 따로 받지 않음)
  ├─ (선택) 모델 ────────── 위 원문으로 카드 문구 + 본문
  └─ POST_AT 까지 대기 → files.uploadV2 (본문 + 이미지를 한 메시지로)
```

알아 두면 좋은 것들:

- **기온은 '지역 간 분포 범위'임.** `아침 14~22℃` 는 하루의 최저/최고가 아니라 전국 각지의
  아침 최저기온이 그 범위에 걸쳐 있다는 뜻. 한 도시만 보면 두 값이 같아짐.
- **월요일 아침에 돌면 월~일 7일이 빈틈없이 채워짐.** 통보문이 월~목, 중기예보가 금~다음 주를
  덮음. 주 중간에 돌리면 지난 요일은 빔(정상).
- **페이지 구조가 바뀌면 게시를 포기함.** 값의 범위를 검증하고 월~일 7칸에 맞춰 놓은 뒤,
  7일 중 4일 이상 기온이 비면 아무것도 올리지 않음(`src/weekly/forecast.py`).
- **주간 게시는 헬스체크 → 영역 동시 실행 → 종합 → 전송.** 헬스체크(`src/weekly/health.py`)는 슬랙만
  필수 — 실패하면 아무것도 돌리지 않음. Chromium 이 없으면 카드·지도 없이 글만 올림. 영역(날씨 · 카드 ·
  일기도 · 벚꽃 · 장마 · 폭염 · 태풍 · 단풍 · 첫눈)은 동시에 돌고(`src/weekly/pipeline.py`), 날씨만 필수 — 나머지는 실패하거나
  5분 안에 끝나지 않으면 그 영역만 빠짐.
- **일기도는 페이지를 렌더링하지 않고 PNG 를 직접 받음.** 없는 시각을 요청하면 404 가 아니라
  HTTP 200 + HTML 오류 페이지가 오므로 PNG 매직바이트로 검증하고, 12시간씩 거슬러 올라감.
  기상청은 이틀치만 보관해서 링크 대신 파일을 올림.
- **멘션 봇은 Socket Mode.** 인바운드 포트·도메인·TLS·리버스 프록시가 필요 없음.
  광역 예보는 1시간 캐시함(`MENTION_CACHE_TTL`) — 기상청은 하루 네 번만 갱신함. 시도·동 동네예보는
  멘션마다 새로 받음.

자료 구조와 파싱 근거는 [`docs/forecast-format.md`](docs/forecast-format.md),
로그 읽는 법은 [`docs/logging.md`](docs/logging.md).

## 예보만 조회하기

슬랙 없이 터미널에서 결과만 봄.

```bash
.venv/bin/python -m src.query                          # 이번 주 전국
.venv/bin/python -m src.query 부산                      # 지역 지정
.venv/bin/python -m src.query 제주 --week-offset 1 --json
.venv/bin/python -m src.query --foliage 설악산           # 단풍 현황·예상
.venv/bin/python -m src.query --snow 서울                # 첫눈 관측·평년
```

광역 구역은 `전국 · 수도권 · 강원 · 영서 · 영동 · 충남 · 충북 · 전남 · 전북 · 경남 · 경북 · 제주`
12개. 기상청 페이지가 따로 없는 `중부`·`영남`·`호남` 같은 말은 대표 구역으로 바꿔 읽고, 바꿨다는
안내를 함께 냄. 못 알아듣는 지역은 임의로 고르지 않고 되물음.

## 프로젝트 구조

기능별 패키지. 의존은 `common` ← `kma` · `season` · `advice` ← `weekly` · `mention` 방향으로만.

```
src/common/     설정 · 로그 · 캐시 · 산출물 보존 · 날짜·기온 표기 · HTML → PNG
src/kma/        기상청 수집 — 광역 구역(regions) · 통보문(notice) · 중기예보(mid_term) · 합치기(scrape)
                · 동네예보(dong_zone · dong_forecast) · 1개월 전망(outlook) · 일기도(chart) · 태풍정보(typhoon)
src/season/     철 소식 자료 — 주제마다 자료(data) · 문장(text) · 지도(map)
                · 단풍(foliage/ + 명산 mountains) · 첫눈(snow/ + 관측 지점 stations)
                · 벚꽃(blossom/ + 군락지·도시 spots) · 장마(monsoon/) · 더위(heat/ + 도시 cities) — 그 주 예보에서 읽음
                · 공통 — 수집(sources) · 지도 바탕(basemap) · 관측 한 줄 꼴(summary) · 주의 시작(weeks)
                · 예보관 서술 인용(narrative)
src/advice/     수치에서 생활 조언 — 규칙(rules) · 문구 표(phrases)
src/weekly/     주간 게시 — 진입점(post) · 헬스체크(health) · 영역 동시 실행·종합(pipeline)
                · 날씨·카드·일기도 영역(sections) · 철 소식·태풍 영역(themes) · 7일 조립(forecast)
                · 본문(body · writer) · 카드(card) · 문단(paragraph)
src/mention/    멘션 봇 — 슬랙 연결(bot) · 답 고르기(answer) · 질문 해석(parse) · 문구(texts)
                · 답의 꼴(reply) · 광역 예보 캐시(forecast)
                · 날씨 답(weather/ 광역 region · 동네 dong) · 단풍 답(foliage/ reply · note)
                · 첫눈 답(snow/ reply · note) — reply 는 단독 답, note 는 날씨 답 끝의 한 줄
src/query/      조회 CLI (게시 없이 결과만) — 날씨·인자(week) · 단풍·첫눈(season)
bin/            멘션 봇·타이머 켜고 끄기(start.sh · stop.sh) · data/ · logs/ 정리(cleanup.py, --dry-run 먼저)
deploy/         systemd 유닛 · 실행 스크립트 · 배포 가이드
docs/           예보 자료 구조 · 로그 · 문체 기준 · 코드 스타일
tests/          토큰 없이 도는 검증(test_offline.py) · 슬랙·기상청·Chromium 점검(check_credentials.py)
```

## 개발

```bash
uv sync                                     # dev 그룹(ruff)까지 설치. 모델 extra 를 쓰면 --extra 도 함께 — 빼면 지워짐
.venv/bin/python -m tests.test_offline      # 토큰 없이 도는 검증
uv run ruff check src tests bin
```

조언·게시 문구를 고칠 때는 [`docs/writing-style.md`](docs/writing-style.md) 의 문체 기준을 따름.

이슈와 풀 리퀘스트를 환영함. 기상청 페이지 구조가 바뀌어 파싱이 깨졌다면
`LOG_LEVEL=DEBUG` 로 한 번 돌린 로그(응답 크기·URL)를 함께 올려 주면 빨리 고칠 수 있음.

## 남은 작업

2027년 벚꽃 소식 전(웨더아이 예상 발표 2월 하순)에 함.

- **주간 벚꽃 문단 구성을 다시 봄.** 3줄이라 길고, 관측(군락지 13곳)과 예상(도시 19곳)의 장소가 섞여
  읽힘. 지도는 도시만 그려 갈랐지만 문단은 그대로임. 줄 구성은 `src/weekly/themes.py`, 문단 모양은
  `src/weekly/paragraph.py` 에 있음.
- **벚꽃 지도를 실제 철에 확인함.** 군락지 좌표(`src/season/blossom/spots.py`)는 벚꽃길 한가운데쯤으로 잡은
  어림값이고, 철 중간 관측은 지어낸 값으로만 그려 봄. 2027년 3월 첫 게시 때 라벨 겹침과 표를 봄.

## 데이터 출처

| 출처 | 쓰는 자료 |
|---|---|
| [기상청 날씨누리](https://www.weather.go.kr) | 예보 통보문, 중기예보, 동네예보, 1개월 전망, 지상일기도, 태풍정보, 단풍·벚꽃 관측 |
| [기상자료개방포털](https://data.kma.go.kr) | 첫눈 관측(계절관측 24곳)과 평년값 |
| [웨더아이](https://www.weatheri.co.kr) | 단풍·벚꽃 예상 시기 (해마다 올리는 PDF) |
| [Natural Earth](https://www.naturalearthdata.com) | 단풍·첫눈·벚꽃·더위 지도의 시도 윤곽 (퍼블릭 도메인) |
| [Noto Emoji](https://github.com/googlefonts/noto-emoji) | 단풍·첫눈·벚꽃·더위 지도 표지 🍁 🍂 ❄️ 🌸 🥵 (Apache License 2.0, `src/season/assets/noto-emoji/`) |

- 이 프로젝트는 기상청·웨더아이와 관계가 없는 비공식 도구.
- 게시물마다 출처를 밝힘. 자료를 다시 퍼뜨리거나 상업적으로 쓰려면 각 출처의 이용 조건을 먼저 확인함.
- 남의 서버를 읽는 도구이므로 요청을 아낌 — 멘션 봇의 광역 예보는 한 시간, 단풍 예상은 하루, 단풍 현황과 첫눈 관측은 한 시간, 태풍정보는 30분 들고 있음.

## 라이선스

[Apache License 2.0](LICENSE)
