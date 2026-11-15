"""Document store: bundled synthetic samples + per-session uploads.

Uploads are kept in memory only (cleared on restart or via "Clear my data").
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SAMPLES_DIR = Path(__file__).parent / "samples"

MAX_UPLOAD_BYTES = 2 * 1024 * 1024


@dataclass
class Document:
    id: str
    type: str  # afterVisit | bill | eob | unknown
    name: str
    synthetic: bool
    pages: list[str] = field(default_factory=list)  # extracted text per page

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "synthetic": self.synthetic,
            "pageCount": len(self.pages),
        }


SAMPLES: dict[str, tuple[str, str, str]] = {
    # id: (filename, type, display name)
    "sample-after-visit": ("after_visit_sam.txt", "afterVisit", "Sam's after-visit summary (demo)"),
    "sample-bill": ("bill_sam.txt", "bill", "Sam's clinic bill (demo)"),
    "sample-eob": ("eob_sam.txt", "eob", "Sam's insurance EOB (demo)"),
}


def load_sample(doc_id: str) -> Optional[Document]:
    entry = SAMPLES.get(doc_id)
    if not entry:
        return None
    filename, dtype, name = entry
    text = (SAMPLES_DIR / filename).read_text(encoding="utf-8")
    return Document(id=doc_id, type=dtype, name=name, synthetic=True, pages=[text])


def list_samples() -> list[dict]:
    return [load_sample(i).summary() for i in SAMPLES]  # type: ignore[union-attr]


def guess_type(text: str) -> str:
    low = text.lower()
    if "explanation of benefits" in low or "this is not a bill" in low:
        return "eob"
    if any(k in low for k in ("amount due", "you owe", "patient statement", "balance due")):
        return "bill"
    if any(k in low for k in ("after-visit", "after visit", "discharge", "instructions", "follow-up", "follow up")):
        return "afterVisit"
    return "unknown"


class UploadError(ValueError):
    """Raised with a plain-language message the UI can show and speak."""


def extract_upload(filename: str, content_type: str, data: bytes) -> Document:
    if len(data) == 0:
        raise UploadError("That file is empty. Please choose another file or paste the text.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("That file is larger than 2 MB. Please upload a smaller file or paste the text.")
    name = Path(filename or "upload").name
    low = name.lower()
    if low.endswith(".pdf") or content_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
        except Exception as exc:  # pragma: no cover - depends on the file
            raise UploadError("I couldn't open that PDF. Please try a different file or paste the text.") from exc
        if not any(p.strip() for p in pages):
            raise UploadError(
                "This PDF has no readable text (it may be a scanned image). "
                "Please paste the text instead."
            )
    elif content_type.startswith("image/") or low.endswith((".png", ".jpg", ".jpeg", ".heic", ".webp")):
        raise UploadError(
            "Reading photos of documents isn't available in this demo yet. "
            "Please upload a PDF or text file, or paste the text."
        )
    else:
        try:
            pages = [data.decode("utf-8")]
        except UnicodeDecodeError as exc:
            raise UploadError("I can only read text files, PDFs, or pasted text.") from exc
    text = "\n".join(pages)
    return Document(
        id=f"upload-{uuid.uuid4().hex[:10]}",
        type=guess_type(text),
        name=name,
        synthetic=False,
        pages=pages,
    )


def from_pasted_text(text: str, name: str = "Pasted text") -> Document:
    if not text or not text.strip():
        raise UploadError("There's no text to read yet. Please paste your document text.")
    if len(text) > 100_000:
        raise UploadError("That text is too long for this demo. Please paste a shorter section.")
    return Document(
        id=f"paste-{uuid.uuid4().hex[:10]}",
        type=guess_type(text),
        name=name,
        synthetic=False,
        pages=[text],
    )
