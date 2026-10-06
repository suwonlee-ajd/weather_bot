# 서버 배포

> **배치 방식은 둘.**
>
> | | root 가 있는 서버 | sudo 가 없는 서버 |
> |---|---|---|
> | 경로 | `/opt/weather_bot` | 로그인 계정의 홈 (예: `~/workspace/weather_bot`) |
> | 실행 계정 | 전용 `weather` 계정 | 로그인 계정 |
> | systemd | 시스템 유닛 (§2 · §3) | **`systemd --user`** (§2-A · §3-A) — 켜고 끄는 데 sudo 가 필요 없음 |
> | 파이썬 | `.python-version`, uv 가 받아서 씀 | 같음 |
>
> 유닛 파일은 경로를 `%h`(유닛을 등록한 계정의 홈)로 적어 두었음. root 서버에서 `/opt` 에
> 둔다면 `WorkingDirectory` · `EnvironmentFile` · `ExecStart` 의 경로와 `User=` 를 맞춤.

멘션 봇은 **Socket Mode** 라서 인바운드 포트·도메인·TLS·리버스 프록시가 전혀 필요 없음.
나가는 WebSocket 연결 하나뿐이라, 서버에 이미 떠 있는 다른 서비스와 겹치지 않음.

## 1. 슬랙 콘솔 (먼저)

| 위치 | 할 일 |
|---|---|
| Basic Information → App-Level Tokens | `connections:write` 스코프로 토큰 생성 → `xapp-...` |
| Settings → Socket Mode | **Enable Socket Mode** ON |
| OAuth & Permissions → Bot Token Scopes | `app_mentions:read` 추가 (`chat:write`, `files:write` 는 기존) |
| Features → Event Subscriptions | **Enable Events** ON → Subscribe to bot events 에 `app_mention` |
| Install App | **Reinstall to Workspace** (스코프를 바꿨으므로) |

Socket Mode 가 켜져 있으면 Event Subscriptions 에 **Request URL 입력란이 뜨지 않음.** 정상.

## 2. 서버

```bash
# uv 가 파이썬까지 관리하므로 시스템 파이썬 버전을 맞출 필요가 없음
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh

sudo useradd -r -m -d /opt/weather_bot weather
sudo -u weather git clone <repo> /opt/weather_bot
cd /opt/weather_bot

sudo -u weather uv sync --frozen               # uv.lock 그대로 — 로컬과 같은 버전
sudo -u weather uv run python -m playwright install --with-deps chromium
sudo apt-get install -y fonts-noto-cjk          # 없으면 카드가 □□□ 로 렌더링됨

sudo -u weather cp .env.example .env
sudo -u weather chmod 600 .env
sudo -u weather vi .env                          # SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL_ID
```

점검:

```bash
sudo -u weather bash -c 'set -a; . .env; set +a; .venv/bin/python -m tests.check_credentials'
```

## 2-A. 권한 없는 서버

sudo 가 없으므로 전용 계정도 `/opt` 도 만들지 않음. 로그인 계정의 홈에 두고
그 계정으로 돌림.

```bash
git clone <repo> ~/workspace/weather_bot
cd ~/workspace/weather_bot

uv sync --frozen                                  # .python-version 대로 받음
cp .env.example .env                              # SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL_ID
.venv/bin/python -m playwright install chromium   # --with-deps 는 sudo 가 필요해 뺌
chmod 600 .env                                    # 토큰이 들어 있음
```

`--with-deps` 없이도 크로뮴이 뜨는지, 한글이 깨지지 않는지 확인함
(`fonts-noto-cjk` 가 이미 깔려 있는 서버라면 둘 다 통과함):

```bash
set -a; . ./.env; set +a
.venv/bin/python -m tests.check_credentials
.venv/bin/python -m tests.test_offline          # 카드 렌더링까지 확인함
```

> 크로뮴이 `error while loading shared libraries` 로 죽으면 그때는 라이브러리가
> 모자란 것이라 관리자에게 `apt-get install` 을 요청해야 함.

## 3-A. systemd --user

