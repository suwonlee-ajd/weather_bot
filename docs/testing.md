# 테스트 가이드

무엇을 어떤 순서로 확인하는지, 그리고 **어디가 자주 깨지는지** 적는다.
명령어 목록은 [`README.md`](../README.md) 에도 있다. 여기서는 그 명령이
무엇을 보장하고 무엇을 보장하지 않는지에 집중한다.

모든 명령은 프로젝트 루트에서 돌린다.

```bash
cd /home/ajung/workspace/weather_bot
set -a; . ./.env; set +a        # 파이썬은 .env 를 스스로 읽지 않는다
```

> `set -a` 를 빼먹으면 `RuntimeError: 환경변수 SLACK_BOT_TOKEN 가 필요합니다`
> 로 죽는다. 코드 문제가 아니다.

## 순서 — 아래로 갈수록 느리고 외부에 의존한다

| | 명령 | 걸리는 시간 | 외부 의존 |
|---|---|---|---|
| 1 | `.venv/bin/ruff check src/ tests/` | 1초 | 없음 |
| 2 | `.venv/bin/python -m tests.test_offline` | 30초 | 기상청(일기도만) |
| 3 | `.venv/bin/python -m tests.check_credentials` | 10초 | 슬랙 · 기상청 |
| 4 | `.venv/bin/python -m src.post --dry-run --week-offset 1 --no-wait` | 20초 | 기상청 |
| 5 | 슬랙에서 직접 멘션 | — | 전부 |

1~2 는 키 없이 돈다. 3 부터 토큰이 필요하다.

### 1. 린트

```bash
.venv/bin/ruff check src/ tests/
```

**지금 8건이 이미 떠 있다** (`src/forecast.py`, `src/writer.py`,
`tests/`). 맥에서 넘어온 기존 것이라 새 작업과 무관하다. 고친 파일에서
건수가 늘었는지만 본다.

### 2. 오프라인 검증

```bash
.venv/bin/python -m tests.test_offline
```

pytest 가 아니라 **그냥 스크립트다.** `pytest` 로 부르면 `No module named
pytest` 가 난다. 16개 검사가 순서대로 돌고 `전부 통과` 로 끝난다.

키 없이 도는 대신 가짜 데이터를 쓴다. 그래서 **기상청 페이지 구조가 바뀌어도
여기서는 안 잡힌다** — 그건 3·4 의 몫이다. 다만 일기도 다운로드만은 실제
서버를 부른다(공개 URL, 인증 불필요).

카드 렌더링도 여기서 확인된다. `data/img/card.png` 가 90KB 안팎이면 정상이고,
**20KB 이하로 떨어지면 한글이 □□□ 로 깨진 것**이다. 눈으로 한 번 열어 본다.

### 3. 자격증명·외부 연결

```bash
.venv/bin/python -m tests.check_credentials
```

토큰 값은 찍지 않는다. 다섯 줄이 전부 ✅ 면 된다.

- 슬랙 인증 — 채널 입장 여부는 **판정하지 않는다.** 그건 4 에서 갈린다
- 기상청 통보문 / 중기예보 — 파싱까지 확인한다. **여기가 빨간불이면 기상청
  페이지 구조가 바뀐 것**이다
- Chromium — 카드 렌더링 가능 여부

### 4. 주간 게시 (전송 없음)

```bash
.venv/bin/python -m src.post --dry-run --week-offset 1 --no-wait
```

`--week-offset 1` 이 중요하다. **주 중간에 그냥 돌리면 실패한다.**

```
7일 중 5일의 기온을 얻지 못해 신뢰할 수 없습니다 (09/07, …).
지어낸 날씨를 올리지 않기 위해 게시를 건너뜁니다.
```

고장이 아니다. 기본값은 월요일 시작 주라서 수요일에 돌리면 앞쪽이 지난
날짜이고, 지난 날은 예보가 없다. **이 메시지가 뜨면 정상 동작한 것이다** —
`--week-offset 1` 로 다음 주를 보면 끝까지 돈다.

출력 맨 아래에 저장된 PNG 경로가 찍힌다. 카드와 일기도를 열어 본다.
`--data-dir` 로 저장 위치를 옮길 수 있다(`--dry-run` 과 함께여야 한다).

### 5. 멘션 (실제 슬랙)

**여기부터는 사람들에게 보인다.** 테스트 채널이 따로 없으면 보내기 전에
한 번 더 생각한다. 지운 메시지도 알림은 이미 갔다.

