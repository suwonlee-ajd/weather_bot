"""예보관 서술(통보문·중기예보의 □·○ 줄)에서 낱말이 든 줄 — 장마·더위·태풍이 원문 그대로 인용함."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

_BULLET_RE = re.compile(r"^[□○]\s*")
_HEAD_RE = re.compile(r"^\([^)]*\)\s*")

MAX_QUOTES = 2      # 많으면 철 소식 한 문단이 본문보다 길어짐
QUOTE_CHARS = 120   # 실제 서술은 한 줄이 300자를 넘기도 함 — 길면 낱말 경계에서 자르고 «…»


class Source(Protocol):
    """서술 하나 — kma.page.Narrative 의 모양(season 은 kma 를 가져다 쓰지 않음)."""
    lines: list[str]


def mentioning(lines: Iterable[str], words: tuple[str, ...]) -> list[str]:
    """낱말이 든 줄. 글머리(□·○)만 떼고 괄호 머리말(«(모레, 15일)»)은 남김 — 언제 이야기인지 알려 줌."""
    found: list[str] = []
    for line in lines:
        text = _BULLET_RE.sub("", line).strip()
        if any(w in text for w in words) and text not in found:
            found.append(text)
    return found


def mentioning_in[S: Source](sources: Iterable[S], words: tuple[str, ...]) -> list[tuple[str, S]]:
    """여러 서술에서 낱말이 든 줄과 그 서술 — 같은 줄은 앞 서술의 것만. 출처 줄에 실린 서술만 적으려고 짝지음."""
    found: list[tuple[str, S]] = []
    for source in sources:
        found += [(text, source) for text in mentioning(source.lines, words) if all(text != t for t, _ in found)]
    return found


def in_body(text: str, body: str) -> bool:
    """본문이 이미 인용한 줄인지 — 규칙 기반 본문 1문단이 (종합) 줄을 머리말 없이 인용함."""
    return _HEAD_RE.sub("", text) in body


def unquoted(texts: list[str], body: str) -> list[str]:
    """본문이 이미 인용한 줄은 빼고 MAX_QUOTES 까지."""
    return [t for t in texts if not in_body(t, body)][:MAX_QUOTES]


def quote(text: str) -> str:
    """원문 그대로 따옴. 길면 앞부분만 — 자른 자리에 «…» 를 붙여 원문이 더 있음을 알림(말을 보태지 않음)."""
    if len(text) > QUOTE_CHARS:
        cut = text[:QUOTE_CHARS]
        text = (cut[:cut.rfind(" ")] if " " in cut else cut).rstrip(" ,·") + "…"
    return f'"{text}"'
