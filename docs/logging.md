# 로그와 디버깅

## 어디를 보나

연·월 폴더 아래 앱 이름과 날짜로 쌓임. 서버를 옮겨 다녀도
찾는 자리가 같음.

```
logs/2026/2026.09/weather-mention.2026-09-12.log         ← INFO 이상 전부
logs/2026/2026.09/weather-mention.error.2026-09-12.log   ← WARNING 이상만
logs/2026/2026.09/weekly-weather.2026-09-12.log          ← 월요일 정기 게시
logs/2026/2026.09/cleanup.2026-09-12.log                 ← 매일 04:00 정리
     └연┘ └─연.월─┘ └────앱 이름────┘ └──날짜──┘
```

| 파일 | 내용 |
|---|---|
| `*.error.{날짜}.log` | **WARNING 이상만.** 오류를 찾을 때 여기부터 봄 |
| `*.{날짜}.log` | INFO 이상 전부. 오류 앞뒤 맥락이 필요할 때 |
| `*.{날짜}.log.gz` | 멘션 봇의 지난 날짜 파일. 자정 회전 때 압축됨 — `zcat`·`zgrep` 으로 봄 |
| `logs/weather-mention.console.log` | 유닛 없이 `bin/start.sh` 로 띄운 멘션 봇의 콘솔. 파이썬이 **뜨기 전에** 죽은 경우(venv 경로, `.env` 누락)를 봄. 띄울 때마다 비움 |
| journal | systemd 로 돌면 콘솔 출력이 여기로 감. `journalctl --user -u weather-mention -n 50` (root 서버는 `sudo journalctl -u weather-mention -n 50`). 주간 게시·정리는 `-u weather-weekly` · `-u weather-cleanup` |

```bash
D=logs/$(date +%Y)/$(date +%Y.%m)
tail -50 "$D"/weather-mention.error.$(date +%F).log
```

날짜를 연·월로 갈라 두는 이유는 한 디렉토리에 파일이 무한정 쌓이면 목록
조회부터 느려지기 때문.

**회전·보관** — 자정을 넘겨 떠 있는 멘션 봇만 loguru 가 회전시킴. 그때 지난
파일을 `gz` 로 압축하고 90일 지난 것을 지움. 한 번 돌고 끝나는 주간 게시·정리
(`weekly-weather.*`·`cleanup.*`)는 회전이 일어나지 않아 `.log` 그대로 남고, 90일 뒤
`bin/cleanup.py`(매일 04:00 `weather-cleanup.timer`, `LOG_KEEP_DAYS`)가 지움 —
loguru 는 회전할 때만 압축·삭제하고, 프로세스가 끝날 때는 하지 않기 때문.
위치는 `LOG_DIR` 환경변수로 옮길 수 있음. `logs/` 는 `.gitignore` 에 있음.

## 오류가 났을 때

```bash
D=logs/$(date +%Y)/$(date +%Y.%m)
tail -50 "$D"/weather-mention.error.$(date +%F).log   # 최근 오류
zcat -f "$D"/*.error.*.log* | grep -c ERROR             # 이번 달 빈도 (압축된 파일 포함, 합계)
```

멘션 봇의 실패는 **질문 원문이 같은 줄에 남음.** 그대로 재현하면 됨. 멘션 처리 줄은
`weather-mention` 로거로 찍힘.

```
2026-09-12 10:15:02 ERROR   weather-mention:on_mention:862 - 응답 생성 실패 user=U0B2… ch=C0BD… ts=1788.001 query='<@U1> 역삼동 날씨'
Traceback (most recent call last):
  ...
```

```bash
.venv/bin/python -c "from src.mention.answer import answer; print(answer('역삼동 날씨').text)"
```

`answer()` 가 멘션의 진입점임. `build_reply()` 는 단풍·꽃 갈래를 건너뛰어 그쪽 질문은
재현되지 않음.

## 로그 읽는 법 — 자주 나오는 것들

