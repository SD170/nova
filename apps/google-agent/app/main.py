"""HTTP layer only. All logic lives in service.py.

Run:  uvicorn app.main:app --port 9005   (from apps/google-agent/; port from shared.env)
Docs: http://localhost:9005/docs
MCP:  streamable-HTTP at /mcp (same tools, see mcp_server.py)

Auth: if CANVAS_API_KEY is set, every endpoint except /health and the docs (including /mcp
and /files) needs header `X-Canvas-Key: <key>` (use "Authorize" in /docs).
"""

import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from pydantic import BaseModel
from starlette.routing import Route

from .backends import get_backend
from .canvas_sync import CanvasClient
from .classify import Classifier
from .config import Settings, get_settings
from .documents import MEDIA, DocumentStore
from .exam import ExamPrep, speak_question, speak_score
from .memory import MemoryClient, quiz_result_text
from .feed import Feed
from .gist import Gister
from .mcp_server import KeyGuard, build_mcp
from .models import (
    AutoSyncStatus,
    CalendarEvent,
    CanvasUnavailable,
    CompanyResearch,
    DocumentNotFound,
    DocumentResult,
    DraftResult,
    EmailMessage,
    EventsResponse,
    FreeBusyResponse,
    GoogleLoginExpired,
    Health,
    InboxResponse,
    MemoryUnavailable,
    MessageNotFound,
    NewMailResponse,
    QuizNotFound,
    NewsUnavailable,
    ResearchUnavailable,
    SyncPlan,
)
from .news import NewsClient
from .research import CompanyResearcher
from .service import WorkspaceService

logging.basicConfig(level=logging.INFO)

API_KEY_HEADER = APIKeyHeader(name="X-Canvas-Key", auto_error=False,
                              description="Shared secret (CANVAS_API_KEY)")


class DraftRequest(BaseModel):
    body: str
    to: str = ""
    subject: str = ""
    reply_to_message_id: str | None = None


class EventRequest(BaseModel):
    title: str
    start: datetime
    end: datetime | None = None
    description: str = ""


class ResearchRequest(BaseModel):
    company: str
    domain: str | None = None
    role: str | None = None


class DocumentRequest(BaseModel):
    title: str
    content_markdown: str
    format: Literal["docx", "md"] = "docx"


class AutoSyncRequest(BaseModel):
    enabled: bool


class RememberRequest(BaseModel):
    fact: str
    kind: str = "fact"


class ExamRequest(BaseModel):
    course: str


class QuizStartRequest(BaseModel):
    course: str
    topic: str | None = None
    count: int = 6


class QuizBeginRequest(BaseModel):
    mode: Literal["voice", "panel"] = "voice"


