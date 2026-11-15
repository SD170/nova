"""Course materials: ask the backend for them, then extract PDF text locally.

Backends are responsible for downloading files into data/materials/ (they hold
the logged-in session) and setting Material.local_path. This module fills in
extracted_text for any downloaded PDF that doesn't have it yet.
"""

import logging
from pathlib import Path

from .backends.base import BrowserBackend
from .models import Course, Material

log = logging.getLogger(__name__)


def extract_pdf_text(path: Path, max_chars: int = 200_000) -> str:
    from pypdf import PdfReader  # lazy: only needed when a PDF exists

    reader = PdfReader(str(path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        parts.append(f"[page {i}]\n{page.extract_text() or ''}")
    return "\n\n".join(parts)[:max_chars]


async def collect(backend: BrowserBackend, course: Course) -> list[Material]:
    materials = await backend.fetch_materials(course)
    for m in materials:
        if m.extracted_text or not m.local_path or m.type != "pdf":
            continue
        try:
            m.extracted_text = extract_pdf_text(Path(m.local_path))
        except Exception as exc:  # one bad PDF must not break the sync
            log.warning("PDF text extraction failed for %s: %s", m.local_path, exc)
    return materials