유닛 파일에 `User=` 를 두지 않음 — 등록한 계정으로 실행됨.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/weather-*.service deploy/weather-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload

systemctl --user enable --now weather-mention.service   # 멘션 봇 (상시)
systemctl --user enable --now weather-cleanup.timer     # 정리 (매일 04:00)
# weather-weekly.timer 는 §4 를 읽고 켬 (GitHub Actions 와 겹침)

systemctl --user status weather-mention
systemctl --user list-timers 'weather-*'
journalctl --user -u weather-mention -f
```

### ⚠️ 로그아웃하면 꺼짐 — lingering

`systemd --user` 는 기본적으로 계정의 마지막 세션이 끝나면 함께 내려감.
**상시 실행인 멘션 봇에는 치명적임.** 관리자에게 한 번만 요청함:

```bash
sudo loginctl enable-linger <계정>
loginctl show-user <계정> -p Linger   # Linger=yes 여야 함
```

이게 켜지기 전까지는 SSH 를 끊으면 봇이 멈춤. 재부팅 후 자동 기동도 이 설정에 달려 있음.

명령은 전부 `systemctl --user`. `sudo systemctl` 로 쓰면 "유닛이 없다" 고 나옴.

## 3. systemd

```bash
sudo cp deploy/weather-*.service deploy/weather-*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable --now weather-mention.service   # 멘션 봇 (상시)
sudo systemctl enable --now weather-weekly.timer      # 주간 게시 (월 07:50)
sudo systemctl enable --now weather-cleanup.timer     # 정리 (매일 04:00)

systemctl status weather-mention
systemctl list-timers 'weather-*'
journalctl -u weather-mention -f
```

정리 타이머를 켜는 이유 — 실제 게시는 슬랙에만 올리고 파일을 남기지 않음.
그래서 dry-run 을 돌리지 않는 서버에서는 `data/` 를 치울 주체가 없음.
`logs/` 는 loguru 가 알아서 회전시키므로 이 타이머가 없어도 무방함.

주간 게시를 수동으로 한 번 돌려보려면:

```bash
sudo systemctl start weather-weekly.service
sudo systemctl start weather-cleanup.service   # 정리도 같은 방식
```

## 4. 주간 게시는 한 곳에서만

주간 게시를 돌릴 수 있는 자리가 둘 — 서버의 타이머(`weather-weekly.timer`, 월 07:50 KST)와
GitHub Actions(`.github/workflows/weekly-weather.yml`).
**둘 다 살아 있으면 매주 두 번 올라감.** 하나를 반드시 끔.

저장소의 워크플로에는 `schedule:` 이 없음 — 기본은 **서버 타이머로 게시**하고, 워크플로는
손으로 한 번 돌리거나 dry-run 결과만 확인할 때(`workflow_dispatch`) 씀.

서버로 운영한다면(권장 — 멘션 봇이 어차피 여기 있고, 토큰이 한 곳에 모임) 워크플로에
`schedule:` 을 넣지 않음.

GitHub Actions 로 운영한다면 워크플로에 크론을 넣고, 서버 타이머를 먼저 끔:

```bash
systemctl --user disable --now weather-weekly.timer   # systemd --user
# root 가 있는 서버라면: sudo systemctl disable --now weather-weekly.timer
```

```yaml
on:
  schedule:
    - cron: "35 22 * * 0"     # 일 22:35 UTC = 월 07:35 KST. 크론은 늦게 뜰 수 있어 일찍 깨우고 POST_AT 까지 기다림
  workflow_dispatch:
