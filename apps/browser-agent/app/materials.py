"""Course materials: turn Canvas Modules / Files / syllabus into a Material list,
extract text, and cache that text on disk.

Two stages (CSE 507 alone has 424 MB of PDFs, so we never download everything):
  1. LIST, every sync (cheap): one Material per study item, with module name and
     the week dates parsed from names like "(11/11 - 11/17) Module 5: Mining".
  2. TEXT, on demand: GET /materials/{id}/text downloads + extracts once, then
     serves from data/materials/ (gitignored). The sync pre-fetches only the
     current/next week's modules + the syllabus so exam prep is instant.

Everything here is pure (no network) so it is unit-tested directly.
"""

import io
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Course, Material, MaterialText, MaterialType, TextStatus

log = logging.getLogger(__name__)

# Not study material for Jarvis: archives (project templates), images, media.
SKIP_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".png", ".jpg", ".jpeg", ".gif",
            ".svg", ".webp", ".mp4", ".mov", ".mp3", ".wav", ".exe", ".dmg", ".jar"}
SKIP_CT = ("image/", "video/", "audio/", "application/zip", "application/x-rar",
           "application/vnd.rar", "application/x-7z", "application/x-tar", "application/gzip",
           "application/x-compressed", "application/x-zip")
TEXT_EXT = {".txt", ".md", ".csv", ".py", ".java", ".c", ".cpp", ".lp", ".pl"}

MAX_TEXT_CHARS = 600_000  # hard cap per document stored on disk

_WEEK = re.compile(r"(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*(?:-|–|—|to)\s*(\d{1,2})/(\d{1,2})")


# ---------------- listing ----------------

def parse_week(module_name: str, today: date | None = None) -> tuple[date, date] | None:
    """'(11/11 - 11/17) Module 5' -> (Nov 11, Nov 17) of the right year."""
    m = _WEEK.search(module_name or "")
    if not m:
        return None
    today = today or date.today()
    m1, d1, m2, d2 = map(int, m.groups())

    def year_for(month: int) -> int:  # a term spans < 6 months around today
        if month - today.month > 6:
            return today.year - 1
        if today.month - month > 6:
            return today.year + 1
        return today.year

    try:
        start = date(year_for(m1), m1, d1)
        end = date(year_for(m2), m2, d2)
    except ValueError:
        return None
    if end < start:  # e.g. 12/28 - 1/3
        end = date(start.year + 1, m2, d2)
    return start, end


def _ext(name: str) -> str:
    name = (name or "").lower()
    return name[name.rfind("."):] if "." in name else ""


def file_kind(content_type: str | None, filename: str) -> tuple[MaterialType, TextStatus] | None:
    """None = skip it entirely (archives, images, media)."""
    ct = (content_type or "").lower()
    ext = _ext(filename)
    if ext in SKIP_EXT or ct.startswith(SKIP_CT):
        return None
    if ct == "application/pdf" or ext == ".pdf":
        return MaterialType.pdf, TextStatus.not_fetched
    if ct.startswith("text/") or ext in TEXT_EXT:
        return MaterialType.file, TextStatus.not_fetched
    return MaterialType.file, TextStatus.unsupported


def file_material(course: Course, meta: dict[str, Any], base_url: str, max_bytes: int,
                  module: dict[str, Any] | None = None, item: dict[str, Any] | None = None
                  ) -> Material | None:
    """One Canvas file (from /files or a module File item + its file metadata)."""
    fid = meta.get("id") or (item or {}).get("content_id")
    name = meta.get("display_name") or meta.get("filename") or (item or {}).get("title") or ""
    kind = file_kind(meta.get("content-type"), meta.get("filename") or name)
    if kind is None:
        return None
    mtype, status = kind
    size = meta.get("size")
    if status == TextStatus.not_fetched and size and size > max_bytes:
        status = TextStatus.too_large
    if meta.get("locked_for_user"):
        status = TextStatus.locked
    url = (item or {}).get("html_url") or f"{base_url}/courses/{course.id}/files/{fid}"
    return Material(
        id=f"file-{fid}", course_id=course.id, course_code=course.code,
        title=(item or {}).get("title") or name, type=mtype, url=url,
        content_type=meta.get("content-type"), size_bytes=size,
        updated_at=_dt(meta.get("updated_at") or meta.get("modified_at")),
        text_status=status, fetch_ref=f"/api/v1/courses/{course.id}/files/{fid}",
        **_module_fields(module, item),
    )


