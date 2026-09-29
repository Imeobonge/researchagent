from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptRGBColor
from pptx.util import Inches as PptInches, Pt as PptPt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def export_report(report: dict, file_type: str) -> tuple[bytes, str, str]:
    safe_name = re.sub(r"[^a-zA-Z0-9]+", "-", report["topic"]).strip("-").lower()[:60] or "research-report"
    markdown = report["report_markdown"]
    if file_type == "Markdown":
        return markdown.encode("utf-8"), f"{safe_name}.md", "text/markdown"
    if file_type == "Text":
        return markdown_to_text(markdown).encode("utf-8"), f"{safe_name}.txt", "text/plain"
    if file_type == "PDF":
        return make_pdf(markdown), f"{safe_name}.pdf", "application/pdf"
    if file_type == "Word":
        return make_docx(markdown), f"{safe_name}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if file_type == "PowerPoint":
        return make_pptx(markdown, report["topic"]), f"{safe_name}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    raise ValueError(f"Unsupported file type: {file_type}")


def parse_markdown(markdown: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    paragraph: list[str] = []
    def flush() -> None:
        if paragraph:
            blocks.append(("p", " ".join(paragraph)))
            paragraph.clear()
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("### "):
            flush(); blocks.append(("h3", line[4:]))
        elif line.startswith("## "):
            flush(); blocks.append(("h2", line[3:]))
        elif line.startswith("# "):
            flush(); blocks.append(("h1", line[2:]))
        elif re.match(r"^[-*]\s+", line):
            flush(); blocks.append(("bullet", line[2:]))
        elif re.match(r"^\d+\.\s+", line):
            flush(); blocks.append(("number", re.sub(r"^\d+\.\s+", "", line)))
        else:
            paragraph.append(line)
    flush()
    return blocks


def markdown_to_text(markdown: str) -> str:
    text = re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1 (\2)", markdown)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("*", "")
    return text


def make_pdf(markdown: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title="Astra Research Report", author="Astra Research")
    styles = getSampleStyleSheet()
    purple = colors.HexColor("#6D28D9")
    styles.add(ParagraphStyle(name="AstraTitle", parent=styles["Title"], textColor=purple, fontSize=24, leading=29, spaceAfter=14))
    styles.add(ParagraphStyle(name="AstraH2", parent=styles["Heading2"], textColor=purple, fontSize=15, leading=19, spaceBefore=13, spaceAfter=7))
    styles.add(ParagraphStyle(name="AstraH3", parent=styles["Heading3"], textColor=colors.HexColor("#4C1D95"), fontSize=12, leading=15, spaceBefore=9))
    styles.add(ParagraphStyle(name="AstraBody", parent=styles["BodyText"], fontSize=9.5, leading=14, alignment=TA_LEFT, spaceAfter=6))
    story = []
    for kind, text in parse_markdown(markdown):
        clean = escape(re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1 (\2)", text))
        style = {"h1": "AstraTitle", "h2": "AstraH2", "h3": "AstraH3"}.get(kind, "AstraBody")
        prefix = "• " if kind == "bullet" else ""
        story.append(Paragraph(prefix + clean, styles[style]))
        if kind.startswith("h"):
            story.append(Spacer(1, 2*mm))
    doc.build(story, onFirstPage=_pdf_header, onLaterPages=_pdf_header)
    return buffer.getvalue()


def _pdf_header(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#6D28D9"))
    canvas.rect(0, A4[1] - 5*mm, A4[0], 5*mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(A4[0] - 18*mm, 9*mm, f"ASTRA RESEARCH  ·  {doc.page}")
    canvas.restoreState()


def make_docx(markdown: str) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7); section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8); section.right_margin = Inches(0.8)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"; styles["Normal"].font.size = Pt(10)
    for heading in ("Title", "Heading 1", "Heading 2"):
        styles[heading].font.color.rgb = RGBColor(109, 40, 217)
    for kind, text in parse_markdown(markdown):
        clean = re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1 (\2)", text)
        if kind == "h1": doc.add_heading(clean, 0)
        elif kind == "h2": doc.add_heading(clean, 1)
        elif kind == "h3": doc.add_heading(clean, 2)
        elif kind == "bullet": doc.add_paragraph(clean, style="List Bullet")
        elif kind == "number": doc.add_paragraph(clean, style="List Number")
        else: doc.add_paragraph(clean)
    buffer = io.BytesIO(); doc.save(buffer); return buffer.getvalue()


def make_pptx(markdown: str, topic: str) -> bytes:
    prs = Presentation()
    prs.slide_width = PptInches(13.333); prs.slide_height = PptInches(7.5)
    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_slide.background.fill.solid(); title_slide.background.fill.fore_color.rgb = PptRGBColor(8, 7, 13)
    title_slide.shapes.title.text = topic
    title_slide.placeholders[1].text = "Astra Research · Evidence-led briefing"
    _style_slide(title_slide)
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"; body: list[str] = []
    for kind, text in parse_markdown(markdown):
        if kind == "h1": continue
        if kind in {"h2", "h3"}:
            if body: sections.append((current_title, body))
            current_title = text; body = []
        else:
            body.append(re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1", text))
    if body: sections.append((current_title, body))
    for heading, items in sections:
        for offset in range(0, len(items) or 1, 6):
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.background.fill.solid(); slide.background.fill.fore_color.rgb = PptRGBColor(8, 7, 13)
            slide.shapes.title.text = heading
            frame = slide.placeholders[1].text_frame; frame.clear()
            for idx, item in enumerate(items[offset:offset+6]):
                p = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
                p.text = item[:420]; p.level = 0; p.font.size = PptPt(18); p.font.color.rgb = PptRGBColor(226, 221, 242)
            _style_slide(slide)
    buffer = io.BytesIO(); prs.save(buffer); return buffer.getvalue()


def _style_slide(slide) -> None:
    if slide.shapes.title:
        for paragraph in slide.shapes.title.text_frame.paragraphs:
            paragraph.font.color.rgb = PptRGBColor(167, 139, 250)
            paragraph.font.size = PptPt(30)
            paragraph.font.bold = True

