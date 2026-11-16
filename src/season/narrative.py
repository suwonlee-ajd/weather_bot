"""예보관 서술(통보문·중기예보의 □·○ 줄)에서 낱말이 든 줄 — 장마·더위가 원문 그대로 인용함."""
from __future__ import annotations

import re
from collections.abc import Iterable

_BULLET_RE = re.compile(r"^[□○]\s*")
_HEAD_RE = re.compile(r"^\([^)]*\)\s*")

MAX_QUOTES = 2      # 많으면 철 소식 한 문단이 본문보다 길어짐


def mentioning(lines: Iterable[str], words: tuple[str, ...]) -> list[str]:
    """낱말이 든 줄. 글머리(□·○)만 떼고 괄호 머리말(«(모레, 15일)»)은 남김 — 언제 이야기인지 알려 줌."""
    found: list[str] = []
    for line in lines:
        text = _BULLET_RE.sub("", line).strip()
        if any(w in text for w in words) and text not in found:
            found.append(text)
    return found


def unquoted(texts: list[str], body: str) -> list[str]:
    """본문이 이미 인용한 줄은 뺌 — 규칙 기반 본문 1문단이 (종합) 줄을 머리말 없이 인용함."""
    return [t for t in texts if _HEAD_RE.sub("", t) not in body][:MAX_QUOTES]


def quote(text: str) -> str:
    return f'"{text}"'
