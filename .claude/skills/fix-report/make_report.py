"""Render a remediation report (JSON in, A4 PDF out). See SKILL.md for the content file.

Usage: python make_report.py content.json out.pdf
Needs reportlab and a font with the report language (Yu Gothic or similar for ja, Arial or similar otherwise).
"""
import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# (regular, bold, subfont index) tried in order; the first pair that exists is used.
FONTS = {
    "ja": [
        ("C:/Windows/Fonts/YuGothR.ttc", "C:/Windows/Fonts/YuGothB.ttc", 0),
        ("C:/Windows/Fonts/BIZ-UDGothicR.ttc", "C:/Windows/Fonts/BIZ-UDGothicB.ttc", 0),
        ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/meiryob.ttc", 0),
        ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ],
    "default": [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", 0),
        ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf", 0),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", 0),
    ],
}
INK, GREY, RULE, HEAD = colors.HexColor("#222222"), colors.HexColor("#777777"), colors.HexColor("#888888"), colors.HexColor("#eeeeee")
DEFAULT_WIDTHS = {2: [0.3, 0.7], 3: [0.26, 0.16, 0.58], 4: [0.2, 0.16, 0.16, 0.48]}


def register_fonts(lang: str) -> None:
    for regular, bold, index in FONTS["ja" if lang == "ja" else "default"]:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("R", regular, subfontIndex=index))
            pdfmetrics.registerFont(TTFont("B", bold, subfontIndex=index))
            pdfmetrics.registerFontFamily("R", normal="R", bold="B", italic="R", boldItalic="B")
            return
    sys.exit(f"no usable font for lang '{lang}': install one of {[f[0] for f in FONTS['ja' if lang == 'ja' else 'default']]}")


def build(content: dict, out: str) -> None:
    lang = content.get("lang", "ja")
    register_fonts(lang)
    cjk = "CJK" if lang == "ja" else None
    size, lead = (9.5, 16.5) if lang == "ja" else (9.6, 14.5)

    def style(name, font="R", s=size, leading=lead, color=INK, **kw):
        return ParagraphStyle(name, fontName=font, fontSize=s, leading=leading, textColor=color, wordWrap=cjk, **kw)

    title = style("t", "B", 18.5, 26, spaceAfter=4)
    date = style("d", s=9.5, color=GREY, spaceAfter=14)
    h2 = style("h", "B", 13.2, 19.5, spaceBefore=8, spaceAfter=2)
    body = style("b", spaceAfter=8)
    cell = style("c", s=size - 0.7, leading=lead - 1.5)
    cell_bold = style("cb", "B", size - 0.7, lead - 1.5)

    width = A4[0] - 2 * 57
    story = [Paragraph(content["title"], title), Paragraph(content["date"], date)]
    for block in content["blocks"]:
        kind = block["type"]
        if kind == "h2":
            story += [Paragraph(block["text"], h2), HRFlowable(width="100%", thickness=0.8, color=RULE, spaceAfter=8)]
        elif kind == "p":
            story += [Paragraph(block["text"], body)]
        elif kind == "table":
            cols = len(block["columns"])
            widths = [width * w for w in block.get("widths") or DEFAULT_WIDTHS[cols]]
            data = [[Paragraph(c, cell_bold) for c in block["columns"]]]
            data += [[Paragraph(c, cell) for c in row] for row in block["rows"]]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), HEAD), ("GRID", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]))
            story += [t, Spacer(1, 12)]
        else:
            sys.exit(f"unknown block type: {kind}")
    SimpleDocTemplate(out, pagesize=A4, leftMargin=57, rightMargin=57, topMargin=52, bottomMargin=52,
                      title=content["title"], author=content.get("author", "Floorline")).build(story)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    build(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), sys.argv[2])
    print("written", sys.argv[2])
