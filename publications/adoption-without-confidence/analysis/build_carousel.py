"""Build the revised eight-page LinkedIn carousel.

Run from the repository root:
    python analysis/build_carousel.py
"""

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
SENTIMENT_OUT = ROOT / "outputs" / "sentiment"
OUT = (
    ROOT
    / "outputs"
    / "Favorable_Stance_Is_Not_Accuracy_Trust_LinkedIn_Carousel_2026.pdf"
)

PAGE = 1080
MARGIN = 86

INK = HexColor("#12313A")
GREEN = HexColor("#235347")
TEAL = HexColor("#2A7B73")
MINT = HexColor("#EAF2EF")
PALE = HexColor("#F5F3ED")
ORANGE = HexColor("#E76F51")
GOLD = HexColor("#C98C16")
GRAY = HexColor("#5E676B")
LIGHT_GRAY = HexColor("#D8DFDC")

pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
pdfmetrics.registerFont(TTFont("Vera-Bold", "VeraBd.ttf"))


def pstyle(name, size, leading=None, color=INK, align=TA_LEFT, font="Vera"):
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=size,
        leading=leading or size * 1.16,
        textColor=color,
        alignment=align,
        spaceAfter=0,
    )


BODY = pstyle("Body", 34, 43)
SMALL = pstyle("Small", 24, 31, GRAY)
CENTER = pstyle("Center", 34, 43, INK, TA_CENTER)


def draw_paragraph(c, text, x, top, width, style, max_height=800):
    para = Paragraph(text, style)
    _, height = para.wrap(width, max_height)
    para.drawOn(c, x, top - height)
    return height


def header(c, page_no, kicker=None):
    c.setFillColor(GREEN)
    c.rect(0, PAGE - 18, PAGE, 18, fill=1, stroke=0)
    c.setFont("Vera-Bold", 18)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, PAGE - 56, (kicker or "IMAGINATION APPLIED").upper())
    c.drawRightString(PAGE - MARGIN, PAGE - 56, f"{page_no} / 8")


def footer(c):
    c.setStrokeColor(LIGHT_GRAY)
    c.line(MARGIN, 54, PAGE - MARGIN, 54)
    c.setFont("Vera", 15)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, 29, "Josh Penzell  |  Imagination Applied")
    c.drawRightString(PAGE - MARGIN, 29, "2025 Stack Overflow Developer Survey")


def title(c, text, y=905, size=58, color=INK):
    style = pstyle("Title", size, size * 1.03, color, font="Vera-Bold")
    return draw_paragraph(c, text, MARGIN, y, PAGE - 2 * MARGIN, style)


def pill(c, text, x, y, fill=MINT, color=GREEN):
    font = "Vera-Bold"
    size = 20
    pad_x = 18
    width = stringWidth(text, font, size) + 2 * pad_x
    c.setFillColor(fill)
    c.roundRect(x, y - 8, width, 38, 19, fill=1, stroke=0)
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x + pad_x, y + 3, text)


def metric(c, x, y, value, label, width=265, accent=GREEN):
    c.setFillColor(PALE)
    c.roundRect(x, y - 185, width, 185, 18, fill=1, stroke=0)
    c.setFillColor(accent)
    c.setFont("Vera-Bold", 58)
    c.drawCentredString(x + width / 2, y - 76, value)
    style = pstyle("MetricLabel", 22, 27, INK, TA_CENTER)
    draw_paragraph(c, label, x + 22, y - 104, width - 44, style, 70)