def module_materials(course: Course, modules: list[dict[str, Any]],
                     file_meta: dict[str, dict[str, Any]], base_url: str, max_bytes: int,
                     today: date | None = None) -> list[Material]:
    """Modules (with items) -> Materials. File items use file_meta[content_id]."""
    out: list[Material] = []
    for mod in modules:
        for it in mod.get("items") or []:
            t = it.get("type")
            if t == "File":
                meta = file_meta.get(str(it.get("content_id"))) or {}
                m = file_material(course, meta, base_url, max_bytes, mod, it)
            elif t == "Page":
                slug = it.get("page_url") or ""
                m = Material(
                    id=f"page-{course.id}-{slug}", course_id=course.id, course_code=course.code,
                    title=it.get("title") or slug, type=MaterialType.page,
                    url=it.get("html_url") or f"{base_url}/courses/{course.id}/pages/{slug}",
                    fetch_ref=f"/api/v1/courses/{course.id}/pages/{slug}",
                    text_status=TextStatus.locked if _locked(it) else TextStatus.not_fetched,
                    **_module_fields(mod, it),
                )
            elif t == "ExternalUrl":
                m = Material(
                    id=f"link-{course.id}-{it.get('id')}", course_id=course.id,
                    course_code=course.code, title=it.get("title") or "",
                    type=MaterialType.link, url=it.get("external_url") or it.get("html_url") or "",
                    text_status=TextStatus.link_only, **_module_fields(mod, it),
                )
            else:  # Quiz / Assignment / Discussion are in the to-do list; SubHeader = label
                m = None
            if m:
                week = parse_week(mod.get("name", ""), today)
                if week:
                    m.week_start, m.week_end = week
                out.append(m)
    return out


def syllabus_material(course: Course, base_url: str) -> Material:
    return Material(
        id=f"syllabus-{course.id}", course_id=course.id, course_code=course.code,
        title=f"{course.code} Syllabus", type=MaterialType.syllabus,
        url=f"{base_url}/courses/{course.id}/assignments/syllabus",
        fetch_ref=f"/api/v1/courses/{course.id}?include[]=syllabus_body",
    )


_FILE_LINK = re.compile(r"/courses/\d+/files/(\d+)")


def linked_file_ids(html_body: str | None) -> list[str]:
    """Canvas file ids linked from an HTML body (syllabus), in order, unique."""
    return list(dict.fromkeys(_FILE_LINK.findall(html_body or "")))


def dedupe(materials: list[Material]) -> list[Material]:
    """Same file can sit in two modules or in Modules + Files; keep the first."""
    seen: set[str] = set()
    out = []
    for m in materials:
        if m.id not in seen:
            seen.add(m.id)
            out.append(m)
    return out


def _module_fields(mod: dict | None, it: dict | None) -> dict[str, Any]:
    if not mod:
        return {}
    return {"module": mod.get("name"), "module_position": mod.get("position"),
            "position": (it or {}).get("position")}


def _locked(it: dict[str, Any]) -> bool:
    return bool((it.get("content_details") or {}).get("locked_for_user"))


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------- picking / filtering ----------------

def in_window(m: Material, start: date, end: date) -> bool:
    return bool(m.week_start and m.week_end and m.week_start <= end and m.week_end >= start)


