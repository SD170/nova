"""The exam-prep PDF: a small flashcard sheet (1-2 pages), questions + answers + sources."""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .quiz_models import ExamInfo, Quiz

LETTERS = "ABCD"


def pdf_safe(text: str) -> str:
    """Built-in PDF fonts only cover Windows-1252: replace anything else instead of drawing boxes."""
    return escape((text or "").encode("cp1252", errors="replace").decode("cp1252"))


def build_flashcards_pdf(quiz: Quiz, exam: ExamInfo | None = None) -> bytes:
    base = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18,
                           leading=22, spaceAfter=2, alignment=0)
    sub = ParagraphStyle("s", parent=base["Normal"], fontName="Helvetica", fontSize=9.5,
                         leading=13, textColor=colors.HexColor("#555555"))
    tag = ParagraphStyle("g", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.5,
                         textColor=colors.HexColor("#2a6f4f"), leading=11)
    q = ParagraphStyle("q", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=11,
                       leading=14, spaceBefore=2, spaceAfter=4)
    opt = ParagraphStyle("o", parent=base["Normal"], fontName="Helvetica", fontSize=10,
                         leading=13, leftIndent=10)
    ans = ParagraphStyle("a", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10,
                         leading=13, textColor=colors.HexColor("#1b5e3a"), spaceBefore=5)
    why = ParagraphStyle("w", parent=base["Normal"], fontName="Helvetica", fontSize=9.5, leading=12)
    src = ParagraphStyle("r", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=8,
                         leading=10, textColor=colors.HexColor("#777777"))

    story = [Paragraph(pdf_safe(quiz.title), title)]
    meta = [f"{quiz.course_code} exam prep cards", f"{len(quiz.questions)} questions",
            "cover the answers and test yourself"]
    story.append(Paragraph(pdf_safe(" | ".join(meta)), sub))
    if exam and exam.exams:
        e = exam.exams[0]
        line = f"{e.name}: {e.date_text}" + (f" - {', '.join(e.topics[:4])}" if e.topics else "")
        story.append(Paragraph(pdf_safe(line), sub))
    story.append(Spacer(1, 10))

    for i, qu in enumerate(quiz.questions, 1):
        card = [Paragraph(f"CARD {i}" + (f"  |  {pdf_safe(qu.topic)}" if qu.topic else ""), tag),
                Paragraph(pdf_safe(qu.q), q)]
        card += [Paragraph(f"<b>{LETTERS[k]}.</b>  {pdf_safe(o)}", opt)
                 for k, o in enumerate(qu.options)]
        card.append(Paragraph(f"Answer: {LETTERS[qu.answer]}. {pdf_safe(qu.options[qu.answer])}", ans))
        if qu.explanation:
            card.append(Paragraph(pdf_safe(qu.explanation), why))
        cite = qu.source_title + (f", page {qu.page}" if qu.page else "")
        if cite:
            card.append(Paragraph(pdf_safe(f"Source: {cite}"), src))
        t = Table([[card]], colWidths=[6.9 * inch])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8d3")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7faf8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story += [KeepTogether(t), Spacer(1, 8)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(0.8 * inch, 0.5 * inch, "Made by Nova from your course materials")
        canvas.drawRightString(letter[0] - 0.8 * inch, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                      topMargin=0.7 * inch, bottomMargin=0.8 * inch,
                      title=quiz.title, author="Nova").build(story, onFirstPage=footer,
                                                              onLaterPages=footer)
    return buf.getvalue()
