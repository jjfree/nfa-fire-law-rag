"""Build the readable PDF edition of the system manual.

The Markdown manual is the source of truth. This script intentionally handles
the small Markdown subset used by docs/SYSTEM_MANUAL.md so the PDF can be built
offline with the bundled reportlab runtime.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "SYSTEM_MANUAL.md"
OUTPUT = ROOT / "output" / "pdf" / "nfa-fire-law-rag-system-manual.pdf"


def register_fonts() -> tuple[str, str]:
    """Register a Windows Traditional Chinese font and return regular/bold names."""
    candidates = [
        (Path(r"C:\Windows\Fonts\msjh.ttc"), Path(r"C:\Windows\Fonts\msjhbd.ttc")),
        (Path(r"C:\Windows\Fonts\mingliu.ttc"), Path(r"C:\Windows\Fonts\mingliub.ttc")),
    ]
    for regular_path, bold_path in candidates:
        if not regular_path.exists():
            continue
        regular_name = "NFA-CJK-Regular"
        bold_name = "NFA-CJK-Bold"
        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path), subfontIndex=0))
        if bold_path.exists():
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path), subfontIndex=0))
        else:
            pdfmetrics.registerFont(TTFont(bold_name, str(regular_path), subfontIndex=0))
        return regular_name, bold_name
    raise FileNotFoundError("No supported Traditional Chinese Windows font was found")


def inline_markup(value: str) -> str:
    """Convert the manual's limited inline Markdown to safe ReportLab markup."""
    value = escape(value, quote=False)
    value = re.sub(r"`([^`]+)`", r'<font name="NFA-CJK-Regular">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    return value


def make_styles(font_name: str, bold_name: str) -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ManualTitle", parent=styles["Title"], fontName=bold_name,
            fontSize=20, leading=26, alignment=TA_LEFT,
            textColor=colors.HexColor("#1F2937"), spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "ManualH2", parent=styles["Heading2"], fontName=bold_name,
            fontSize=14, leading=19, textColor=colors.HexColor("#123B5D"),
            spaceBefore=11, spaceAfter=6, keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ManualH3", parent=styles["Heading3"], fontName=bold_name,
            fontSize=11.5, leading=16, textColor=colors.HexColor("#245B7A"),
            spaceBefore=8, spaceAfter=4, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ManualBody", parent=styles["BodyText"], fontName=font_name,
            fontSize=9.5, leading=15, alignment=TA_LEFT,
            textColor=colors.HexColor("#202124"), spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "ManualBullet", parent=styles["BodyText"], fontName=font_name,
            fontSize=9.3, leading=14, leftIndent=3, spaceAfter=2,
        ),
        "table": ParagraphStyle(
            "ManualTable", parent=styles["BodyText"], fontName=font_name,
            fontSize=8.2, leading=11.5, textColor=colors.HexColor("#202124"),
            spaceAfter=0,
        ),
        "table_header": ParagraphStyle(
            "ManualTableHeader", parent=styles["BodyText"], fontName=bold_name,
            fontSize=8.2, leading=11.5, textColor=colors.white, spaceAfter=0,
        ),
        "code": ParagraphStyle(
            "ManualCode", parent=styles["Code"], fontName=font_name,
            fontSize=7.8, leading=10.5, leftIndent=6, rightIndent=6,
            textColor=colors.HexColor("#1F2937"),
        ),
        "diagram": ParagraphStyle(
            "ManualDiagram", parent=styles["BodyText"], fontName=bold_name,
            fontSize=9, leading=12, alignment=TA_CENTER,
            textColor=colors.HexColor("#123B5D"),
        ),
        "arrow": ParagraphStyle(
            "ManualArrow", parent=styles["BodyText"], fontName=font_name,
            fontSize=13, leading=15, alignment=TA_CENTER,
            textColor=colors.HexColor("#6B7280"), spaceAfter=1, spaceBefore=1,
        ),
    }


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def table_rows(lines: list[str]) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]


