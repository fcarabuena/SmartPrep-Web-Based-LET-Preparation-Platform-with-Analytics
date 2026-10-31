"""Small reportlab helpers for printable tables (grades, reports)."""
import io
from collections.abc import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INDIGO = colors.HexColor("#4f46e5")


def table_pdf(title: str, subtitle: str, headers: Sequence[str], rows: Sequence[Sequence], wide: bool = False,
              summary: Sequence[tuple[str, str]] | None = None) -> bytes:
    buf = io.BytesIO()
    pagesize = landscape(A4) if wide else A4
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=title)
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=8, leading=10)
    head = styles["BodyText"].clone("head", fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")
    story = [
        Paragraph("Smart Prep · LET Review Platform", styles["Normal"]),
        Paragraph(title, styles["Title"]),
        Paragraph(subtitle, styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    if summary:
        story.append(Table([[Paragraph(f"<b>{k}</b>", cell), Paragraph(str(v), cell)] for k, v in summary],
                           colWidths=[50 * mm, 80 * mm], hAlign="LEFT"))
        story.append(Spacer(1, 5 * mm))
    data = [[Paragraph(str(h), head) for h in headers]]
    data += [[Paragraph("" if v is None else str(v), cell) for v in r] for r in rows]
    if len(data) == 1:
        data.append([Paragraph("No data", cell)] + [""] * (len(headers) - 1))
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()
