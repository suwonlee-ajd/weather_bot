# 로그와 디버깅

## 어디를 보나

연·월 폴더 아래 앱 이름과 날짜로 쌓임. 서버를 옮겨 다녀도
찾는 자리가 같음.

```
logs/2026/2026.09/weather-mention.2026-09-12.log         ← INFO 이상 전부
logs/2026/2026.09/weather-mention.error.2026-09-12.log   ← WARNING 이상만
logs/2026/2026.09/weekly-weather.2026-09-12.log          ← 월요일 정기 게시
     └연┘ └─연.월─┘ └────앱 이름────┘ └──날짜──┘
```

| 파일 | 내용 |
|---|---|
| `*.error.{날짜}.log` | **WARNING 이상만.** 오류를 찾을 때 여기부터 봄 |
| `*.{날짜}.log` | INFO 이상 전부. 오류 앞뒤 맥락이 필요할 때 |
| `/tmp/*.boot.log` | 파이썬이 **뜨기 전에** 죽은 경우만 (venv 경로, `.env` 누락) |

```bash
D=logs/$(date +%Y)/$(date +%Y.%m)
tail -50 "$D"/weather-mention.error.$(date +%F).log
```

날짜를 연·월로 갈라 두는 이유는 한 디렉토리에 파일이 무한정 쌓이면 목록
조회부터 느려지기 때문.

**회전·보관** — loguru 가 자정에 새 파일로 넘기고, 90일 뒤 지우고, 지난
파일은 `gz` 로 압축함. 지우는 코드를 따로 쓰지 않음. 위치는 `LOG_DIR`
환경변수로 옮길 수 있음. `logs/` 는 `.gitignore` 에 있음.

## 오류가 났을 때

```bash
D=logs/$(date +%Y)/$(date +%Y.%m)
tail -50 "$D"/weather-mention.error.$(date +%F).log   # 최근 오류
grep -hc ERROR "$D"/*.error.*.log                      # 이번 달 빈도
```

멘션 봇의 실패는 **질문 원문이 같은 줄에 남음.** 그대로 재현하면 됨.

```
ERROR weather-mention: 응답 생성 실패 user=U0B2… ch=C0BD… ts=1788.001 query='<@U1> 역삼동 날씨'
Traceback (most recent call last):
  ...
```

```bash
.venv/bin/python -c "from src.mention import build_reply; print(build_reply('역삼동 날씨'))"
```

## 로그 읽는 법 — 자주 나오는 것들

### `요청 실패 url=… status=500`
기상청 쪽 장애. 코드 문제가 아님. 통보문과 중기예보 중 하나만 죽으면
나머지로 채워 게시는 계속됨 (`수집 실패 — fetch_notice …` 한 줄만 남고 끝).

### `요청 실패` 없이 값만 비었을 때
상태 200 인데 결과가 없으면 **페이지 구조가 바뀐 것**임. 그날의 `*.log` 에서
`요청 성공 url=… 4123B` 처럼 본문이 비정상적으로 작은지 확인함
(정상은 수십 KB). 확인하려면 로그 수준을 낮춤:

```bash
LOG_LEVEL=DEBUG .venv/bin/python -m src.query 부산
```

### `7일 중 N일의 기온을 얻지 못해…`
뒤에 붙는 문장으로 갈림.

- `지난 날짜라 예보가 없습니다 — 주 중간 실행이면 정상입니다` → **정상.**
  기상청은 지난 날짜를 예보하지 않음. 월요일 정기 게시에서는 나오지 않음.
- `기상청 페이지 구조가 바뀌었을 수 있습니다` → **진짜 이상.** 미래 날짜가
  비어 있다는 뜻. 파서를 봐야 함.

### `슬랙 전송 실패 … error=not_in_channel`
코드가 아니라 슬랙 설정. 해당 채널에서 봇을 초대함.
`missing_scope` 면 토큰 스코프(`chat:write`, `files:write`)를 확인함.

## 남기지 않는 것

- 슬랙 토큰·`.env` 값 — 어떤 수준에서도 로그에 넣지 않음.
- 사용자 발화는 질문 원문 200자까지만. 재현에 필요한 최소량.
- `slack_bolt` / `urllib3` 의 연결 잡담은 WARNING 으로 눌러 뒀음.

## 산출물 보존 — `data/`

로그 바깥에도 쌓이는 것이 있음. dry-run 을 돌릴 때마다 PNG 가 1MB 가까이
남음. 여기는 loguru 가 관여하지 않으므로 `src/retention.py` 가 맡음.

