"""Branded deal image (1080x1080) for Telegram and Facebook posts."""
import io
import math
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent / "fonts" / "Montserrat.ttf"
NAVY = (10, 37, 92)
BLUE = (24, 98, 210)
YEL = (255, 190, 30)
WHITE = (255, 255, 255)
SOFT = (200, 222, 255)
BG_MONTHS = ["", "яну", "фев", "мар", "апр", "май", "юни", "юли", "авг", "сеп", "окт", "ное", "дек"]


def font(size, weight="ExtraBold"):
    f = ImageFont.truetype(str(FONT), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def fit(draw, text, max_w, start, weight="ExtraBold", min_size=40):
    size = start
    while size > min_size:
        f = font(size, weight)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return font(min_size, weight)


def background(w, h):
    vert = Image.linear_gradient("L").resize((w, h))
    horiz = Image.linear_gradient("L").rotate(90).transpose(Image.FLIP_LEFT_RIGHT).resize((w, h))
    grad = Image.blend(vert, horiz, 0.5)
    top = Image.new("RGB", (w, h), NAVY)
    bottom = Image.new("RGB", (w, h), BLUE)
    return Image.composite(bottom, top, grad)


def plane(d, cx, cy, s, ang):
    pts = [(1.0, 0), (-0.8, -0.55), (-0.35, 0), (-0.8, 0.55)]
    fold = [(1.0, 0), (-0.35, 0), (-0.55, 0.25)]
    a = math.radians(ang)
    tr = lambda p: (cx + s * (p[0] * math.cos(a) - p[1] * math.sin(a)), cy + s * (p[0] * math.sin(a) + p[1] * math.cos(a)))
    d.polygon([tr(p) for p in pts], fill=WHITE)
    d.polygon([tr(p) for p in fold], fill=SOFT)


def short_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{d.day} {BG_MONTHS[d.month]}"


def deal_image(deal, frm, to, airline, country=""):
    """Return JPEG bytes for the deal card."""
    W = H = 1080
    im = background(W, H)
    d = ImageDraw.Draw(im)
    rt = deal.get("trip") == "rt" and deal.get("return_at")

    # header
    plane(d, 110, 112, 42, -30)
    d.text((170, 112), "ЕВТИНИ ПОЛЕТИ", font=font(40), fill=WHITE, anchor="lm")
    if deal.get("typical") and deal.get("drop", 0) >= 0.2:
        badge = f"−{round(deal['drop'] * 100)}%"
        f = font(46)
        bw = d.textlength(badge, font=f) + 56
        d.rounded_rectangle([W - 80 - bw, 80, W - 80, 146], radius=33, fill=YEL)
        d.text((W - 80 - bw / 2, 113), badge, font=f, fill=NAVY, anchor="mm")

    # route
    d.text((W / 2, 300), frm, font=fit(d, frm, 900, 92), fill=WHITE, anchor="mm")
    for dx in (-150, -115, -80, 80, 115, 150):
        d.ellipse([W / 2 + dx - 6, 395 - 6, W / 2 + dx + 6, 395 + 6], fill=SOFT)
    plane(d, W / 2, 395, 40, 0)
    if country:
        d.text((W / 2, 475), to, font=fit(d, to, 900, 104), fill=YEL, anchor="mm")
        d.text((W / 2, 550), country.upper(), font=font(36, "SemiBold"), fill=SOFT, anchor="mm")
    else:
        d.text((W / 2, 490), to, font=fit(d, to, 900, 104), fill=YEL, anchor="mm")

    # price
    price = f"{deal['price']} €"
    d.text((W / 2, 675), price, font=font(200), fill=WHITE, anchor="mm")
    kind = "отиване и връщане" if rt else "в едната посока"
    d.text((W / 2, 800), kind, font=font(44, "SemiBold"), fill=SOFT, anchor="mm")

    # dates / airline pill
    dates = f"{short_date(deal['departure_at'])} – {short_date(deal['return_at'])}" if rt else short_date(deal["departure_at"])
    line = f"{dates}  ·  {airline}" if airline else dates
    f = fit(d, line, 860, 40, "Bold", 28)
    tw = d.textlength(line, font=f)
    d.rounded_rectangle([W / 2 - tw / 2 - 40, 865, W / 2 + tw / 2 + 40, 935], radius=35, fill=(255, 255, 255))
    d.text((W / 2, 900), line, font=f, fill=NAVY, anchor="mm")

    d.text((W / 2, 1020), "t.me/evtini_poleti_bg", font=font(32, "SemiBold"), fill=SOFT, anchor="mm")

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()