def select_prefetch(materials: list[Material], today: date, days: int, limit: int) -> list[Material]:
    """Syllabus + this/next week's modules: what exam prep and quizzes need first."""
    end = today + timedelta(days=days)
    picks = [m for m in materials if m.text_status == TextStatus.not_fetched
             and (_is_syllabus(m) or in_window(m, today, end))]
    picks.sort(key=lambda m: (not _is_syllabus(m), m.week_start or today))
    return picks[:limit]


def _is_syllabus(m: Material) -> bool:
    return m.type == MaterialType.syllabus or m.module == "Syllabus"


def matches_topic(m: Material, hint: str) -> bool:
    """Loose match on title + module name: any word of 3+ letters."""
    hay = f"{m.title} {m.module or ''}".lower()
    words = [w for w in re.findall(r"[a-z0-9]+", hint.lower()) if len(w) >= 3]
    return not words or any(w in hay for w in words)


# ---------------- text extraction ----------------

def extract_pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader  # lazy: only needed when a PDF is read

    reader = PdfReader(io.BytesIO(data))
    parts = [f"[page {i}]\n{_tidy(page.extract_text() or '')}"
             for i, page in enumerate(reader.pages, start=1)]
    return "\n\n".join(parts)[:MAX_TEXT_CHARS], len(reader.pages)


def _tidy(text: str) -> str:
    """Some PDFs put 2+ spaces between every word ('Final  Exam  Dec  1'): collapse them."""
    text = re.sub(r"[ \t\xa0]{2,}", " ", text)
    return re.sub(r" *\n *", "\n", text).strip()


def slice_text(full: str, offset: int, max_chars: int) -> tuple[str, int | None]:
    """Cut a slice, preferring to end at a paragraph break. Returns (text, next_offset)."""
    offset = max(0, min(offset, len(full)))
    end = offset + max_chars
    if end >= len(full):
        return full[offset:], None
    brk = full.rfind("\n\n", offset + max_chars // 2, end)
    end = brk if brk != -1 else end
    return full[offset:end], end


class TextCache:
    """data/materials/<id>.json = extracted text + the Canvas version it came from."""

    PAGE_MAX_AGE = timedelta(hours=24)  # pages carry no updated_at in module lists

    def __init__(self, directory: Path):
        self.dir = directory

    def _path(self, material_id: str) -> Path:
        return self.dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", material_id) + ".json")

    @staticmethod
    def _version(m: Material) -> str | None:
        return m.updated_at.isoformat() if m.updated_at else None

    def get(self, m: Material) -> dict[str, Any] | None:
        p = self._path(m.id)
        if not p.exists():
            return None
        try:
            entry = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        if entry.get("version") != self._version(m):
            return None  # file changed in Canvas
        if entry.get("version") is None:
            fetched = _dt(entry.get("fetched_at"))
            if not fetched or datetime.now(timezone.utc) - fetched > self.PAGE_MAX_AGE:
                return None
        return entry

    def has(self, m: Material) -> bool:
        return self.get(m) is not None

    def put(self, m: Material, text: str, pages: int | None) -> dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        entry = {"version": self._version(m), "fetched_at": datetime.now(timezone.utc).isoformat(),
                 "pages": pages, "text": text[:MAX_TEXT_CHARS]}
        tmp = self._path(m.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(entry))
        tmp.replace(self._path(m.id))
        return entry


def to_material_text(m: Material, entry: dict[str, Any], offset: int, max_chars: int) -> MaterialText:
    full = entry["text"]
    text, nxt = slice_text(full, offset, max_chars)
    return MaterialText(
        material_id=m.id, course_id=m.course_id, course_code=m.course_code, title=m.title,
        type=m.type, module=m.module, source_url=m.url,
        fetched_at=_dt(entry["fetched_at"]) or datetime.now(timezone.utc),
        pages=entry.get("pages"), total_chars=len(full), offset=offset, next_offset=nxt, text=text,
    )