```

멘션 봇은 상시 WebSocket 연결이라 Actions 로 옮길 수 없음. 서버에만 둠.

> **같은 슬랙 앱에 두 연결이 붙으면 한 멘션에 두 번 답함.** 개발 중 다른
> 자리에서 `src.mention` 을 띄워 뒀다면 서버로 옮긴 뒤 반드시 끔.

## 로그

`logs/{연}/{연.월}/{앱}.{날짜}.log`

```bash
cd ~/workspace/weather_bot                   # 저장소 위치
D=logs/$(date +%Y)/$(date +%Y.%m)
tail -50 "$D"/weather-mention.error.$(date +%F).log   # 오류만 — 여기부터 봄
tail -f  "$D"/weather-mention.$(date +%F).log         # 전체 흐름
```

자정에 회전하고 90일 뒤 지워지며 지난 파일은 gz 로 압축됨(loguru).

**파이썬이 뜨기도 전에 죽은 경우**(venv 경로, `.env` 누락, 권한)는 앱 로거가
잡지 못하므로 journald 를 봄.

```bash
journalctl --user -u weather-mention -n 50            # systemd --user (root 서버는 --user 없이)
journalctl --user -u weather-weekly --since "1 week ago"
```

읽는 법은 [`docs/logging.md`](../docs/logging.md).

## 운영

### 켜고 끄기

```bash
bin/start.sh             # 멘션 봇 + 타이머 (disable 해 둔 타이머는 건너뜀)
bin/start.sh -r          # 코드를 갱신한 뒤 — 떠 있는 멘션 봇을 다시 띄움
bin/start.sh mention     # 멘션 봇만 (timers 도 됨)
bin/stop.sh              # 전부 끔. disable 은 하지 않아 재부팅하면 다시 켜짐
bin/stop.sh timers       # 이번 주 게시만 건너뛸 때
```

systemd 유닛이 등록돼 있으면(§3 · §3-A) 그 유닛을 켜고 끔. **유닛이 없으면 멘션 봇을
백그라운드 프로세스로 직접 띄움** — 이때는 죽어도 되살아나지 않고, 재부팅하면 꺼지며,
주간 게시·정리 예약도 없음. 콘솔 출력은 `logs/weather-mention.console.log`, PID 는
`data/mention.pid`. 스크립트 밖에서 띄운 멘션 봇이 있으면 경고함(한 멘션에 두 번 답함).

### 코드 갱신

```bash
cd ~/workspace/weather_bot
git pull
uv sync --frozen                              # uv.lock 이 바뀌었을 때만 실제로 설치함
bin/start.sh -r mention                       # 멘션 봇은 상시라 다시 띄워야 반영됨
```

> root 가 있는 서버라면 `sudo -u weather git pull` · `sudo systemctl restart` 로 읽음.

주간 게시와 정리는 타이머가 매번 새로 실행하므로 재시작할 것이 없음.

### 되돌리기

```bash
git log --oneline -5
git checkout <직전 커밋>
uv sync --frozen
systemctl --user restart weather-mention
```

### 상태 확인

```bash
systemctl --user status weather-mention          # 상시 봇이 살아 있나
systemctl --user list-timers 'weather-*'         # 다음 실행 시각
systemctl --user start weather-weekly.service    # 게시를 지금 한 번

# 주 중간에 «다음 주» 결과만 미리 보기 (슬랙 전송 없음)
./deploy/run-weekly.sh --dry-run --week-offset 1 --no-wait
```

> 주 중간에 `weather-weekly.service` 를 그냥 돌리면 «기온을 얻지 못해» 로 실패함.
> 지난 날짜에는 예보가 없기 때문이며, 고장이 아님 — 위 `--week-offset 1` 로 확인함.

### 게시가 안 나갔을 때

1. `journalctl --user -u weather-weekly --since "1 week ago"` — 유닛이 뜨긴 했나
2. 떴는데 실패했다면 `logs/.../weekly-weather.error.*.log` 에 이유가 있음
3. `봇이 채널에 없습니다` → 해당 채널에서 `/invite @<봇 이름>`
4. `기온을 얻지 못해` → 기상청 페이지 구조가 바뀌었을 수 있음.
   `LOG_LEVEL=DEBUG` 로 한 번 돌려 응답 크기를 봄(정상은 수십 KB)

## 참고

- `EnvironmentFile` 은 셸이 아니라서 따옴표·변수 확장이 없음. `.env` 는 `KEY=값` 한 줄씩만 둠.
- 멘션 봇은 예보를 1시간 캐시함(`MENTION_CACHE_TTL`). 기상청은 하루 네 번만 갱신하므로
  멘션마다 긁을 이유가 없고, 남의 서버에 대한 예의이기도 함.
