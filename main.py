"""Евтини Полети — flight deal scanner.

Runs every 30 minutes (GitHub Actions):
  1. pulls cached cheapest prices from Travelpayouts for every Bulgarian airport
  2. compares each price to the route's typical price
  3. optionally re-checks the best candidates live (SerpApi / Google Flights)
  4. posts real deals to Telegram (and Facebook, when configured)
State (price history, what was posted) is kept in state/*.json.
"""
import json
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402
from names_bg import AIRLINES_BG, CITIES_BG  # noqa: E402

TZ = ZoneInfo("Europe/Sofia")
ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
HISTORY_FILE = STATE / "history_eur.json"
POSTED_FILE = STATE / "posted_v2.json"
COUNTERS_FILE = STATE / "counters.json"
REJECTED_FILE = STATE / "rejected.json"
NAMES_FILE = STATE / "names_en.json"

BG_MONTHS = ["", "яну", "фев", "мар", "апр", "май", "юни", "юли", "авг", "сеп", "окт", "ное", "дек"]
BG_WEEKDAYS = ["пон", "вт", "ср", "чет", "пет", "съб", "нед"]


# ---------------------------------------------------------------- helpers
def log(*a):
    print(datetime.now(TZ).strftime("%H:%M:%S"), *a, flush=True)


