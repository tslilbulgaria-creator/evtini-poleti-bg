"""Product-deals bot (Bulgarian): reads a Profitshare product feed of discounted products,
picks the biggest real discounts and posts them to a separate Telegram channel.
Once a day it also posts a short teaser with a link to that channel in the flights channel.

Secrets (env): PS_FEED_URL, TG_BOT_TOKEN, TG_DEALS_CHANNEL, TG_CHANNEL (flights channel).
Run:  python deals.py           normal run
      python deals.py --debug   print the feed's columns and a few parsed rows, post nothing
"""
import csv
import html
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
POSTED_FILE = STATE / "deals_posted.json"
DAY_FILE = STATE / "deals_day.json"
TZ = ZoneInfo("Europe/Sofia")

FEED_URL = os.environ.get("PS_FEED_URL", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
DEALS_CHANNEL = os.environ.get("TG_DEALS_CHANNEL", "")
FLIGHTS_CHANNEL = os.environ.get("TG_CHANNEL", "")
DRY_RUN = bool(os.environ.get("DRY_RUN"))

MIN_DISCOUNT = 0.40       # only real discounts: at least 40% off
MIN_PRICE = 10.0          # original price at least 10 EUR
MIN_SAVING = 8.0          # save at least 8 EUR
MAX_PER_RUN = 2
MAX_PER_DAY = 12
HOUR_START, HOUR_END = 8, 22
TEASER_HOUR = 18          # daily teaser in the flights channel after this hour
REPOST_AFTER_DAYS = 30

# Column detection: feed headers may be English or Bulgarian, so match by keywords.
COLS = {
    "adv": ["advertiser", "рекламодател", "adv_name"],
    "category": ["category", "категория"],
    "brand": ["manufacturer", "производител", "brand"],
    "code": ["product code", "product_code", "код"],
    "name": ["product name", "product_name", "наименование", "name"],
    "link": ["link", "линк", "url"],
    "image": ["image", "снимка", "picture", "photo"],
    "price": ["price with vat", "цена с ддс", "price_vat"],
    "promo": ["discount", "намаление", "promo", "sale"],
    "currency": ["currency", "валута"],
    "free_ship": ["free shipping", "безплатна доставка", "free_shipping"],
}


def log(*a):
    print(datetime.now(TZ).strftime("%H:%M:%S"), *a, flush=True)


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_feed():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "evtini-deals-bot/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def map_columns(header):
    low = [h.strip().lower() for h in header]
    found = {}
    # price columns first: "price with discount, with VAT" must not be taken as the normal price
    for i, h in enumerate(low):
        is_price = "price" in h or "цена" in h
        is_promo = any(k in h for k in COLS["promo"])
        no_vat = "without" in h or "без" in h
        if is_price and is_promo and not no_vat and "promo" not in found:
            found["promo"] = i
        elif is_price and not is_promo and not no_vat and "price" not in found:
            found["price"] = i
    for key in ("adv", "category", "brand", "code", "name", "link", "image", "currency", "free_ship"):
        for i, h in enumerate(low):
            if i in found.values():
                continue
            if key == "link" and ("image" in h or "снимка" in h):
                continue
            if key == "name" and ("advertiser" in h or "рекламодател" in h or "description" in h or "описание" in h):
                continue
            if any(k in h for k in COLS[key]):
                found[key] = i
                break
    return found


def num(s):
    s = (s or "").strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_feed(text):
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return [], [], {}
    header, body = rows[0], rows[1:]
    cols = map_columns(header)
    products = []
    for r in body:
        def g(k):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        price, promo = num(g("price")), num(g("promo"))
        if not price or not promo or promo >= price:
            continue
        products.append({
            "adv": g("adv"), "category": g("category"), "brand": g("brand"), "code": g("code"),
            "name": g("name"), "link": g("link"), "image": g("image"), "currency": g("currency") or "EUR",
            "free_ship": g("free_ship").lower() in ("1", "yes", "да", "true"),
            "price": round(price, 2), "promo": round(promo, 2),
            "discount": round(1 - promo / price, 3),
        })
    return header, products, cols


def key_of(p):
    return f"{p['adv']}|{p['code'] or p['name']}"


def pick(products, posted, now):
    good = []
    for p in products:
        if not p["name"] or not p["link"].startswith("http"):
            continue
        if p["discount"] < MIN_DISCOUNT or p["price"] < MIN_PRICE or p["price"] - p["promo"] < MIN_SAVING:
            continue
        prev = posted.get(key_of(p))
        if prev and now - datetime.fromisoformat(prev["at"]) < timedelta(days=REPOST_AFTER_DAYS) \
                and p["promo"] >= prev["promo"] * 0.95:
            continue
        p["score"] = p["discount"] * math.log(1 + p["price"] - p["promo"])
        good.append(p)
    good.sort(key=lambda p: p["score"], reverse=True)
    return good


def money(v, cur):
    sym = "€" if cur.upper() in ("EUR", "€") else (" лв." if cur.upper() in ("BGN", "ЛВ", "ЛВ.") else f" {cur}")
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{s} €" if sym == "€" else f"{s}{sym}"


def caption(p):
    e = html.escape
    shop = p["adv"] or "онлайн магазин"
    lines = [
        f"🔥 <b>−{round(p['discount'] * 100)}%</b> · {e(p['name'][:180])}",
        "",
        f"💶 <b>{money(p['promo'], p['currency'])}</b>  <s>{money(p['price'], p['currency'])}</s>",
        f"💰 Спестяваш {money(p['price'] - p['promo'], p['currency'])}",
        f"🏬 {e(shop)}" + (" · 🚚 безплатна доставка" if p["free_ship"] else ""),
        "",
        f'👉 <a href="{e(p["link"], quote=True)}">Виж офертата</a>',
        "",
        "⚠️ Цените и наличностите се променят бързо.",
    ]
    return "\n".join(lines)


def tg(method, data):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read().decode())
    if not res.get("ok"):
        raise RuntimeError(f"Telegram error: {res}")
    return res


