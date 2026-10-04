# 주간 날씨 슬랙 봇

매주 월요일 08:00(KST), 이번 주 날씨 브리핑을 슬랙 채널에 게시한다.
[기존 수동 게시물](https://ajdevhq.slack.com/archives/C03ED58CQLE/p1788217226827099)과 같은 구성이다.

| 구성 요소 | 내용 | 출처 |
|---|---|---|
| 본문 | 복장·우산·태풍 등 **특이사항에 대한 권장 대응** | 기상청 원문 + 규칙 기반 (모델은 선택) |
| 첨부 1 | 주간 전망 **카드 이미지** (원본 AI 검색 캡처와 동일 구성) | 기상청 원문 → Chromium 렌더링 |
| 첨부 2 | 기상청 **지상일기도** PNG | 날씨누리 공개 저장소 |
| 첨부 3 | **단풍 지도** — 9월 둘째 주 ~ 11월 둘째 주에만 | 기상청 현황 + 웨더아이 예상 → Chromium 렌더링 |

**필수 자격증명은 슬랙 봇 토큰 하나뿐이다.** 기상청 API 키도, 검색 API도, 결제도 필요 없다.
카드 문장은 기상청 예보관이 쓴 원문을 그대로 쓰므로 모델도 필요 없다.

```
GitHub Actions / systemd timer (월 07:50 KST 기동)
  ├─ 기상청 예보 통보문 ─── 전국 아침·낮 기온 범위 + 총괄예보관 서술  (D+0~D+4)
  ├─ 기상청 중기예보 ───── 기상전망 + 도시별 기온 + 하늘상태·강수확률 (D+4~D+10)
  ├─ 날씨누리 저장소 ───── 지상일기도 PNG
  ├─ (단풍철) 기상청 단풍현황 + 웨더아이 예상 PDF ── 21개 명산 단풍 지도
  ├─ 모델 ────────────── 위 원문으로 카드 문구 + 본문 작성 (선택, 없으면 규칙 기반)
  └─ 08:00 정각까지 대기 후 files.uploadV2 (본문 + 이미지 2~3장을 한 메시지로)
```

---

## 1. 예보: 기상청 공개 페이지 스크래핑

API 키가 필요 없고 결제도 없다. robots.txt 가 `User-Agent: * / Allow: /` 로 이 경로들을 허용한다.
두 페이지만 쓰고, 둘 다 서버 렌더링이라 `requests` + BeautifulSoup 로 충분하다.

### 예보 통보문 — `/w/forecast/notice.do`

총괄예보관이 쓴 종합 서술과 **전국 최저/최고기온 범위 표**(오늘~그글피, D+0~D+4).

> □ (종합) 당분간 낮과 밤 기온차 큼, 내일까지 풍랑과 너울 유의
> ○ (오늘~그글피, 10~14일) 전국 가끔 구름많음, 글피 오후부터 밤 사이 제주도산지 곳에 따라 비

### 중기예보 — `/w/forecast/overall/mid-term.do`

기상전망 서술 + 도시별 최저/최고기온 표 + 지역별 오전/오후 하늘상태·강수확률 (D+4~D+10).
도시별 값을 날짜별로 모으면 전국 분포 범위가 나온다.

### 기온은 '지역 간 분포 범위'다

`아침 14~22℃` 는 하루의 최저/최고가 **아니다**. 전국 각지의 아침 최저기온이 그 범위에 걸쳐
있다는 뜻이다. 원본 게시물의 "아침 기온 18~24℃, 낮 기온 25~33℃"가 바로 이 형식이고,
`DayForecast` 의 `tmin_lo/tmin_hi`, `tmax_lo/tmax_hi` 가 그것을 그대로 담는다.
특정 도시 하나만 볼 때는 lo 와 hi 가 같은 값이 된다.

### 날짜 커버리지

월요일 아침 기준으로 통보문이 월~금, 중기예보가 금~다음 주 목을 덮어 **월~일 7일이 빈틈없이
채워진다**. 주 중간에 돌리면 지난 요일은 비는데, 이건 정상이다.

### 깨질 수 있다는 점

HTML 구조가 바뀌면 파싱이 실패한다. 그래서 세 겹으로 막았다 (`src/forecast.py`):

1. **범위 검증** — 기온 −35~45℃, 강수확률 0~100 밖의 값은 버리고, lo>hi 면 바로잡는다.
2. **날짜 정렬** — 무엇이 오든 월~일 7칸에 매핑하고, 빠진 날은 경고를 남긴다.
3. **실패 시 게시 포기** — 7일 중 4일 이상 기온이 비면 예외를 던져 **아무것도 올리지 않는다.**

`python -m tests.check_credentials` 가 두 페이지의 파싱 가능 여부를 확인해 준다.
구조가 바뀌면 여기서 먼저 빨간불이 뜬다.

## 2. 일기도: 페이지를 렌더링하지 말고 PNG를 직접 받는다

`analysis.do` 는 아래 정적 저장소의 PNG를 `<img>` 로 띄우기만 하는 뷰어다.

```
https://www.weather.go.kr/w/repositary/image/cht/img/{종류}_{YYYYMMDDHH}.png
```

| 항목 | 내용 |
|---|---|
| 시각 | **UTC** 기준 (`surf_2026091000.png` = 2026-09-10 09시 KST) |
| 발표 주기 | `surf`(지상일기도), `ghmd_s24`(24시간 예상) 모두 **00 / 12 UTC 두 번**뿐 |
| 크기 | 1073×802, 약 600~850 KB |
| 보관 | **약 2일**치만 남고 삭제됨 |

**함정 하나.** 존재하지 않는 시각을 요청하면 404가 아니라 **HTTP 200 + 4 KB HTML 오류 페이지**가
온다. 상태코드가 아니라 PNG 매직바이트(`\x89PNG`)로 검증해야 한다. `src/kma_chart.py` 가 이
검증을 하며 12시간씩 최대 5스텝 거슬러 올라간다.

**게시 시각과의 관계.** 월요일 08:00 에 올리면 최신 일기도는 *전날 21시(12 UTC)* 판이다.
원본 게시물도 같은 이유로 "21KST 31 AUG" 판을 썼다. 당일 09시 판을 쓰려면 `POST_AT=09:10`.

> 보관 기간 때문에 Block Kit `image_url` 로 링크만 걸면 이틀 뒤 채널에서 깨진다.
> 그래서 바이트를 받아 `files.uploadV2` 로 올린다.

## 3. 카드 이미지: HTML → Chromium 캡처

원본 캡처의 구성은 셋이 전부였다 — **하이라이트된 리드 문장 + `기온 전망 및 날씨 흐름` 소제목 +
불릿 3개**, 각각 뒤에 출처 칩. 카드도 딱 그것만 그린다. 제목·표·특이사항 박스를 더하면
캡처처럼 보이지 않는다. 태풍 같은 특이사항은 카드가 아니라 **슬랙 본문**에서 다룬다.

한글 폰트는 macOS 에 기본 탑재(Apple SD Gothic Neo)지만 **리눅스 러너에는 없어서
`fonts-noto-cjk` 를 설치하지 않으면 □□□로 렌더링된다.** 워크플로에 포함해 두었다.

## 4. 문구: 기본은 예보관 원문 그대로 (비용 0)

카드 불릿은 **기상청 예보관이 쓴 문장을 그대로** 쓴다. 모델에게 다시 쓰게 하는 것보다 낫다 —
사람이 쓴 정확한 문장이고, 돈이 들지 않으며, 지어낼 여지가 아예 없다.

원문이 `○ (기온) 이번 예보기간 아침 기온은 13~22℃…` 형태라 괄호 머리말이 마침 원본 캡처의
`초반 (9월 1일~2일):` 과 같은 모양이다. 그대로 라벨로 쓴다.

- `종합` 줄은 슬랙 본문 1문단에, `기온` 줄은 카드 리드에 들어가므로 불릿에서는 뺀다.
- 불릿은 최대 5개. 원본이 3개였고, 많으면 캡처처럼 보이지 않는다.

본문은 원본처럼 **두 문단**이다 — 1문단 날씨(체감 + 예보관 종합 서술, 연결어미로 마감),
빈 줄, 2문단 테마(겉옷·우산 + 이모지).

### 모델을 쓰고 싶다면

| `WRITER` | 비용 | 비고 |
|---|---|---|
| `gemini` (기본) | `GEMINI_API_KEY` 필요 | 검색 없이 생성만 하므로 그라운딩 쿼터와 무관 |
| `claude` | 선불 크레딧 | 문장 품질이 가장 낫다. `uv sync --extra claude` 로 설치 |
| 그 외 값 | **0원** | 예보관 원문 + 규칙 기반 본문 |

**키가 없으면 어느 쪽이든 규칙 기반으로 떨어진다.** 기본값이 `gemini` 라도
`GEMINI_API_KEY` 를 안 넣으면 0원으로 돈다.

어느 백엔드든 실패하면 `none` 과 같은 결과로 폴백한다. 주 1회뿐인 게시를 거르지 않기 위해서다.
모델이 흘리는 반쪽짜리 이모지 코드(`:falling_leaf_`)는 `sanitize()` 가 걸러내고,
`12:30` 같은 시각 표기는 건드리지 않는다.

## 5. 실행: GitHub Actions / 리눅스 서버

주간 게시를 돌릴 수 있는 자리가 둘이다. **둘 다 켜 두면 매주 두 번 올라간다.**

| 방식 | 장점 | 단점 |
|---|---|---|
| **GitHub Actions** | 인프라 0, Secrets 관리, 실행 로그·실패 알림, 수동 재실행 | 크론이 수십 분 지연될 수 있음 → 일찍 트리거 + 정각 대기로 해결 |
| 리눅스 서버 (systemd) | 멘션 봇과 한 자리, 토큰이 외부로 안 나감 | 서버를 직접 돌봐야 함 |

```bash
# GitHub Actions 쪽을 쓸 때 — 서버 타이머를 끈다
sudo systemctl disable --now weather-weekly.timer

# 서버 쪽을 쓸 때 — 워크플로의 schedule: 블록을 지운다 (수동 실행은 남는다)
```

멘션 봇은 상시 연결이라 GitHub Actions 로 옮길 수 없다. 서버에 둔다.

절차는 [`deploy/DEPLOY.md`](deploy/DEPLOY.md) 참고.

## 6. 멘션 봇 (Socket Mode)

`@주간 날씨 부산`, `@주간 날씨 제주 다음주` 로 지역 날씨를 물어볼 수 있다(`src/mention.py`).
주간 게시와 **같은 수집 코드**(`src/kma_scrape.py`)를 쓴다.

**여기서 처음으로 Bolt 와 App-Level Token 이 필요해진다.** 보내기만 할 때는 둘 다 필요 없었다.

Socket Mode 를 고른 이유는 **인바운드 포트·도메인·TLS·리버스 프록시·Signing Secret 이 전부
불필요**하기 때문이다. 나가는 WebSocket 연결 하나뿐이라 서버에 이미 떠 있는 다른 서비스의
ingress 를 건드리지 않는다.

응답은 텍스트로만 한다. 카드 이미지를 붙이면 무거워지고, 실용적으로도 "부산 어때?" 에는
텍스트가 빠르고 낫다. **예외는 단풍 현황 하나다** — "단풍 어디까지 왔어" 에는 21곳을 한눈에
보는 지도가 글보다 낫다. 주간 게시와 같은 지도를 1시간 캐시해 붙이고, Chromium 이 없거나
그리다 실패하면 글로만 답한다. "설악산 단풍" 처럼 산 하나를 물으면 글로 답하고, "주말 내장산
단풍" 처럼 날짜·날씨를 함께 물으면 산 아래 마을 동네예보를 붙인다.

단풍 말 없이 물어도 단풍철이면 단풍이 따라온다. "설악산" · "주말 지리산 등산" 처럼 산 이름이면
산 아래 마을 예보에 그 산의 단풍을 붙이고(단풍철 밖에는 예보만), "강원 날씨" · "서울" 처럼 지역
날씨면 그 지역 산 가운데 물든 곳과 그 기간에 예상된 변화를 한 줄 붙인다. 말할 것이 없으면 붙이지
않고, 단풍 자료를 못 받아 와도 날씨 답은 그대로 나간다. 지역과 산의 짝은 `src/mountains.py`
(`REGION_MOUNTAINS`, 시도는 행정동코드 앞자리).

단풍은 **9월 둘째 주 ~ 11월 둘째 주** 에만 답하고, 그 밖에는 다음 기간을 알려 주며 거절한다.
꽃 개화는 다루지 않는다. 자료 구조는 [`docs/forecast-format.md`](docs/forecast-format.md) 의 단풍 절.

예보는 **1시간 캐시**한다(`MENTION_CACHE_TTL`). 기상청은 하루 네 번만 갱신하므로 멘션마다
긁을 이유가 없고, 남의 서버에 대한 예의이기도 하다.

슬랙 콘솔 설정과 서버 배포는 [`deploy/DEPLOY.md`](deploy/DEPLOY.md) 참고.

---

## 설치

### 1) 슬랙 앱

1. https://api.slack.com/apps → **From an app manifest** → `slack_app_manifest.yaml` 붙여넣기
2. `OAuth & Permissions` → Bot Token Scopes 에 `chat:write`, `files:write`
3. `Install App` → **Bot User OAuth Token** (`xoxb-...`) 복사
4. **게시할 채널에서 `/invite @주간 날씨`**
   비공개 채널은 초대 전까지 봇에게 보이지 않아 `channel_not_found` 로 나온다.

Client Secret · Signing Secret · Verification Token · App-Level Token 은 **전혀 필요 없다.**

앱을 매니페스트가 아니라 직접 만들면 봇 유저가 없어 설치 시
"설치할 봇 사용자가 없습니다" 가 뜬다. `App Home → App Display Name` 에서 이름을 지정하면 된다.

### 2) 로컬 실행

```bash
uv sync                                      # .venv 생성 + uv.lock 대로 설치
uv run python -m playwright install chromium  # 카드 렌더링용 헤드리스 크로뮴
cp .env.example .env   # SLACK_BOT_TOKEN, SLACK_CHANNEL_ID 채우기
set -a && . ./.env && set +a
.venv/bin/python -m tests.check_credentials   # 슬랙·기상청·Chromium 점검 (값은 출력 안 함)
.venv/bin/python -m src.post --dry-run        # data/img/ 에 이미지 2~3장 저장, 본문 출력
```

실제 게시는 `--dry-run` 없이. `--no-wait` 를 붙이면 `POST_AT` 대기를 건너뛴다.

키 없이 배관만 확인하려면 `.venv/bin/python -m tests.test_offline`.

### 3) 예보만 조회

```bash
.venv/bin/python -m src.query              # 이번 주 전국
.venv/bin/python -m src.query 부산          # 지역 지정
.venv/bin/python -m src.query 제주 --week-offset 1 --json
```

광역 구역은 12개다.

```
전국 · 수도권 · 강원 · 영서 · 영동 · 충남 · 충북 · 전남 · 전북 · 경남 · 경북 · 제주
```

- `서울`·`부산`·`청주`·`여수` 같은 도시명도 해당 구역으로 해석한다.
- `중부`·`남부`·`영남`·`호남`·`충청` 은 대응하는 기상청 페이지가 없어 대표 구역으로
  보내되, **무엇으로 바꿔 읽었는지 안내문이 함께 나온다.**
- **동 단위**는 멘션 봇에서 별도 경로로 조회한다(`src/dong.py`, 오늘~3일).
  광역은 10일까지, 그 너머는 1개월 전망(`src/outlook.py`)이 확률로 답한다.
- 못 알아듣는 지역은 임의로 고르지 않고 되묻는다.

Claude Code 에서는 `.claude/skills/kma-weather` 스킬이 이 명령을 대신 불러준다 —
"이번 주 날씨 어때" 하고 물으면 된다.

## 설정값

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SLACK_BOT_TOKEN` | — | **필수.** `xoxb-` 로 시작하는 Bot User OAuth Token |
| `SLACK_CHANNEL_ID` | — | **필수.** `C` 로 시작하는 채널 ID |
| `SLACK_APP_TOKEN` | — | 멘션 봇에만 필요. `xapp-` (Socket Mode) |
| `TZ` | — | **`Asia/Seoul` 을 반드시 둔다.** 로그 파일명·자정 회전·`POST_AT` 이 모두 따른다 |
| `AREA_LABEL` | 지역 정식명 | 카드·본문에 표기할 지역 이름. 비우면 `부산·울산·경남` 식 정식명 |
| `CHART_PRODUCT` | `surf` | `surf`=지상일기도, `ghmd_s24`=24시간 예상일기도 |
| `POST_AT` | `08:00` | 게시 시각(KST). `09:10` 이면 당일 09시 판 일기도를 쓴다 |
| `WRITER` | `gemini` | `gemini` / `claude` / 그 외 값이면 규칙 기반. 키가 없으면 규칙 기반으로 폴백 |
| `REGION` | `전국` | 광역 구역. `부산`·`청주` 같은 도시명, `중부`·`영남`·`영동` 같은 지명도 인식 |
| `CARD_SCALE` | `2` | 카드 PNG 배율 |
| `LOG_LEVEL` | `INFO` | `DEBUG` 면 요청 URL·응답 크기까지 남는다 (파서가 의심스러울 때) |
| `LOG_DIR` | `logs/` | 로그를 저장소 밖에 둘 때만 |
| `CARD_KEEP_DAYS` | `14` | `data/img/weekly-weather-*.png` 보존일. `0` 이면 지우지 않는다 |
| `CHART_KEEP_DAYS` | `30` | `data/img/surf_*.png` 보존일. 일기도는 기상청도 2일치만 보관해 다시 못 받는다 |
| `LOG_KEEP_DAYS` | `90` | `logs/` 보존일 (평소엔 loguru 가 처리) |

전체 목록과 주석은 [`.env.example`](.env.example) 참고.

## 로그와 산출물

```
logs/2026/2026.09/weekly-weather.2026-09-12.log         INFO 이상 전부
logs/2026/2026.09/weekly-weather.error.2026-09-12.log   WARNING 이상만
data/img/weekly-weather-20260914.png                    dry-run 산출물
data/img/surf_2026091200.png
```

사내 다른 저장소(`brifo` · `cs-auto-qa`)와 같은 배치다. 자정 회전·90일 보관·gz
압축은 loguru 가 맡고, `data/` 는 `src/retention.py` 가 보존 기간 뒤 지운다.
밀린 정리는 `bin/cleanup.py --dry-run` 으로 먼저 확인하고 돌린다.

읽는 법과 디버깅 요령은 [`docs/logging.md`](docs/logging.md).

## 파일 구조

```
src/kma_scrape.py           기상청 두 페이지 수집·파싱 (수집 로직의 단일 출처)
src/forecast.py             월~일 7일 조립 + 검증 (실패 시 게시 포기)
src/outlook.py              1개월 전망 (10일 너머는 값이 아니라 확률)
src/foliage.py              단풍 현황(기상청) + 예상(웨더아이 PDF) + 다루는 기간
src/mountains.py            기상청 단풍 관측 21개 명산 (좌표 · 별칭 · 산 아래 행정동)
src/render_foliage.py       단풍 지도 HTML → Chromium 캡처
src/assets/korea_provinces.json  지도 윤곽 (Natural Earth, 퍼블릭 도메인)
src/writer.py               한 번 호출로 카드 문구 + 본문, 규칙 기반 폴백
src/render_card.py          HTML → 헤드리스 Chromium 캡처 (카드 PNG)
src/kma_chart.py            일기도 PNG 다운로드 (매직바이트 검증 + 시각 백트래킹)
src/post.py                 게시 엔트리포인트 (대기 → 이미지 2~3장 업로드)
src/query.py                조회 CLI (게시 없이 결과만)
src/mention.py              멘션 응답 봇 (Socket Mode)
src/dong.py                 동 단위 동네예보 (오늘~3일, 행정동 검색)
src/advice.py               수치에서 생활 조언 (일교차·한파·폭염·비·특이사항)
src/cache.py                예보 TTL 캐시
src/config.py               환경변수 → 설정 객체
src/logsetup.py             로그 초기화 (loguru 단일 출구 + 표준 logging 브리지)
src/retention.py            보존 기간 지난 산출물 정리
bin/cleanup.py              data/ · logs/ 수동 정리 (--dry-run 먼저)
bin/start.sh · stop.sh      멘션 봇·타이머 켜고 끄기 (systemd 유닛이 없으면 직접 띄운다)
deploy/_env.sh              .env 로더 (run-weekly.sh · run-mention.sh 공용)
deploy/run-weekly.sh        주간 게시 진입점 (월 1회, 끝나면 종료)
deploy/run-mention.sh       멘션 봇 진입점
deploy/DEPLOY.md            슬랙 콘솔 설정 + 서버(systemd) 배포 가이드
deploy/weather-*.service    systemd 유닛 (멘션 상시 / 주간 게시 / 정리 + 각 타이머)
docs/forecast-format.md     예보 자료 구조·출처·검증 (파싱 근거)
docs/logging.md             로그 읽는 법 · 디버깅 · 보존 기간
.claude/skills/kma-weather  Claude Code 에서 바로 물어보는 스킬
tests/test_offline.py       키 없이 도는 검증
tests/check_credentials.py  슬랙·기상청 페이지·Chromium 점검
```