```
data/img/weekly-weather-20260914.png   ← 우리가 만든 주간 카드
data/img/surf_2026091200.png           ← 기상청에서 받아 온 지상일기도
```

**한 자리에 모으고 보존 기간만 파일명으로 가름.** 디렉터리를 나눠 봐야
파일명이 이미 `weekly-weather-*` 와 `surf_*` 로 갈리므로 얻는 것이 없음.
같은 디렉터리를 패턴만 달리해 두 번 훑음.

| 설정 | 기본 | 대상 |
|---|---|---|
| `CARD_KEEP_DAYS` | `14` | `weekly-weather-*.png` 주간 카드 |
| `CHART_KEEP_DAYS` | `30` | `surf_*.png` 일기도 |
| `LOG_KEEP_DAYS` | `90` | `logs/` (평소엔 loguru 가 처리) |

일기도가 카드보다 긴 이유는 **다시 받을 수 없기 때문.** 카드는 코드가
언제든 다시 만들지만, 기상청은 일기도를 2일치만 보관함.

셋 다 **`0` 이면 지우지 않음.** «0 = 전부 삭제» 로 읽히면 사고가 나기 때문.

기준은 파일명의 날짜가 아니라 **수정 시각**임. 같은 날짜로 여러 번
덮어써도 마지막 실행 시점이 기준이 되어 «최근에 본 것» 이 살아남음.

정기 게시가 dry-run 으로 돌 때 **이번 산출물을 쓰기 직전에** 지난 것을
치움 — 방금 쓴 파일이 정리 대상에 걸리지 않는 순서.

## 손으로 정리하기 — `bin/cleanup.py`

평소에는 부를 일이 없음. 필요한 때는 봇을 한참 안 돌려 정리가 밀렸을 때,
보존 기간을 줄인 직후 바로 반영하고 싶을 때, cron 으로 정리만 따로 돌릴 때.

```bash
bin/cleanup.py --dry-run                  # 무엇이 지워지는지 먼저 봄
bin/cleanup.py                            # 실제로 지움
bin/cleanup.py --days 30                  # data/ 만 덮어씀
bin/cleanup.py --days 30 --include-logs   # 로그까지 함께
```

`--days` 는 **로그에 적용되지 않음.** 디스크를 비우려고 `--days 1` 을 쳤다가
90일치 디버깅 기록을 잃는 일이 없도록, 로그는 `--include-logs` 를 명시해야
포함됨.

```
data/img/weekly-weather-*.png (14일) — 지울 것 1개 145KB
    weekly-weather-20260914.png
data/img/surf_*.png (30일) — 지울 것 0개 0B
logs/*.log* (90일) — 지울 것 1개 2KB
    2026/2026.06/weekly-weather.2026-06-01.log

지울 수 있음: 2개 147KB
```

파일을 다 지우고 남은 `logs/2026/2026.06/` 같은 빈 껍데기도 함께 치움.
슬랙 토큰 없이 돌아가므로 정리만 하는 자리에서도 쓸 수 있음.

**우리가 만든 파일만 지움.** `data/` 는 사용자도 열어 보는 자리라서
`weekly-weather-*.png` · `surf_*.png` · `*.log*` 처럼 패턴으로 좁혀 둠.
거기 따로 저장해 둔 파일은 아무리 오래돼도 건드리지 않음.

> `data/` 는 **산출물** 자리. 행정동 목록처럼 계속 변하는 참조 자료의
> 스냅샷은 여기 두지 않음 — 그건 매번 기상청에서 받아 옴(`src/dong.py`).

## 시간대

로그 파일명과 자정 회전은 **프로세스의 시간대**를 따름. 서버가 UTC 면
KST 새벽 0~9시 로그가 전날 파일에 들어가고, 회전도 KST 09시에 일어남 —
근무 시간 한가운데서 파일이 갈림.

그래서 실행하는 모든 자리에 `TZ=Asia/Seoul` 을 박아 둠.

| 자리 | 어디에 |
|---|---|
| systemd | `Environment=TZ=Asia/Seoul` |
| GitHub Actions | 워크플로 최상단 `env:` |
| 로컬·수동 실행 | `.env` 의 `TZ` |

systemd 도 셸을 거치지 않아 로그인 셸의 `TZ` 를 물려받지 않음.
유닛 파일의 `Environment=` 에 직접 넣어야 함.