봇이 최신 코드로 돌고 있는지부터 확인한다.

```bash
systemctl --user restart weather-mention    # 코드를 고쳤으면 반드시
systemctl --user status weather-mention
```

`.env` 도 마찬가지다 — systemd 가 **기동 시점에만** 읽으므로 채널을 바꿨으면
재시작해야 한다. 실행 중인 프로세스가 무슨 값을 들고 있는지는 이렇게 본다.

```bash
PID=$(systemctl --user show weather-mention -p MainPID --value)
tr '\0' '\n' < /proc/$PID/environ | grep SLACK_CHANNEL_ID
```

슬랙 없이 응답 문구만 보려면 파이썬으로 직접 부른다. **이쪽을 먼저 쓴다.**

```bash
.venv/bin/python -c "
from src.mention import build_reply
print(build_reply('9월 18일 부산 날씨'))
"
```

## 지역·기간 조회

```bash
.venv/bin/python -m src.query              # 전국, 이번 주
.venv/bin/python -m src.query 부산
.venv/bin/python -m src.query 제주 --week-offset 1 --json
```

**`src.query` 는 광역만 받는다.** 동 단위(`역삼동`)는 멘션 봇에만 있다 —
`build_reply('역삼동 날씨')` 로 확인한다.

## 깨지기 쉬운 곳

오늘까지 실제로 문제가 났던 자리들이다.

**기상청 페이지 구조** — 가장 잦다. 3 이나 4 에서 "기온을 얻지 못해" 가 나오면
여기를 의심한다. `LOG_LEVEL=DEBUG` 로 한 번 돌려 응답 크기를 본다(정상은 수십 KB).

**멘션 이벤트가 안 들어옴** — 봇은 살아 있는데 답이 없다면, 로그에 `멘션 수신`
줄이 찍히는지 본다.

```bash
journalctl --user -u weather-mention -f
```

한 줄도 안 찍히면 코드가 아니라 **슬랙 앱의 Event Subscriptions** 문제다
(`app_mention` 구독 + Reinstall). 저장소의 `slack_app_manifest.yaml` 은
게시 전용 시절 버전이라 이 설정이 빠져 있다.

**조언 문구가 매번 같음** — [`src/advice.py`](../src/advice.py) 의 `*_LINES`
표를 본다. 문구는 **날짜로 고른다**(`_pick`). 같은 날 두 번 물으면 같은 답이
나오는 게 정상이고, 날이 바뀌어야 표현이 바뀐다. 하루 안에서 다른 문구를
보려면 날짜를 바꿔 부른다.

```bash
.venv/bin/python -c "
import datetime as dt
from src.advice import _pick, SPREAD_LINES
for i in range(4):
    d = dt.date(2026,9,13) + dt.timedelta(days=i)
    print(d, _pick(SPREAD_LINES, d).format(gap=12))
"
```

**조언이 하나도 안 나옴** — 임계값에 안 걸린 것일 수 있다. 아침 11도에
일교차 11도 같은 평범한 날은 **일부러 침묵한다.** 짚을 게 없으면 말하지
않는 것이 이 모듈의 규칙이다.

**일기도가 어제 것** — 정상이다. 일기도는 09시·21시(KST)에만 나오는데
게시가 08:00 이라 직전 것은 전날 21시 발표분이다. 카드 라벨에 기준 시각이
적혀 있다.

## 배포 후 확인

```bash
systemctl --user status weather-mention          # 상시 봇
systemctl --user list-timers 'weather-*'         # 다음 실행 시각
journalctl --user -u weather-mention -n 50
```

앱 로그는 `logs/{연}/{연.월}/` 아래에 날짜별로 쌓인다. **오류만 보려면**
`*.error.*` 를 먼저 본다.

```bash
D=logs/$(date +%Y)/$(date +%Y.%m)
tail -50 "$D"/weather-mention.error.$(date +%F).log
```

파이썬이 뜨기도 전에 죽은 경우(venv 경로, `.env` 누락, 권한)는 앱 로거가
잡지 못하므로 `journalctl` 을 본다.

> **`loginctl show-user ajung -p Linger` 가 `Linger=no` 면** 로그아웃할 때
> 봇이 함께 내려간다. 재부팅 후 자동 기동도 안 된다. 관리자에게
> `sudo loginctl enable-linger ajung` 를 요청한다.