def publish(p):
    cap = caption(p)
    if p["image"].startswith("http"):
        try:
            tg("sendPhoto", {"chat_id": DEALS_CHANNEL, "photo": p["image"], "caption": cap, "parse_mode": "HTML"})
            return
        except Exception as e:  # image URL rejected -> fall back to text
            log("photo failed, sending text:", e)
    tg("sendMessage", {"chat_id": DEALS_CHANNEL, "text": cap, "parse_mode": "HTML",
                       "disable_web_page_preview": "false"})


def channel_link():
    c = DEALS_CHANNEL.strip()
    return f"https://t.me/{c[1:]}" if c.startswith("@") else ""


def teaser(day):
    link = channel_link()
    if not link or not day["posted"]:
        return
    top = sorted(day["posted"], key=lambda d: d["discount"], reverse=True)[:3]
    lines = ["🛍 <b>Днешните топ намаления</b>", ""]
    for d in top:
        lines.append(f"• −{round(d['discount'] * 100)}% {html.escape(d['name'][:70])} — {money(d['promo'], d['currency'])}")
    lines += ["", f'👉 Всички оферти: <a href="{link}">{link.replace("https://", "")}</a>']
    tg("sendMessage", {"chat_id": FLIGHTS_CHANNEL, "text": "\n".join(lines), "parse_mode": "HTML",
                       "disable_web_page_preview": "true"})


def run(debug=False):
    if not FEED_URL:
        log("PS_FEED_URL is not set — nothing to do")
        return
    now = datetime.now(TZ)
    text = fetch_feed()
    header, products, cols = parse_feed(text)
    log(f"feed: {len(text)} bytes, {len(products)} discounted products, columns mapped: {cols}")
    if debug:
        log("header:", header)
        for p in sorted(products, key=lambda p: p["discount"], reverse=True)[:5]:
            log("sample:", {k: p[k] for k in ("adv", "name", "price", "promo", "discount", "currency")})
        return
    posted = load(POSTED_FILE, {})
    day = load(DAY_FILE, {})
    if day.get("day") != now.date().isoformat():
        day = {"day": now.date().isoformat(), "count": 0, "posted": [], "teaser": False}

    if HOUR_START <= now.hour < HOUR_END and DEALS_CHANNEL:
        cands = pick(products, posted, now)
        log(f"{len(cands)} candidates after filters")
        used_adv = {d.get("adv") for d in day["posted"][-3:]}
        cands.sort(key=lambda p: (p["adv"] in used_adv, -p["score"]))  # rotate shops
        sent = 0
        for p in cands:
            if sent >= MAX_PER_RUN or day["count"] >= MAX_PER_DAY:
                break
            try:
                if not DRY_RUN:
                    publish(p)
            except Exception as e:
                log("publish failed:", e)
                continue
            sent += 1
            log(f"POSTED −{round(p['discount'] * 100)}% {p['name'][:60]} {p['promo']}")
            if DRY_RUN:
                continue
            posted[key_of(p)] = {"at": now.isoformat(), "promo": p["promo"]}
            day["count"] += 1
            day["posted"].append({k: p[k] for k in ("adv", "name", "promo", "discount", "currency")})

    if not day["teaser"] and now.hour >= TEASER_HOUR and FLIGHTS_CHANNEL and not DRY_RUN:
        try:
            teaser(day)
            day["teaser"] = True
        except Exception as e:
            log("teaser failed:", e)

    cutoff = now - timedelta(days=60)
    posted = {k: v for k, v in posted.items() if datetime.fromisoformat(v["at"]) > cutoff}
    if not DRY_RUN:
        save(POSTED_FILE, posted)
        save(DAY_FILE, day)


if __name__ == "__main__":
    run(debug="--debug" in sys.argv)
