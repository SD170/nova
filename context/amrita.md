# Amrita — context + notes

Owner: Amrita (GitHub: AmritaSeeram)
Proposed role: **Academic intelligence — retrieval + quiz + study plan**

## Role

Turn Canvas course materials into grounded answers, quiz questions, and a personalized revision plan. Every output cites source passages.

**Does NOT own:** OAuth, UI, tool routing.

## Deliverables

- Document ingestion: chunk + embed course materials (PDFs, slides, notes) handed over from the Canvas adapter
- Vector store (Mongo Atlas / Chroma / Qdrant — pick fast)
- `generate_exam_quiz(course_id, topic_hints?) → [{q, type, choices?, expected, source_passages: [{chunk_id, text, source_url}]}]`
- `evaluate_quiz_answer(question_id, student_answer) → {correct, score, explanation, source_passages: [...]}`
- `suggest_study_plan(weak_topics, free_slots, deadlines) → [{block_start, block_end, topic, materials: [...]}]`
- Weak-topic identification from quiz performance

## Grounding rule (hard)

Every quiz question must be answerable from a retrieved passage. Return `source_passages` on every response. **No hallucinated exam coverage.**

## Open questions

- Which embedding model? OpenAI text-embedding-3-small vs Gemini embedding-004 vs local
- Vector DB: Mongo Atlas Vector Search (sponsor prize), Chroma (fastest to set up), Qdrant?
- Chunk size + overlap for course PDFs?
- How do we evaluate open-ended answers (not just MCQ)? LLM-as-judge with rubric?

## Ideas

- 

## Blockers

- Need course materials (real or sample) from Abishek early
- 