class QuizAnswerRequest(BaseModel):
    choice: str            # "A".."D", "1".."4" or the option text
    index: int | None = None   # panel: which question (voice: the next one)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        backend = get_backend(settings)
        canvas = CanvasClient(settings.canvas_service_url, settings.canvas_api_key)
        docs = DocumentStore(settings.files_dir, settings.public_workspace_base)
        feed = Feed(settings.feed_path)
        exam = ExamPrep(settings, canvas, docs, feed)
        memory = MemoryClient(
            settings.supermemory_api_key,
            settings.supermemory_namespace + ("_demo" if settings.workspace_backend == "mock" else ""),
            settings.supermemory_base_url)
        exam.memory = memory

        async def save_quiz_result(quiz):   # the one fact saved automatically: how the quiz went
            if not memory.enabled:
                return
            text, meta = quiz_result_text(quiz)
            await memory.remember(text, doc_id=f"quiz_{quiz.id}", kind="quiz_result", metadata=meta)
            feed.post("memory", "Nova will remember how this quiz went", text[:120],
                      {"quiet": True, "quiz_id": quiz.id})   # quiet: shown in the panel, no toast

        exam.on_quiz_done = save_quiz_result
        svc = WorkspaceService(
            settings, backend,
            Classifier(settings.classify_cache_path,
                       settings.gemini_api_key if settings.llm_active else "",
                       settings.gemini_models, settings.gemini_timeout_seconds),
            canvas,
            CompanyResearcher(settings.tinyfish_api_key, settings.gemini_api_key,
                              settings.gemini_models, settings.gemini_timeout_seconds),
            docs,
            Gister(settings.gist_cache_path,
                   settings.gemini_api_key if settings.llm_active else "",
                   settings.gemini_models, settings.gemini_timeout_seconds),
            NewsClient(settings.news_service_url, settings.news_api_key), exam, feed, memory)
        app.state.service = svc
        if svc.state.data.get("auto_sync"):
            svc.start_auto_loop()  # resume after a restart
        async with mcp.session_manager.run():
            yield
        await svc.stop()
        await backend.close()

    def require_key(key: str | None = Security(API_KEY_HEADER)) -> None:
        expected = settings.canvas_api_key
        if expected and not (key and hmac.compare_digest(key, expected)):
            raise HTTPException(status_code=401, detail="Missing or wrong X-Canvas-Key header")

    app = FastAPI(title="Nova Gmail + Calendar agent", version="0.1.0", lifespan=lifespan)
    protected = [Depends(require_key)]

    mcp = build_mcp(lambda: app.state.service)
    mcp.streamable_http_app()  # creates mcp.session_manager
    app.router.routes.append(Route(
        "/mcp", KeyGuard(StreamableHTTPASGIApp(mcp.session_manager), settings.canvas_api_key),
        methods=["GET", "POST", "DELETE"], include_in_schema=False))

    def svc(request: Request) -> WorkspaceService:
        return request.app.state.service

    # ---------- error mapping ----------

    def err(status: int, code: str):
        async def handler(_req: Request, exc: Exception):
            return JSONResponse(status_code=status, content={"error": code, "detail": str(exc)})
        return handler

    app.add_exception_handler(GoogleLoginExpired, err(503, "google_login_expired"))
    app.add_exception_handler(MessageNotFound, err(404, "message_not_found"))
    app.add_exception_handler(DocumentNotFound, err(404, "document_not_found"))
    app.add_exception_handler(QuizNotFound, err(404, "quiz_not_found"))
    app.add_exception_handler(MemoryUnavailable, err(503, "memory_unavailable"))
    app.add_exception_handler(CanvasUnavailable, err(502, "canvas_unavailable"))
    app.add_exception_handler(ResearchUnavailable, err(503, "research_unavailable"))
    app.add_exception_handler(NewsUnavailable, err(502, "news_unavailable"))
    app.add_exception_handler(ValueError, err(422, "bad_request"))

    # ---------- routes ----------

    @app.get("/health", response_model=Health)
    async def health(request: Request):
        return await svc(request).health()

    # Gmail
    @app.get("/gmail/inbox", response_model=InboxResponse, dependencies=protected, tags=["gmail"])
    async def inbox(request: Request, hours: int = Query(72, ge=1, le=720),
                    max_results: int = Query(20, ge=1, le=50), unread_only: bool = False,
                    important_only: bool = False, category: str | None = None):
        """Classified inbox summary, important first."""
        return await svc(request).inbox(hours, max_results, unread_only, important_only, category)

    @app.get("/gmail/new", response_model=NewMailResponse, dependencies=protected, tags=["gmail"])
    async def new_mail(request: Request, mark_seen: bool = True):
        """Mail that arrived since the last call."""
        return await svc(request).new_mail(mark_seen)

    @app.get("/gmail/search", response_model=InboxResponse, dependencies=protected,
             tags=["gmail"])
    async def search(request: Request, q: str, max_results: int = Query(10, ge=1, le=30)):
        return await svc(request).search(q, max_results)

    @app.get("/gmail/messages/{message_id}", response_model=EmailMessage,
             dependencies=protected, tags=["gmail"])
    async def message(request: Request, message_id: str,
                      max_chars: int = Query(8000, ge=500, le=30_000)):
        return await svc(request).message(message_id, max_chars)

    @app.post("/gmail/drafts", response_model=DraftResult, dependencies=protected,
              tags=["gmail"])
    async def create_draft(request: Request, body: DraftRequest):
        """Saves a draft in Gmail. Never sends."""
        return await svc(request).draft(body.to, body.subject, body.body,
                                        body.reply_to_message_id)

    # Calendar
    @app.get("/calendar/events", response_model=EventsResponse, dependencies=protected,
             tags=["calendar"])
    async def events(request: Request, days_ahead: int = Query(7, ge=0, le=60),
                     days_back: int = Query(0, ge=0, le=30)):
        return await svc(request).events(days_ahead, days_back)

    @app.get("/calendar/free-busy", response_model=FreeBusyResponse, dependencies=protected,
             tags=["calendar"])
    async def free_busy(request: Request, days_ahead: int = Query(3, ge=1, le=14)):
        return await svc(request).free_busy(days_ahead)

    @app.post("/calendar/events", response_model=CalendarEvent, dependencies=protected,
              tags=["calendar"])
    async def create_event(request: Request, body: EventRequest):
        """Adds an event to the Nova calendar (never the student's own)."""
        return await svc(request).create_event(body.title, body.start, body.end, body.description)

    @app.post("/calendar/sync-canvas", response_model=SyncPlan, dependencies=protected,
              tags=["calendar"])
    async def sync_canvas(request: Request, apply: bool = False):
        """Canvas to-dos and exams -> Nova calendar. apply=false previews only."""
        return await svc(request).sync_canvas(apply)

    @app.get("/calendar/auto-sync", response_model=AutoSyncStatus, dependencies=protected,
             tags=["calendar"])
    async def auto_sync_status(request: Request):
        return svc(request).auto_status()

    @app.post("/calendar/auto-sync", response_model=AutoSyncStatus, dependencies=protected,
              tags=["calendar"])
    async def auto_sync_set(request: Request, body: AutoSyncRequest):
        return await svc(request).set_auto_sync(body.enabled)

    # News + ASU events (proxy to Amrita's service, shortened)
    @app.get("/news/headlines", dependencies=protected, tags=["news"])
    async def headlines(request: Request, topics: str = "top", count: int = Query(3, ge=1, le=6),
                        live: bool = False):
        """Compact stories (title, source, url) for the UI and the brain."""
        return await svc(request).headlines(topics, count, live)

    @app.get("/news/asu-events", dependencies=protected, tags=["news"])
    async def asu_events(request: Request, days: int = Query(7, ge=1, le=30),
                         query: str | None = None, limit: int = Query(5, ge=1, le=10)):
        return await svc(request).asu_events(days, query, limit)

    # Exam prep: exam facts, a short grounded quiz, voice or panel, flashcard PDF
    @app.post("/exam/info", dependencies=protected, tags=["exam prep"])
    async def exam_info(request: Request, body: ExamRequest):
        """Exam dates + topics from the syllabus (each backed by a quote from it)."""
        return await svc(request).exam.exam_info(body.course)

    @app.post("/quiz/start", dependencies=protected, tags=["exam prep"])
    async def quiz_start(request: Request, body: QuizStartRequest):
        """Makes a <=6 question multiple-choice quiz from real course material (15-40 s) and
        starts the flashcard PDF in the background. Returns the panel view."""
        ex = svc(request).exam
        return ex.view(await ex.create_quiz(body.course, body.topic, body.count))

    @app.get("/quiz/latest", dependencies=protected, tags=["exam prep"])
    async def quiz_latest(request: Request):
        ex = svc(request).exam
        q = ex.latest()
        if not q:
            raise QuizNotFound("No quiz yet. Start one with quiz_start.")
        return ex.view(q)

    @app.get("/quiz/{quiz_id}", dependencies=protected, tags=["exam prep"])
    async def quiz_view(request: Request, quiz_id: str):
        ex = svc(request).exam
        return ex.view(ex.get(quiz_id))

    @app.post("/quiz/{quiz_id}/begin", dependencies=protected, tags=["exam prep"])
    async def quiz_begin(request: Request, quiz_id: str, body: QuizBeginRequest):
        ex = svc(request).exam
        return ex.view(ex.begin(quiz_id, body.mode))

    @app.post("/quiz/{quiz_id}/answer", dependencies=protected, tags=["exam prep"])
    async def quiz_answer(request: Request, quiz_id: str, body: QuizAnswerRequest):
        ex = svc(request).exam
        quiz, _ = await ex.answer(quiz_id, body.choice, body.index)
        return ex.view(quiz)

    @app.post("/quiz/{quiz_id}/finish", dependencies=protected, tags=["exam prep"])
    async def quiz_finish(request: Request, quiz_id: str):
        ex = svc(request).exam
        return ex.view(await ex.finish(quiz_id))

    @app.post("/vapi/quiz", dependencies=protected, tags=["exam prep"])
    async def vapi_quiz(request: Request):
        """FAST path for the voice quiz (~0.1 s), as a Vapi function tool so a spoken answer does
        not go through the slow brain. Tools: quiz_answer(answer) and quiz_repeat(). Vapi sends
        {message:{toolCalls:[{id, function:{name, arguments}}]}} and expects
        {results:[{toolCallId, result}]}. Needs the X-Canvas-Key header (Vapi server.headers)."""
        body = await request.json()
        ex = svc(request).exam
        results = []
        for tc in (body.get("message") or {}).get("toolCalls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            try:
                quiz = ex.current_voice_quiz()
                if fn.get("name") == "quiz_repeat":
                    i = ex.next_index(quiz)
                    speak = speak_question(quiz, i if i is not None else 0)
                else:
                    quiz, finished = await ex.answer(quiz.id, args.get("answer", ""))
                    speak = speak_score(quiz) if finished else speak_question(quiz, ex.next_index(quiz))
            except (QuizNotFound, ValueError) as exc:
                speak = str(exc)
            results.append({"toolCallId": tc.get("id") or tc.get("toolCallId") or "tc", "result": speak})
        return {"results": results}

    # Memory (supermemory): the Memory tab of the side panel
    @app.get("/memory/profile", dependencies=protected, tags=["memory"])
    async def memory_profile(request: Request):
        return await svc(request).memory.profile()

    @app.get("/memory/recall", dependencies=protected, tags=["memory"])
    async def memory_recall(request: Request, q: str, limit: int = Query(5, ge=1, le=10)):
        return {"results": await svc(request).memory.recall(q, limit)}

    @app.get("/memory/recent", dependencies=protected, tags=["memory"])
    async def memory_recent(request: Request, limit: int = Query(10, ge=1, le=30)):
        return {"recent": await svc(request).memory.recent(limit)}

    @app.post("/memory/remember", dependencies=protected, tags=["memory"])
    async def memory_remember(request: Request, body: RememberRequest):
        doc_id = await svc(request).memory.remember(body.fact, kind=body.kind)
        return {"saved": True, "id": doc_id}

    @app.get("/panel/feed", dependencies=protected, tags=["panel"])
    async def panel_feed(request: Request, since: int = Query(0, ge=0)):
        """Meaningful events only (quiz ready, PDF saved, quiz score). Poll with the last id."""
        return {"events": svc(request).feed.since(since)}

    # Research + documents
    @app.post("/research/company", response_model=CompanyResearch, dependencies=protected,
              tags=["research"])
    async def research_company(request: Request, body: ResearchRequest):
        return await svc(request).research_company(body.company, body.domain, body.role)

    @app.post("/documents", response_model=DocumentResult, dependencies=protected,
              tags=["documents"])
    async def save_document(request: Request, body: DocumentRequest):
        return await svc(request).save_document(body.title, body.content_markdown, body.format)

    @app.get("/files/{doc_id}", dependencies=protected, tags=["documents"])
    async def download(request: Request, doc_id: str):
        path, meta = svc(request).docs.get(doc_id)
        return FileResponse(path, media_type=MEDIA[meta.format], filename=meta.filename)

    return app


app = create_app()