def check(c, text, x, y, width=820, color=GREEN):
    c.setFillColor(color)
    c.circle(x + 13, y - 11, 13, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Vera-Bold", 16)
    c.drawCentredString(x + 13, y - 17, "✓")
    return draw_paragraph(c, text, x + 44, y + 4, width - 44, BODY)


def image_contain(c, path, x, y, width, height):
    image = ImageReader(str(path))
    iw, ih = image.getSize()
    scale = min(width / iw, height / ih)
    dw, dh = iw * scale, ih * scale
    c.drawImage(image, x + (width - dw) / 2, y + (height - dh) / 2,
                dw, dh, preserveAspectRatio=True, mask="auto")


def build():
    gradient = SENTIMENT_OUT / "primary_current_user_stance_gradient.png"
    required = [gradient]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Run analysis/sentiment_deep_dive.py first:\n" + "\n".join(missing))

    c = Canvas(str(OUT), pagesize=(PAGE, PAGE))
    c.setTitle("Favorable Stance Is Not Accuracy Trust")
    c.setAuthor("Josh Penzell")
    c.setSubject("Favorable stance, accuracy trust, and AI-use frequency")

    # 1 — Cover
    c.setFillColor(PALE)
    c.rect(0, 0, PAGE, PAGE, fill=1, stroke=0)
    c.setFillColor(GREEN)
    c.rect(0, 0, 32, PAGE, fill=1, stroke=0)
    pill(c, "CURRENT AI USERS  •  n = 26,102", MARGIN, 922, white, GREEN)
    draw_paragraph(
        c,
        "Favorable Stance<br/>Is <font color='#E76F51'>Not</font><br/>Accuracy Trust",
        MARGIN,
        800,
        790,
        pstyle("Cover", 75, 79, INK, font="Vera-Bold"),
    )
    draw_paragraph(
        c,
        "What current AI users reveal about reported use frequency - and why stance and trust should be measured separately.",
        MARGIN,
        480,
        820,
        pstyle("Deck", 38, 48, GREEN),
    )
    c.setStrokeColor(GOLD)
    c.setLineWidth(6)
    c.line(MARGIN, 332, 420, 332)
    draw_paragraph(
        c,
        "A robustness-first secondary analysis of the 2025 Stack Overflow Developer Survey",
        MARGIN,
        290,
        760,
        pstyle("SourceDeck", 25, 33, GRAY),
    )
    c.setFont("Vera-Bold", 22)
    c.setFillColor(INK)
    c.drawString(MARGIN, 100, "Josh Penzell  |  Imagination Applied")
    c.showPage()

    # 2 — Distinction
    header(c, 2, "Start with the construct")
    title(c, "The survey asks two different questions.", y=880, size=50)
    c.setFillColor(MINT)
    c.roundRect(MARGIN, 445, 420, 285, 22, fill=1, stroke=0)
    c.setFillColor(PALE)
    c.roundRect(574, 445, 420, 285, 22, fill=1, stroke=0)
    c.setFont("Vera-Bold", 28)
    c.setFillColor(GREEN)
    c.drawString(122, 670, "FAVORABLE STANCE")
    c.setFillColor(ORANGE)
    c.drawString(610, 670, "ACCURACY TRUST")
    draw_paragraph(
        c,
        "“How favorable is your stance on using AI tools as part of your development workflow?”",
        122,
        625,
        340,
        pstyle("Quote1", 29, 38, INK),
    )
    draw_paragraph(
        c,
        "“How much do you trust the accuracy of the output from AI tools as part of your development workflow?”",
        610,
        625,
        340,
        pstyle("Quote2", 29, 38, INK),
    )
    draw_paragraph(
        c,
        "<b>A user can value AI while still distrusting its answers enough to verify them.</b>",
        MARGIN,
        360,
        PAGE - 2 * MARGIN,
        pstyle("Insight", 41, 51, GREEN, TA_CENTER),
    )
    footer(c)
    c.showPage()

    # 3 — Gradient
    header(c, 3, "The descriptive result")
    title(c, "Among current users, daily-use frequency separates sharply.", size=49)
    metric(c, MARGIN, 790, "18.8%", "Very unfavorable", 270, ORANGE)
    metric(c, 405, 790, "31.5%", "Indifferent", 270, GOLD)
    metric(c, 724, 790, "88.1%", "Very favorable", 270, GREEN)
    image_contain(c, gradient, MARGIN, 135, PAGE - 2 * MARGIN, 410)
    draw_paragraph(
        c,
        "The middle categories are not perfectly ordered. These are same-wave associations, not causal effects.",
        MARGIN,
        116,
        PAGE - 2 * MARGIN,
        SMALL,
    )
    footer(c)
    c.showPage()

    # 4 — Same trust, different use
    header(c, 4, "The revealing comparison")
    title(c, "Even among current users who highly distrust AI accuracy…", size=49)
    c.setFillColor(PALE)
    c.roundRect(MARGIN, 390, PAGE - 2 * MARGIN, 380, 24, fill=1, stroke=0)
    c.setFont("Vera-Bold", 92)
    c.setFillColor(ORANGE)
    c.drawCentredString(310, 610, "17.7%")
    c.setFillColor(GREEN)
    c.drawCentredString(770, 610, "85.1%")
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(3)
    c.line(540, 470, 540, 710)
    draw_paragraph(c, "daily use among the<br/><b>very unfavorable</b>", 145, 548, 330, CENTER)
    draw_paragraph(c, "daily use among the<br/><b>very favorable</b>", 605, 548, 330, CENTER)
    draw_paragraph(
        c,
        "<b>Same accuracy-trust category. Very different reported frequency.</b><br/>Favorable stance and accuracy trust are not synonyms.",
        115,
        330,
        850,
        pstyle("Compare", 37, 48, INK, TA_CENTER),
    )
    footer(c)
    c.showPage()

    # 5 — Model evidence
    header(c, 5, "The classification comparison")
    title(c, "Favorable stance carries more frequency information.", size=49)
    metric(c, MARGIN, 790, "0.758", "Stance-only<br/>ROC AUC", 270, GREEN)
    metric(c, 405, 790, "0.669", "Trust-only<br/>ROC AUC", 270, GRAY)
    metric(c, 724, 790, "0.793", "Context + trust + stance<br/>ROC AUC", 270, TEAL)
    c.setFillColor(MINT)
    c.roundRect(MARGIN, 330, PAGE - 2 * MARGIN, 210, 22, fill=1, stroke=0)
    draw_paragraph(
        c,
        "Context + trust<br/><b>0.704</b><br/>Context + stance <font color='#235347'><b>0.790</b></font>",
        130,
        500,
        400,
        pstyle("Lift1", 31, 40, INK),
    )
    draw_paragraph(
        c,
        "Context + stance<br/><b>0.790</b><br/>+ trust <font color='#E76F51'><b>0.793</b></font>",
        585,
        500,
        360,
        pstyle("Lift2", 31, 40, INK),
    )
    draw_paragraph(
        c,
        "Five-fold cross-validation among current users. Classification inside one survey - not causal or future prediction.",
        MARGIN,
        270,
        PAGE - 2 * MARGIN,
        SMALL,
    )
    footer(c)
    c.showPage()

    # 6 — Counterarguments
    header(c, 6, "Put it through the ringer")
    title(c, "The data do not prove the tempting story.", y=890, size=48)
    counter_style = pstyle("Counter", 27, 34, INK)
    counterpoints = [
        "<b>Not causality:</b> use may shape stance just as stance may shape use.",
        "<b>Not a validated scale:</b> favorable stance and trust are single survey items.",
        "<b>Not an even ladder:</b> unsure is slightly above indifferent among current users.",
        "<b>Criterion proximity:</b> favoring AI use is closer to reported use than accuracy trust is.",
        "<b>Not universal:</b> Stack Overflow respondents are a voluntary sample; 77.3% of complete cases identify as professional developers.",
        "<b>Not blind trust:</b> high trust may be unsafe when system reliability is low.",
    ]
    for text, y in zip(counterpoints, [740, 625, 510, 395, 280, 165]):
        c.setFillColor(ORANGE)
        c.circle(MARGIN + 13, y - 11, 13, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Vera-Bold", 16)
        c.drawCentredString(MARGIN + 13, y - 17, "!")
        draw_paragraph(c, text, MARGIN + 44, y + 4, 820 - 44, counter_style)
    footer(c)
    c.showPage()

    # 7 — Dashboard
    header(c, 7, "What leaders should measure")
    title(c, "A better AI-adoption dashboard", size=58)
    rows = [
        ("1", "Behavior", "How often, where, and for what"),
        ("2", "Favorable stance", "Whether AI feels valuable and workable"),
        ("3", "Accuracy trust", "How much output is believed without added evidence"),
        ("4", "Verification burden", "Review, testing, rework, defects, and time"),
        ("5", "Outcomes", "Quality, speed, learning, risk, and customer impact"),
    ]
    y = 755
    for number, label, question in rows:
        c.setFillColor(MINT if int(number) % 2 else PALE)
        c.roundRect(MARGIN, y - 102, PAGE - 2 * MARGIN, 96, 12, fill=1, stroke=0)
        c.setFillColor(GREEN)
        c.setFont("Vera-Bold", 29)
        c.drawCentredString(126, y - 67, number)
        c.drawString(170, y - 50, label)
        draw_paragraph(c, question, 505, y - 24, 450, pstyle("Row", 24, 30, INK))
        y -= 116
    draw_paragraph(
        c,
        "<b>Measure these separately.</b> Then test which ones actually move when a tool, workflow, or support changes.",
        MARGIN,
        156,
        PAGE - 2 * MARGIN,
        pstyle("Measure", 31, 39, GREEN, TA_CENTER),
    )
    footer(c)
    c.showPage()

    # 8 — Close
    c.setFillColor(GREEN)
    c.rect(0, 0, PAGE, PAGE, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Vera-Bold", 20)
    c.drawString(MARGIN, 970, "IMAGINATION APPLIED RESEARCH SERIES")
    draw_paragraph(
        c,
        "Access is not adoption.<br/>Trust is not stance.<br/>Use is not confidence.",
        MARGIN,
        850,
        PAGE - 2 * MARGIN,
        pstyle("Close", 67, 82, white, TA_CENTER, "Vera-Bold"),
    )
    c.setStrokeColor(GOLD)
    c.setLineWidth(7)
    c.line(300, 515, 780, 515)
    draw_paragraph(
        c,
        "Measure stance, trust, behavior, verification, and outcomes separately - then test what changes.",
        150,
        455,
        780,
        pstyle("Final", 42, 53, white, TA_CENTER),
    )
    c.setFillColor(HexColor("#D7E8E2"))
    c.roundRect(228, 185, 624, 105, 28, fill=1, stroke=0)
    c.setFillColor(GREEN)
    c.setFont("Vera-Bold", 29)
    c.drawCentredString(540, 245, "READ THE FULL REPORT")
    c.setFont("Vera", 23)
    c.drawCentredString(540, 211, "Adoption Without Confidence?")
    c.setFillColor(white)
    c.setFont("Vera", 20)
    c.drawCentredString(540, 95, "Josh Penzell  |  Imagination Applied  |  July 2026")
    c.showPage()

    c.save()
    print(OUT)


if __name__ == "__main__":
    build()