### `요청 실패 url=… status=500`
기상청 쪽 장애. 코드 문제가 아님. 월요일 게시 기준으로 통보문이 월~목, 중기예보가 금~ 을 덮음.

- 중기예보만 죽으면 금~일이 비어도(3일) 게시는 계속됨.
- **통보문이 죽으면 월~목 4일이 비어 게시를 포기함.** 이때 뒤이어
  `7일 중 4일의 기온을 얻지 못해… 기상청 페이지 구조가 바뀌었을 수 있습니다` 가 찍히지만
  파서 문제가 아님. 그보다 앞서 찍힌 `수집 실패 — fetch_notice …` 줄로 가려냄.

### `요청 실패` 없이 값만 비었을 때
상태 200 인데 결과가 없으면 **페이지 구조가 바뀐 것**임. 응답 본문이 비정상적으로
작은지 봄(정상은 통보문 80KB·중기예보 130KB 안팎). 크기를 찍는
`요청 성공 url=… status=200 82755B` 는 DEBUG 줄이라 기본(INFO) 로그에는 없음 —
로그 수준을 낮춰 다시 돌림:

```bash
LOG_LEVEL=DEBUG .venv/bin/python -m src.query 부산
```

조회 CLI 는 결과를 stdout 으로 내므로 `LOG_LEVEL` 을 주지 않으면 WARNING 만 남김. 로그는 콘솔(stderr)과
`logs/…/query.{날짜}.log` 에 남음.

### `7일 중 N일의 기온을 얻지 못해…`
뒤에 붙는 문장으로 갈림.

- `지난 날짜라 예보가 없습니다 — 주 중간 실행이면 정상입니다` → **정상.**
  기상청은 지난 날짜를 예보하지 않음. 월요일 정기 게시에서는 나오지 않음.
- `기상청 페이지 구조가 바뀌었을 수 있습니다` → 미래 날짜가 비어 있다는 뜻.
  그보다 앞서 `수집 실패 — fetch_…` 줄이 있으면 기상청 장애, 없으면 **진짜 이상** —
  파서를 봐야 함.

### `슬랙 전송 실패 … error=not_in_channel`
코드가 아니라 슬랙 설정. 해당 채널에서 봇을 초대함.
`missing_scope` 면 토큰 스코프(`chat:write`, `files:write`)를 확인함.
이 꼴은 멘션 봇의 줄임. 주간 게시는 같은 원인을 `봇이 채널(C…)에 없습니다…` /
`토큰 스코프를 확인하세요…` 로 남김.

## 남기지 않는 것

- 슬랙 토큰·`.env` 값 — 어떤 수준에서도 로그에 넣지 않음.
- 사용자 발화는 질문 원문 200자까지만. 재현에 필요한 최소량.
- `slack_bolt`·`slack_sdk`·`urllib3`·`requests` 의 잡담은 WARNING 으로 눌러 뒀음. 예외는 세션 수립 한 줄
  (`A new session has been established`) — 첫 연결과 재연결 성공(대략 5시간마다)을 확인하려고 남김. Bolt 는 앱을
  만들 때 자기 로거를 루트 수준으로 되돌리므로 `src/mention/bot.py` 가 앱을 만든 뒤 필터(`session_only`)로 거름.

## 산출물 보존 — `data/`

로그 바깥에도 쌓이는 것이 있음. dry-run 을 돌릴 때마다 PNG 가 1MB 가까이
남음. 여기는 loguru 가 관여하지 않으므로 `src/common/retention.py` 가 맡음.

```
data/img/weekly-weather-20260914.png   ← 우리가 만든 주간 카드
data/img/foliage-20260914.png          ← 우리가 만든 단풍 지도 (단풍철에만)
data/img/surf_2026091200.png           ← 기상청에서 받아 온 지상일기도
```