def render_table(lines: list[str], styles: dict[str, ParagraphStyle], available_width: float) -> Table:
    rows = table_rows(lines)
    header, body = rows[0], rows[2:]
    column_count = len(header)
    if column_count == 2:
        proportions = [0.30, 0.70]
    elif column_count == 3:
        proportions = [0.23, 0.39, 0.38]
    elif column_count == 4:
        proportions = [0.14, 0.25, 0.33, 0.28]
    else:
        proportions = [1 / column_count] * column_count
    widths = [available_width * proportion for proportion in proportions]
    data = [
        [Paragraph(inline_markup(cell), styles["table_header"]) for cell in header],
        *[[Paragraph(inline_markup(cell), styles["table"]) for cell in row] for row in body],
    ]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#245B7A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F8")]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D2D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def architecture_flow(styles: dict[str, ParagraphStyle], available_width: float) -> list[object]:
    def box(label: str) -> Table:
        node = Table([[Paragraph(inline_markup(label), styles["diagram"])]])
        node.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF2F7")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#8FB3C7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return node

    def arrow(value: str) -> Paragraph:
        return Paragraph(value, styles["arrow"])

    data = [
        [box("NFA 分類頁與法規頁"), arrow("→"), box("Discovery：同網域連結探索"), arrow("→"), box("Fetcher：TLS、節流、重試")],
        [arrow("↓"), "", arrow("↓"), "", arrow("↓")],
        [box("Parser + Attachment：清理、metadata、條文與 PDF"), arrow("→"), box("Version-aware Ingest：LSID + hash"), arrow("→"), box("SQLite：laws、versions、chunks、FTS5、vectors")],
        [arrow("↓"), "", arrow("↓"), "", arrow("↓")],
        [box("Hybrid Search：lexical + NumPy cosine"), arrow("→"), box("Evidence-grounded answer：引用驗證與 web fallback"), arrow("→"), box("Streamlit UI / FastAPI / MCP stdio")],
    ]
    diagram = Table(data, colWidths=[available_width * value for value in (0.25, 0.06, 0.38, 0.06, 0.25)], hAlign="LEFT")
    diagram.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return [diagram, Spacer(1, 8)]


def markdown_to_flowables(markdown: str, styles: dict[str, ParagraphStyle], available_width: float) -> list[object]:
    lines = markdown.splitlines()
    story: list[object] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            story.append(Paragraph(inline_markup(text), styles["body"]))
            paragraph_lines.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            flush_paragraph()
            index += 1
            continue
        if line.startswith("```"):
            flush_paragraph()
            language = line[3:].strip().lower()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            if language == "mermaid":
                story.extend(architecture_flow(styles, available_width))
            else:
                story.append(Preformatted("\n".join(block), styles["code"], maxLineLength=110))
                story.append(Spacer(1, 5))
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            style_name = "title" if level == 1 else "h2" if level == 2 else "h3"
            story.append(Paragraph(inline_markup(heading.group(2)), styles[style_name]))
            index += 1
            continue
        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("|")
            and is_table_separator(lines[index + 1])
        ):
            flush_paragraph()
            table_block = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].startswith("|"):
                table_block.append(lines[index])
                index += 1
            story.append(render_table(table_block, styles, available_width))
            story.append(Spacer(1, 7))
            continue
        if re.match(r"^[-*]\s+", line):
            flush_paragraph()
            items: list[ListItem] = []
            while index < len(lines) and re.match(r"^[-*]\s+", lines[index]):
                value = re.sub(r"^[-*]\s+", "", lines[index])
                items.append(ListItem(Paragraph(inline_markup(value), styles["bullet"])))
                index += 1
            story.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=15))
            story.append(Spacer(1, 3))
            continue
        if re.match(r"^\d+\.\s+", line):
            flush_paragraph()
            items = []
            while index < len(lines) and re.match(r"^\d+\.\s+", lines[index]):
                value = re.sub(r"^\d+\.\s+", "", lines[index])
                items.append(ListItem(Paragraph(inline_markup(value), styles["bullet"])))
                index += 1
            story.append(ListFlowable(items, bulletType="1", leftIndent=18))
            story.append(Spacer(1, 3))
            continue
        paragraph_lines.append(line)
        index += 1
    flush_paragraph()
    return story


def build_pdf(source: Path = SOURCE, output: Path = OUTPUT) -> None:
    regular_font, bold_font = register_fonts()
    output.parent.mkdir(parents=True, exist_ok=True)
    page_width, _ = A4
    left_margin = 19 * mm
    right_margin = 19 * mm
    top_margin = 17 * mm
    bottom_margin = 17 * mm
    available_width = page_width - left_margin - right_margin
    styles = make_styles(regular_font, bold_font)
    document = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=left_margin, rightMargin=right_margin,
        topMargin=top_margin, bottomMargin=bottom_margin + 7 * mm,
        title="NFA Fire Law RAG 系統說明書", author="NFA Fire Law RAG",
    )
    story = markdown_to_flowables(source.read_text(encoding="utf-8"), styles, available_width)

    def draw_header_footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(regular_font, 7.5)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(left_margin, 9 * mm, "NFA Fire Law RAG 系統說明書")
        canvas.drawRightString(page_width - right_margin, 9 * mm, f"第 {doc.page} 頁")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
    print(output)


if __name__ == "__main__":
    build_pdf()
