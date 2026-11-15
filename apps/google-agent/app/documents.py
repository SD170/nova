"""save_document: the brain writes the text (cover letter, reply, summary), we save it as a
.docx (or .md) file and return a download link. Files live in data/files/ (gitignored)."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import DocumentNotFound, DocumentResult

MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "md": "text/markdown", "pdf": "application/pdf"}

_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def _slug(title: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
    return (s or "document")[:60]


def _runs(paragraph, text: str) -> None:
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def markdown_to_docx(title: str, markdown: str, path: Path) -> None:
    """Small Markdown subset: #/##/### headings, -/* bullets, 1. lists, **bold**, *italic*."""
    from docx import Document

    doc = Document()
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            doc.add_heading(m.group(2).strip(), level=len(m.group(1)))
        elif re.match(r"^\s*[-*]\s+", line):
            _runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", line))
        elif re.match(r"^\s*\d+[.)]\s+", line):
            _runs(doc.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s+", "", line))
        else:
            _runs(doc.add_paragraph(), line.strip())
    doc.core_properties.title = title
    doc.save(str(path))


class DocumentStore:
    def __init__(self, directory: Path, public_base: str = ""):
        self.dir = directory
        self.public_base = public_base.rstrip("/")

    def save(self, title: str, markdown: str, fmt: str = "docx") -> DocumentResult:
        if fmt not in MEDIA:
            raise ValueError("format must be 'docx' or 'md'")
        if not markdown.strip():
            raise ValueError("content_markdown is empty")
        self.dir.mkdir(parents=True, exist_ok=True)
        doc_id = uuid.uuid4().hex[:12]
        filename = f"{_slug(title)}.{fmt}"
        path = self.dir / f"{doc_id}.{fmt}"
        if fmt == "docx":
            markdown_to_docx(title, markdown, path)
        else:
            path.write_text(markdown, encoding="utf-8")
        result = DocumentResult(
            id=doc_id, title=title, filename=filename, format=fmt, size_bytes=path.stat().st_size,
            download_url=f"{self.public_base}/files/{doc_id}", created_at=datetime.now(timezone.utc))
        (self.dir / f"{doc_id}.json").write_text(result.model_dump_json())
        return result

    def save_bytes(self, title: str, data: bytes, fmt: str = "pdf") -> DocumentResult:
        """Store an already-built file (the exam-prep PDF)."""
        if fmt not in MEDIA:
            raise ValueError(f"unsupported format {fmt!r}")
        self.dir.mkdir(parents=True, exist_ok=True)
        doc_id = uuid.uuid4().hex[:12]
        path = self.dir / f"{doc_id}.{fmt}"
        path.write_bytes(data)
        result = DocumentResult(
            id=doc_id, title=title, filename=f"{_slug(title)}.{fmt}", format=fmt,
            size_bytes=len(data), download_url=f"{self.public_base}/files/{doc_id}",
            created_at=datetime.now(timezone.utc))
        (self.dir / f"{doc_id}.json").write_text(result.model_dump_json())
        return result

    def get(self, doc_id: str) -> tuple[Path, DocumentResult]:
        if not re.fullmatch(r"[0-9a-f]{12}", doc_id):
            raise DocumentNotFound(doc_id)
        meta = self.dir / f"{doc_id}.json"
        try:
            result = DocumentResult(**json.loads(meta.read_text()))
        except (OSError, ValueError) as exc:
            raise DocumentNotFound(doc_id) from exc
        path = self.dir / f"{doc_id}.{result.format}"
        if not path.exists():
            raise DocumentNotFound(doc_id)
        return path, result
