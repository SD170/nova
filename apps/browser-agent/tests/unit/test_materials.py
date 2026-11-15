"""Pure helpers in app/materials.py, using Canvas-shaped JSON seen on real ASU courses."""

from datetime import date, datetime, timedelta, timezone

from app.materials import (
    TextCache, dedupe, file_kind, matches_topic, module_materials, parse_week,
    select_prefetch, slice_text,
)
from app.models import Course, Material, MaterialType, TextStatus

C = Course(id="266933", code="CSE 540", name="CSE 540: Data Mining", term="")
BASE = "https://canvas.asu.edu"


def test_parse_week_from_module_names():
    today = date(2026, 11, 14)
    assert parse_week("(11/11 - 11/17) Module 5: Mining", today) == (date(2026, 11, 11),
                                                                     date(2026, 11, 17))
    assert parse_week("Module 2 (12/28 – 1/3)", today) == (date(2026, 12, 28), date(2027, 1, 3))
    assert parse_week("Week of 1/5-1/11", date(2026, 12, 20)) == (date(2027, 1, 5),
                                                                 date(2027, 1, 11))
    assert parse_week("The Little Book of Deep Learning", today) is None
    assert parse_week("(13/40 - 13/41) bad", today) is None


def test_file_kind():
    assert file_kind("application/pdf", "a.pdf") == (MaterialType.pdf, TextStatus.not_fetched)
    assert file_kind(None, "notes.txt")[0] == MaterialType.file
    assert file_kind("application/vnd.ms-powerpoint", "s.ppt") == (MaterialType.file,
                                                                   TextStatus.unsupported)
    assert file_kind("application/x-rar-compressed", "proj.rar") is None
    assert file_kind("application/octet-stream", "template.zip") is None
    assert file_kind("image/png", "x.png") is None


MODULES = [
    {"id": 1, "name": "(11/11 - 11/17) Module 5: Mining", "position": 5, "items": [
        {"id": 10, "type": "SubHeader", "title": "Readings", "position": 1},
        {"id": 11, "type": "Page", "title": "5.1 Frequent Patterns", "page_url": "5-1-frequent",
         "html_url": f"{BASE}/courses/266933/modules/items/11", "position": 2},
        {"id": 12, "type": "File", "title": "Slides 5", "content_id": 900, "position": 3,
         "html_url": f"{BASE}/courses/266933/modules/items/12"},
        {"id": 13, "type": "File", "title": "Project template", "content_id": 901, "position": 4},
        {"id": 14, "type": "ExternalUrl", "title": "Paper", "external_url": "https://arxiv.org/x",
         "position": 5},
        {"id": 15, "type": "Quiz", "title": "Quiz 5", "position": 6},
        {"id": 16, "type": "Page", "title": "Locked", "page_url": "locked", "position": 7,
         "content_details": {"locked_for_user": True}},
    ]},
]
META = {
    "900": {"id": 900, "display_name": "slides5.pdf", "content-type": "application/pdf",
            "size": 2_000_000, "updated_at": "2026-11-10T00:00:00Z"},
    "901": {"id": 901, "display_name": "template.zip", "content-type": "application/zip"},
}


def test_module_materials_maps_types_and_weeks():
    mats = module_materials(C, MODULES, META, BASE, max_bytes=25_000_000,
                            today=date(2026, 11, 14))
    by_id = {m.id: m for m in mats}
    assert set(by_id) == {"page-266933-5-1-frequent", "file-900", "link-266933-14",
                          "page-266933-locked"}  # zip, quiz, subheader skipped
    pdf = by_id["file-900"]
    assert pdf.type == MaterialType.pdf and pdf.week_start == date(2026, 11, 11)
    assert pdf.module == "(11/11 - 11/17) Module 5: Mining" and pdf.title == "Slides 5"
    assert pdf.fetch_ref == "/api/v1/courses/266933/files/900"
    assert by_id["page-266933-5-1-frequent"].fetch_ref == "/api/v1/courses/266933/pages/5-1-frequent"
    assert by_id["link-266933-14"].text_status == TextStatus.link_only
    assert by_id["page-266933-locked"].text_status == TextStatus.locked


def test_big_file_is_too_large():
    meta = {"900": {**META["900"], "size": 80_000_000}}
    mats = module_materials(C, MODULES, meta, BASE, max_bytes=25_000_000)
    assert next(m for m in mats if m.id == "file-900").text_status == TextStatus.too_large


def _m(mid, **kw):
    return Material(id=mid, course_id="c", title=mid, type=kw.pop("type", MaterialType.pdf),
                    url="u", **kw)


def test_select_prefetch_syllabus_and_this_week_only():
    today = date(2026, 11, 14)
    mats = [_m("old", week_start=date(2026, 9, 1), week_end=date(2026, 9, 7)),
            _m("now", week_start=date(2026, 11, 11), week_end=date(2026, 11, 17)),
            _m("next", week_start=date(2026, 11, 18), week_end=date(2026, 11, 24)),
            _m("undated"), _m("syl", type=MaterialType.syllabus),
            _m("big", week_start=today, week_end=today, text_status=TextStatus.too_large)]
    assert [m.id for m in select_prefetch(mats, today, 7, 10)] == ["syl", "now", "next"]
    assert len(select_prefetch(mats, today, 7, 1)) == 1


def test_topic_hint_and_dedupe():
    m = _m("x", module="Module 5: Heaps")
    assert matches_topic(m, "heaps") and matches_topic(m, "module 5") is True
    assert not matches_topic(m, "graphs")
    assert [x.id for x in dedupe([_m("a"), _m("a"), _m("b")])] == ["a", "b"]


def test_slice_text_breaks_on_paragraphs():
    full = "\n\n".join(f"[page {i}]\n" + "x" * 50 for i in range(1, 11))
    part, nxt = slice_text(full, 0, 200)
    assert nxt and part.endswith("x") and full[nxt:].startswith("\n\n")
    rest, end = slice_text(full, nxt, 10_000)
    assert end is None and part + rest == full


def test_text_cache_invalidates_when_canvas_file_changes(tmp_path):
    cache = TextCache(tmp_path)
    m = _m("file-1", updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    cache.put(m, "hello", 1)
    assert cache.get(m)["text"] == "hello"
    newer = m.model_copy(update={"updated_at": datetime(2026, 11, 2, tzinfo=timezone.utc)})
    assert cache.get(newer) is None


def test_text_cache_pages_expire_after_a_day(tmp_path):
    cache = TextCache(tmp_path)
    page = _m("page-c-x", type=MaterialType.page)
    entry = cache.put(page, "body", None)
    assert cache.has(page)
    import json
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    (tmp_path / "page-c-x.json").write_text(json.dumps({**entry, "fetched_at": old}))
    assert not cache.has(page)


def test_linked_file_ids_from_syllabus_html():
    from app.materials import linked_file_ids
    body = ('<a href="https://canvas.asu.edu/courses/266933/files/555/download">PDF syllabus</a>'
            '<a href="/courses/266933/files/555?wrap=1">again</a> <a href="/courses/1/files/7">x</a>')
    assert linked_file_ids(body) == ["555", "7"]
    assert linked_file_ids(None) == []


def test_pdf_text_whitespace_is_tidied():
    from app.materials import _tidy
    assert _tidy("Final  Exam  Dec  1,  2026   \n  Proctored") == "Final Exam Dec 1, 2026\nProctored"
