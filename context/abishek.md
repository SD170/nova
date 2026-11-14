# Abishek — context + notes

Owner: Abishek (GitHub: Abishek1801)
Proposed role: **External integrations — Canvas + Calendar adapters**

## Role

Fetch + normalize data from Canvas LMS and Google Calendar. Hand clean JSON to the orchestrator. Own the OAuth dance.

**Does NOT own:** Agent routing, quiz logic, UI.

## Deliverables

- Canvas auth (API token or OAuth)
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

- Do I have a real Canvas API token? If no → how do we demo without faking?
- Google Calendar OAuth: feasible in time, or clearly mocked?
- Canvas file download: can I extract text from PDFs/DOCX, or do I hand raw URLs to retrieval owner?

## Ideas

- 

## Blockers

- 