**한 자리에 모으고 보존 기간만 파일명으로 가름.** 디렉터리를 나눠 봐야
파일명이 이미 `weekly-weather-*` · `foliage-*` · `surf_*` 로 갈리므로 얻는 것이 없음.
같은 디렉터리를 패턴만 달리해 여러 번 훑음.

| 설정 | 기본 | 대상 |
|---|---|---|
| `CARD_KEEP_DAYS` | `14` | `weekly-weather-*.png` 주간 카드, `foliage-*.png` 단풍 지도 |
| `CHART_KEEP_DAYS` | `30` | `{CHART_PRODUCT}_*.png` 일기도 (기본 `surf_*.png`) |
| `LOG_KEEP_DAYS` | `90` | `logs/` — 주간 게시·정리 로그는 이것만 지움(멘션 봇 로그는 loguru 도 지움) |

일기도가 카드보다 긴 이유는 **다시 받을 수 없기 때문.** 카드는 코드가
언제든 다시 만들지만, 기상청은 일기도를 2일치만 보관함.

셋 다 **`0` 이면 지우지 않음.** «0 = 전부 삭제» 로 읽히면 사고가 나기 때문.

기준은 파일명의 날짜가 아니라 **수정 시각**임. 같은 날짜로 여러 번
덮어써도 마지막 실행 시점이 기준이 되어 «최근에 본 것» 이 살아남음.

정기 게시가 dry-run 으로 돌 때 **이번 산출물을 쓰기 직전에** 지난 것을
치움 — 방금 쓴 파일이 정리 대상에 걸리지 않는 순서.

## 손으로 정리하기 — `bin/cleanup.py`

평소에는 정리 타이머(`weather-cleanup.timer`, 매일 04:00)가 부르므로 손으로 부를 일이 없음.
필요한 때는 봇을 한참 안 돌려 정리가 밀렸을 때, 보존 기간을 줄인 직후 바로 반영하고 싶을 때,
systemd 가 없는 서버에서 cron 으로 정리만 따로 돌릴 때.

```bash
bin/cleanup.py --dry-run                  # 무엇이 지워지는지 먼저 봄
bin/cleanup.py                            # 실제로 지움
bin/cleanup.py --days 30                  # data/ 만 덮어씀
bin/cleanup.py --days 30 --include-logs   # 로그까지 함께
```

어디서 불러도 프로젝트 `.venv` 의 파이썬으로 다시 실행됨(loguru 가 거기에만 있음).

`--days` 는 **로그에 적용되지 않음.** 디스크를 비우려고 `--days 1` 을 쳤다가
90일치 디버깅 기록을 잃는 일이 없도록, 로그는 `--include-logs` 를 명시해야
포함됨.

```
  data/img/weekly-weather-*.png (14일) — 지울 것 1개 145KB
      weekly-weather-20260914.png
  data/img/surf_*.png (30일) — 지울 것 0개 0B
  data/img/foliage-*.png (14일) — 지울 것 0개 0B
  logs/*.log* (90일) — 지울 것 1개 2KB
      2026/2026.06/weekly-weather.2026-06-01.log

지울 수 있음: 2개 147KB
```

(실제 출력의 경로는 절대 경로로 찍힘.)

파일을 다 지우고 남은 `logs/2026/2026.06/` 같은 빈 껍데기도 함께 치움.
슬랙 토큰 없이 돌아가므로 정리만 하는 자리에서도 쓸 수 있음.

**우리가 만든 파일만 지움.** `data/` 는 사용자도 열어 보는 자리라서
`weekly-weather-*.png` · `foliage-*.png` · `surf_*.png` 처럼 패턴으로 좁혀 둠
(`logs/` 는 `*.log*`). 거기 따로 저장해 둔 파일은 아무리 오래돼도 건드리지 않음.

> `data/` 는 **산출물** 자리. 행정동 목록처럼 계속 변하는 참조 자료의
> 스냅샷은 여기 두지 않음 — 그건 매번 기상청에서 받아 옴(`src/kma/dong_zone.py`).

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
