"""슬랙 게시물의 문단 — 조립해서 쓰는 부품.

문단은 글자를 바로 이어 붙이지 않고 «제목 + 라벨 — 내용» 줄로 조립한 뒤, 슬랙 글로는
to_slack() 에서만 옮김. 줄 모양(글머리표·구분자)이나 순서를 바꿀 때 자료를 만드는
코드(foliage · blossom …)를 건드리지 않게 하려는 것.

    p = Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:")
    p.add("관측", observed).add("이번 주", week).add("올해", "")     # 빈 내용은 건너뜀
    msg = Message(body, credits=["지상일기도 · 기상청"])
    msg.add(Block(p, credit="벚꽃 · 관측 기상청 날씨누리"))
    msg.to_slack()      # 본문 → 문단들 → 출처 줄
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Row:
    """문단의 한 줄 — '관측', '이번 주' 같은 라벨과 슬랙 mrkdwn 내용."""
    label: str
    text: str

    def to_slack(self) -> str:
        return f"• {self.label} — {self.text}"


@dataclass
class Paragraph:
    """제목 한 줄 아래 «라벨 — 내용» 줄들."""
    title: str
    emoji: str = ""
    rows: list[Row] = field(default_factory=list)

    def add(self, label: str, text: str | None) -> Paragraph:
        """줄을 더함. 내용이 비면 건너뜀 — 받지 못한 자료의 줄을 빼려고 부르는 쪽마다 if 를 두지 않게."""
        if text:
            self.rows.append(Row(label, text))
        return self

    @property
    def empty(self) -> bool:
        return not self.rows

    def to_slack(self) -> str:
        head = f"{self.emoji} *{self.title}*" if self.emoji else f"*{self.title}*"
        return "\n".join([head, *(row.to_slack() for row in self.rows)])


@dataclass(frozen=True)
class Attachment:
    """문단에 딸린 그림.

    slug 는 파일 이름 앞부분이자 보존 정리 패턴임 — 'foliage' 면 foliage-20261005.png 로
    올라가고, dry-run 산출물은 foliage-*.png 로 치움(bin/cleanup.py 와 같은 패턴).
    """
    slug: str
    png: bytes
    title: str
    alt: str


@dataclass
class Block:
    """게시물에 들어가는 한 덩어리 — 문단, 그 출처 한 줄, 딸린 그림."""
    paragraph: Paragraph
    credit: str = ""
    attachment: Attachment | None = None


@dataclass
class Message:
    """본문 → 덩어리 문단들 → 출처 줄 순으로 조립한 게시물 글."""
    body: str
    credits: list[str] = field(default_factory=list)    # 덩어리에 딸리지 않은 출처 (일기도 등)
    blocks: list[Block] = field(default_factory=list)

    def add(self, block: Block) -> Message:
        """덩어리를 더함. 줄이 하나도 없는 문단은 넣지 않음 — 제목만 남음."""
        if not block.paragraph.empty:
            self.blocks.append(block)
        return self

    @property
    def attachments(self) -> list[Attachment]:
        return [b.attachment for b in self.blocks if b.attachment]

    def to_slack(self) -> str:
        credits = [*self.credits, *(b.credit for b in self.blocks if b.credit)]
        parts = [self.body, *(b.paragraph.to_slack() for b in self.blocks)]
        if credits:
            parts.append("\n".join(f"_{c}_" for c in credits))
        return "\n\n".join(parts)