def http_json(url, params=None, data=None, headers=None, timeout=30):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {})
    req.add_header("Accept-Encoding", "identity")
    req.add_header("User-Agent", "evtini-poleti-scanner/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def month_list(today, n):
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------- Travelpayouts
def fetch_month(origin, month):
    """Cheapest one-way tickets from `origin` to anywhere departing in `month` (cached data).
    Merges the Bulgarian market with the default market for wider coverage."""
    base = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
    params = {
        "origin": origin, "departure_at": month, "one_way": "true", "unique": "false",
        "sorting": "price", "direct": "false", "currency": C.CURRENCY, "limit": 1000, "page": 1,
        "token": C.TP_TOKEN,
    }
    seen, out = set(), []
    for market in ([C.MARKET] if C.MARKET else []) + [None]:
        p = dict(params)
        if market:
            p["market"] = market
        res = http_json(base, p)
        if (res.get("currency") or C.CURRENCY).lower() != C.CURRENCY.lower():
            log(f"warning: got currency {res.get('currency')}, skipping")
            continue
        for r in res.get("data") or []:
            k = (r.get("destination"), r.get("departure_at"), r.get("price"))
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def load_english_names():
    names = load(NAMES_FILE, None)
    if names:
        return names
    names = {"cities": {}, "airports": {}, "airlines": {}}
    try:
        for c in http_json("https://api.travelpayouts.com/data/en/cities.json"):
            names["cities"][c["code"]] = c.get("name") or c["code"]
        for a in http_json("https://api.travelpayouts.com/data/en/airports.json"):
            names["airports"][a["code"]] = a.get("city_code") or a["code"]
        for a in http_json("https://api.travelpayouts.com/data/en/airlines.json"):
            if a.get("code"):
                names["airlines"][a["code"]] = a.get("name") or a["code"]
        save(NAMES_FILE, names)
    except Exception as e:  # names are cosmetic; never fail the run over them
        log("could not load names:", e)
    return names


def city_name(code, names):
    if code in CITIES_BG:
        return CITIES_BG[code]
    city = names.get("airports", {}).get(code, code)
    return CITIES_BG.get(city) or names.get("cities", {}).get(city) or names.get("cities", {}).get(code) or code


def airline_name(code, names):
    return AIRLINES_BG.get(code) or names.get("airlines", {}).get(code) or code


# ---------------------------------------------------------------- deal detection
def route_key(t):
    return f"{t['origin']}-{t['destination']}"


def update_history(history, tickets, today):
    """history[route][YYYY-MM-DD seen] = cheapest price seen that day. Keeps 45 days."""
    day = today.isoformat()
    for t in tickets:
        r = history.setdefault(route_key(t), {})
        p = float(t["price"])
        r[day] = min(p, r.get(day, p))
    cutoff = (today - timedelta(days=45)).isoformat()
    for r in list(history):
        history[r] = {d: p for d, p in history[r].items() if d >= cutoff}
        if not history[r]:
            del history[r]


def find_deals(tickets, history, today):
    """Return candidate deals, best first. `tickets` = raw Travelpayouts rows for one scan."""
    by_route = {}
    for t in tickets:
        by_route.setdefault(route_key(t), []).append(t)

    deals = []
    min_dep = today + timedelta(days=C.MIN_DAYS_AHEAD)
    for key, rows in by_route.items():
        prices = sorted(float(r["price"]) for r in rows)
        past = list(history.get(key, {}).values())
        samples = prices + past
        best = min(rows, key=lambda r: float(r["price"]))
        price = float(best["price"])
        dep = datetime.fromisoformat(best["departure_at"]).date()
        if dep < min_dep:
            future = [r for r in rows if datetime.fromisoformat(r["departure_at"]).date() >= min_dep]
            if not future:
                continue
            best = min(future, key=lambda r: float(r["price"]))
            price = float(best["price"])

        typical = statistics.median(samples) if len(samples) >= C.MIN_SAMPLES else None
        reason = None
        if price <= C.ALWAYS_DEAL_EUR:
            reason = "cheap"
        if typical and price <= typical * (1 - C.MIN_DROP) and typical - price >= C.MIN_SAVING_EUR:
            reason = "drop"
        if not reason:
            continue
        drop = (1 - price / typical) if typical else 0
        deals.append({
            "route": key, "origin": best["origin"], "destination": best["destination"],
            "price": round(price), "typical": round(typical) if typical else None,
            "drop": round(drop, 2), "reason": reason,
            "departure_at": best["departure_at"], "airline": best.get("airline", ""),
            "origin_airport": best.get("origin_airport") or best["origin"],
            "dest_airport": best.get("destination_airport") or best["destination"],
            "transfers": best.get("transfers", 0), "link": best.get("link", ""),
            "score": drop + (0.5 if reason == "cheap" else 0),
        })
    deals.sort(key=lambda d: d["score"], reverse=True)
    return deals


def already_posted(deal, posted, now):
    prev = posted.get(deal["route"])
    if not prev:
        return False
    age = now - datetime.fromisoformat(prev["at"])
    if age > timedelta(days=C.REPOST_AFTER_DAYS):
        return False
    return deal["price"] > prev["price"] * (1 - C.REPOST_EXTRA_DROP)


# ---------------------------------------------------------------- live verification
CITY_AIRPORTS = {
    "MIL": "MXP,BGY,LIN", "LON": "LHR,LGW,STN,LTN,LCY,SEN", "PAR": "CDG,ORY,BVA", "ROM": "FCO,CIA",
    "STO": "ARN,NYO,BMA", "BUH": "OTP,BBU", "NYC": "JFK,EWR,LGA", "WAS": "IAD,DCA,BWI", "TYO": "HND,NRT",
    "OSA": "KIX,ITM", "BER": "BER", "VCE": "VCE,TSF", "BRU": "BRU,CRL", "FRA": "FRA,HHN", "DXB": "DXB,DWC",
    "IST": "IST,SAW", "MOW": "SVO,DME,VKO", "REK": "KEF", "TCI": "TFS,TFN", "OSL": "OSL,TRF,RYG",
}


def airport_ids(code):
    return CITY_AIRPORTS.get(code, code)


def verify_live(deal):
    """Re-check price on Google Flights via SerpApi. Returns live price or None."""
    params = {
        "engine": "google_flights", "departure_id": airport_ids(deal.get("origin_airport") or deal["origin"]),
        "arrival_id": airport_ids(deal.get("dest_airport") or deal["destination"]),
        "outbound_date": deal["departure_at"][:10], "type": 2, "currency": "EUR",
        "gl": "bg", "hl": "en", "api_key": C.SERPAPI_KEY,
    }
    res = http_json("https://serpapi.com/search.json", params, timeout=60)
    prices = [f["price"] for k in ("best_flights", "other_flights") for f in res.get(k, []) if f.get("price")]
    return min(prices) if prices else None


def live_still_deal(deal, live):
    """Accept the live price if it is close to the cached one, or is still a deal on its own."""
    if not live:
        return False
    if live <= deal["price"] * C.VERIFY_TOLERANCE:
        return True
    if live <= C.ALWAYS_DEAL_EUR + 5:
        return True
    return bool(deal.get("typical")) and live <= deal["typical"] * (1 - C.MIN_DROP * 0.75)


# ---------------------------------------------------------------- formatting
def booking_link(deal):
    link = deal["link"] or f"/search/{deal['origin']}{deal['departure_at'][8:10]}{deal['departure_at'][5:7]}{deal['destination']}1"
    sep = "&" if "?" in link else "?"
    return f"https://www.aviasales.com{link}{sep}marker={C.TP_MARKER}&sub_id=tg&currency=eur&locale=bg"


def format_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{BG_WEEKDAYS[d.weekday()]}, {d.day} {BG_MONTHS[d.month]} {d.year}"


def format_post(deal, names, html=True):
    frm, to = city_name(deal["origin"], names), city_name(deal["destination"], names)
    stops = "директен полет" if not deal["transfers"] else f"{deal['transfers']} прекачване"
    b = (lambda s: f"<b>{s}</b>") if html else (lambda s: s)
    lines = [f"🔥 {b(f'{frm} → {to}')}", f"💶 само {b(str(deal['price']) + ' €')} в едната посока"]
    if deal.get("typical") and deal["drop"] >= 0.2:
        lines.append(f"📉 обикновено ~{deal['typical']} € (−{round(deal['drop'] * 100)}%)")
    lines += [
        f"📅 {format_date(deal['departure_at'])}",
        f"✈️ {airline_name(deal['airline'], names)} · {stops}",
        "",
        f"👉 Резервирай: {booking_link(deal)}",
        "",
        "⚠️ Цените се променят бързо — проверете преди да платите.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- publishing
def post_telegram(text):
    url = f"https://api.telegram.org/bot{C.TG_BOT_TOKEN}/sendMessage"
    res = http_json(url, data={"chat_id": C.TG_CHANNEL, "text": text, "parse_mode": "HTML",
                               "disable_web_page_preview": "true"})
    if not res.get("ok"):
        raise RuntimeError(f"Telegram error: {res}")


def post_facebook(text, link):
    url = f"https://graph.facebook.com/v21.0/{C.FB_PAGE_ID}/feed"
    res = http_json(url, data={"message": text, "link": link, "access_token": C.FB_PAGE_TOKEN})
    if "id" not in res:
        raise RuntimeError(f"Facebook error: {res}")


def publish(deal, names):
    if C.DRY_RUN:
        log("DRY RUN — would post:\n" + format_post(deal, names, html=False))
        return
    post_telegram(format_post(deal, names))
    if C.FB_PAGE_ID and C.FB_PAGE_TOKEN:
        try:
            post_facebook(format_post(deal, names, html=False).replace("&sub_id=tg", "&sub_id=fb"),
                          booking_link(deal).replace("sub_id=tg", "sub_id=fb"))
        except Exception as e:
            log("Facebook post failed:", e)


# ---------------------------------------------------------------- main
def run():
    if not C.TP_TOKEN or not C.TG_BOT_TOKEN:
        sys.exit("Missing TP_TOKEN or TG_BOT_TOKEN")
    now = datetime.now(TZ)
    today = now.date()
    history, posted = load(HISTORY_FILE, {}), load(POSTED_FILE, {})
    rejected = load(REJECTED_FILE, {})
    counters = load(COUNTERS_FILE, {})
    if counters.get("day") != today.isoformat():
        counters = {"day": today.isoformat(), "posts": 0, "verifies": 0}

    tickets = []
    for origin in C.ORIGINS:
        for month in month_list(today, C.MONTHS_AHEAD):
            try:
                rows = fetch_month(origin, month)
                tickets += rows
                log(f"{origin} {month}: {len(rows)} prices")
            except Exception as e:
                log(f"{origin} {month}: fetch failed: {e}")

    deals = find_deals(tickets, history, today)  # judge against history BEFORE adding today's prices
    update_history(history, tickets, today)
    log(f"{len(tickets)} prices scanned, {len(deals)} candidate deals")

    in_window = C.POST_HOUR_START <= now.hour < C.POST_HOUR_END
    names = load_english_names() if deals else {}
    posted_now = verified_now = 0
    for deal in deals:
        if not in_window or posted_now >= C.MAX_POSTS_PER_RUN or counters["posts"] >= C.MAX_POSTS_PER_DAY:
            break
        if already_posted(deal, posted, now):
            continue
        rej = rejected.get(deal["route"])
        if rej and now - datetime.fromisoformat(rej["at"]) < timedelta(hours=12) and deal["price"] >= rej["price"]:
            continue
        if C.SERPAPI_KEY:
            if verified_now >= C.MAX_VERIFY_PER_RUN or counters["verifies"] >= C.MAX_VERIFY_PER_DAY:
                break
            verified_now += 1
            counters["verifies"] += 1
            try:
                live = verify_live(deal)
            except Exception as e:
                log("verify failed:", e)
                continue
            log(f"verify {deal['route']}: cached {deal['price']} live {live}")
            if not live_still_deal(deal, live):
                rejected[deal["route"]] = {"at": now.isoformat(), "price": deal["price"]}
                continue
            deal["price"] = round(live)
        try:
            publish(deal, names)
        except Exception as e:
            log("publish failed:", e)
            continue
        if C.DRY_RUN:
            posted_now += 1
            continue
        posted[deal["route"]] = {"at": now.isoformat(), "price": deal["price"]}
        posted_now += 1
        counters["posts"] += 1
        log(f"POSTED {deal['route']} {deal['price']}€")

    cutoff = now - timedelta(days=30)
    posted = {k: v for k, v in posted.items() if datetime.fromisoformat(v["at"]) > cutoff}
    save(HISTORY_FILE, history)
    save(POSTED_FILE, posted)
    save(COUNTERS_FILE, counters)
    cutoff_r = now - timedelta(hours=12)
    save(REJECTED_FILE, {k: v for k, v in rejected.items() if datetime.fromisoformat(v["at"]) > cutoff_r})


def send_test():
    post_telegram("✅ Тест: ботът на <b>Евтини Полети</b> работи. Скоро тук ще публикуваме най-евтините полети от България ✈️")
    log("telegram test message sent")
    if C.FB_PAGE_ID and C.FB_PAGE_TOKEN:
        post_facebook("✈️ Добре дошли в Евтини Полети БГ! Тук ще публикуваме най-евтините полети от София, "
                      "Пловдив, Варна и Бургас веднага щом ги открием. Последвайте страницата, за да не "
                      "изпуснете следващата оферта! 🔔", "https://t.me/evtini_poleti_bg")
        log("facebook test post published")


if __name__ == "__main__":
    send_test() if "--test" in sys.argv else run()
