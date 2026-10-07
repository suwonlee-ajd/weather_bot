# weather-bot 코드 스타일

| 항목 | 값 |
| --- | --- |
| 문서 버전 | 0.1.0 |
| 최종 수정 | 2026-10-07 |

`.claude/` 가 gitignore 라 저장소에 커밋되는 유일한 코드 스타일 문서임. 봇이 내보내는 문장의 문체는
[`writing-style.md`](writing-style.md).

## 공통

| 항목 | 규칙 |
| --- | --- |
| 시크릿 | 코드에 하드코딩 금지 — `.env`(chmod 600). 토큰 값은 로그·출력에 한 글자도 남기지 않음 |
| 의존 | 아래 «구조» 의 방향으로만. 역방향 import 금지 |
| 테스트 | 구현과 같은 작업 단위로 작성 |
| 지어내지 않기 | 수치는 기상청 원문 그대로. 수집이 실패하면 게시를 건너뜀 — 추정값으로 채우지 않음 |

## Python

| 항목 | 규칙 |
| --- | --- |
| 버전 | 3.12+ (`.python-version` 은 uv 가 받음) |
| 패키지 | `uv add` — `pip install` 금지. 서버는 `uv sync --frozen`, 모델 extra 는 매번 함께 줌 |
| 린트 | `ruff check src tests bin` — import 정렬(I) 포함 |
| HTTP | `requests` |
| 로깅 | 표준 `logging` 으로 찍고 `common/logsetup.setup()` 이 loguru 로 모음. `print` 는 CLI 출력(조회 · dry-run · 정리)에만 |
| 경로 | `pathlib.Path` — `os.path` 금지 |
| 예외 | bare `except:` 금지. `except Exception` 은 경계(멘션 처리 · 문구 모델 · 철 소식 · 로그 열기 · PDF 읽기)에서만, 로그를 남기고 대체 경로로 |
| 타입 힌트 | 인자 · 반환값 필수. `Any` 최소화 |
| 네이밍 | snake_case (함수 · 변수) · PascalCase (클래스) · UPPER_SNAKE_CASE (상수) · 모듈 밖에서 안 쓰면 `_` 접두 |

### 구조

기능별 패키지. 각 패키지 안은 평평하게 둠.

| 패키지 | 내용 | 가져다 쓰는 곳 |
| --- | --- | --- |
| `common/` | 설정 · 로그 · 캐시 · 보존 · 표기 · HTML → PNG | 어디서나 |
| `kma/` | 기상청 수집 (광역 · 동네 · 전망 · 일기도) | `common` |
| `season/` | 단풍 · 벚꽃 자료와 문장 · 지도 | `common` |
| `advice/` | 수치에서 생활 조언 | (없음) |
| `weekly/` | 주간 게시 | `common` · `kma` · `season` · `advice` |
| `mention/` | 멘션 봇 | `common` · `kma` · `season` · `advice` |

- `weekly` 와 `mention` 은 서로 가져다 쓰지 않음. 둘 다 쓰는 것은 `common` 이나 자료 패키지로 내림
- 진입점: `python -m src.weekly` (주간 게시) · `python -m src.mention` (멘션 봇) · `python -m src.query` (조회) · `bin/cleanup.py` (정리)
- 공유 이름은 정의된 모듈에서 바로 가져옴 — 다른 모듈을 거쳐 다시 내보내지 않음

### 크기

| 대상 | 권장 |
| --- | --- |
| 파일 | 150줄 (HTML·CSS 템플릿이 든 파일은 예외) |
| 함수 | 50줄 안팎. 넘으면 단계별 함수로 나눔 |
| 함수 인자 | 5개 이하. 넘으면 작은 dataclass 로 묶음 (예: `mention.bot.Thread`) |

### 주석

- 코드와 이름이 말하게 함. 주석은 코드만으로 안 보이는 **왜** 만 — 외부 사정(기상청 · 슬랙 · 웨더아이의 형식과 함정), 숫자의 근거, 순서가 중요한 이유
- 한 줄(길어야 두 줄), 결론 먼저(두괄식), 명사형 종결(`~함` · `~임` · 명사)
- 코드가 하는 일을 되풀이하거나 경위를 적지 않음 — 경위는 커밋 메시지에
- docstring: 모듈은 1~2줄. 공개 함수 · 클래스는 이름만으로 부족할 때 한 줄. private 함수는 대개 생략

## 테스트

| 항목 | 규칙 |
| --- | --- |
| 실행 | `.venv/bin/python -m tests.test_offline` — 토큰 없이 동작 |
| 네트워크 | 테스트에서 실제 호출 금지 — 일기도 다운로드 확인(`test_chart_download`)만 예외 |
| 바꿔치기 | 함수를 **쓰는 모듈** 쪽을 바꿔치기함. 여러 모듈이 쓰면 원본 모듈을 거쳐 부르게 함 (예: `foliage.fetch_snapshot`) |
| 점검 | `.venv/bin/python -m tests.check_credentials` — 슬랙 · 기상청 · Chromium · 문구 모델 |

## 문서

README · docs 는 명사형 종결(`~함` · `~임` · 명사). 코드 경로 · 명령은 실제와 같게 — 파일을 옮기면 같은 커밋에서 고침.

## 커밋

```
<type>: <제목>

- 무엇을 · 왜
- 검증: <명령 + 결과>
```

type: `feat` · `fix` · `refactor` · `chore` · `docs` · `test`

- 본문은 heredoc 으로 작성 — single-line `-m` 금지
- 본인이 수정한 파일만 stage — wildcard add 금지
- `Co-Authored-By` 라인 넣지 않음

## 브랜치

`main` 에서 `feat/*` · `fix/*` · `refactor/*` 를 따서 작업하고 `main` 으로 머지.

| 머지 | 버전 (`pyproject.toml`) |
| --- | --- |
| 기능 추가 | MINOR +1 |
| 수정 | PATCH +1 |
| 호환성 파괴 · 정식 출시 | MAJOR +1 (수동 결정) |

운영 서버는 `main` 작업 트리로 돎. 다른 브랜치 작업은 별도 작업 트리(`git worktree`)에서 함.
