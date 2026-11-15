# Abishek — context + notes

Owner: Abishek (GitHub: Abishek1801)
Proposed role: **External integrations — Canvas + Calendar adapters**

## Role

Fetch + normalize data from Canvas LMS and Google Calendar. Hand clean JSON to the orchestrator. Own the OAuth dance.

**Does NOT own:** Agent routing, quiz logic, UI.

## ⚠️ Status update (Nov 14) — no Canvas API access

**We do not have Canvas API access** (no usable API token / API route for our ASU accounts). Abishek is **still planning** how to get Canvas data instead. **No approach has been decided yet** — do not assume API, scraping, or manual export until this section is updated.

What this means for teammates right now:
- The tool **names and JSON output shapes below stay the same** — build against them with mock data. Only *how* Abishek gets the data will change, not what he returns.
- Anything in this file that says "API token" or "OAuth" for Canvas is **on hold** until the approach is chosen.
- Amrita: course materials will come as mock/sample content first; real content depends on the approach chosen.

## Deliverables

- Canvas data access — **method TBD (no API available, see status above)**
- `get_courses(student_id) → [{id, code, name, term}]`
- `get_assignments(course_id) → [{id, title, due_at, source_url, points}]`
- `get_course_materials(course_id) → [{id, title, type, url, extracted_text}]`
- Google Calendar (P1):
  - `get_calendar_events(start, end) → [{id, title, start, end, busy}]`
  - `create_study_block(start, end, title, course_id) → {id, html_link}` (requires approval before call)
- Ship mocks first so orchestrator + UI can integrate immediately

## Tool contract

```json
{
  "name": "get_assignments",
  "arguments": {"course_id": "example-course"},
  "result": {
    "items": [
      {
        "id": "a1",
        "title": "Homework 3",
        "due_at": "2026-11-16T23:59:00",
        "source_url": "https://canvas.asu.edu/..."
      }
    ]
  }
}
```

## Open questions / decisions needed

- ~~Do I have a real Canvas API token?~~ **Answered: no Canvas API.** Open question now: what do we use instead to get Canvas data, and how do we demo it without faking it?
- Google Calendar OAuth: feasible in time, or clearly mocked?
- Canvas file download: can I extract text from PDFs/DOCX, or do I hand raw URLs to retrieval owner?

## Ideas

- 

## Blockers

- 
