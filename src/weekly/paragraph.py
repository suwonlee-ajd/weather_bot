"""슬랙 게시물의 문단 부품. 줄 모양·순서는 to_slack() 에서만 정함 — 자료 쪽은 내용만 넘김.

    p = Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:")
    p.add("관측", observed).add("올해", "")                     # 빈 내용은 건너뜀
    msg = Message(body).add(Block(None, "지상일기도 · 기상청", chart)).add(Block(p, credit="벚꽃 · 기상청"))
    msg.to_slack()                                             # 본문 → 문단들 → 출처 줄
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Row:
    """문단 한 줄. text 는 슬랙 mrkdwn."""
    label: str
    text: str

    def to_slack(self) -> str:
        return f"• {self.label} — {self.text}"


@dataclass
class Paragraph:
    title: str
    emoji: str = ""
    rows: list[Row] = field(default_factory=list)

    def add(self, label: str, text: str | None) -> Paragraph:
        """내용이 비면 건너뜀 — 받지 못한 자료를 부르는 쪽마다 거르지 않게."""
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
    """게시물에 붙는 그림. pattern 은 dry-run 이 같은 종류의 옛 파일을 지우는 보존 정리 패턴."""
    png: bytes
    title: str
    alt: str
    filename: str
    keep_days: int
    pattern: str

    def upload(self) -> dict:
        """files_upload_v2 의 file_uploads 한 칸."""
        return {"filename": self.filename, "file": self.png, "title": self.title, "alt_txt": self.alt}


@dataclass
class Block:
    """영역 하나의 결과. 일기도처럼 글 없이 그림·출처만 있으면 paragraph 는 None."""
    paragraph: Paragraph | None
    credit: str = ""
    attachment: Attachment | None = None

    @property
    def text(self) -> str:
        return self.paragraph.to_slack() if self.paragraph and not self.paragraph.empty else ""


@dataclass
class Message:
    body: str
    blocks: list[Block] = field(default_factory=list)

    def add(self, block: Block) -> Message:
        """글도 그림도 없는 덩어리는 출처까지 뺌."""
        if block.text or block.attachment:
            self.blocks.append(block)
        return self

    @property
    def attachments(self) -> list[Attachment]:
        return [b.attachment for b in self.blocks if b.attachment]

    def to_slack(self) -> str:
        credits = [b.credit for b in self.blocks if b.credit]
        parts = [self.body, *filter(None, (b.text for b in self.blocks))]
        if credits:
            parts.append("\n".join(f"_{c}_" for c in credits))
        return "\n\n".join(parts)
