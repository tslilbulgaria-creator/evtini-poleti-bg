"""One-off: rebuild captions of already-posted deals so no bare shop domain is auto-linked."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deals

# message_id -> start of product name as posted
POSTS = {
    2: "Дамски ортопедични сандали от естествена кожа ST.FLY AQUA III",
    3: "Мъжки обувки от естествена кожа ST.FLY STREAM NAPPA S24 BROWN",
    5: "Прахосмукачка робот Roborock Q Revo Edge",
    6: "Hayari Paris ONLY FOR HER парфюм за жени 100 мл",
}
products = []
for url in deals.FEED_URLS:
    products += deals.parse_feed(deals.fetch_feed(url))[1]
for mid, start in POSTS.items():
    p = next((x for x in products if x["name"].startswith(start)), None)
    if not p:
        print("not found", mid); continue
    try:
        deals.tg("editMessageCaption", {"chat_id": deals.DEALS_CHANNEL, "message_id": mid,
                                         "caption": deals.caption(p), "parse_mode": "HTML"})
        print("fixed", mid)
    except Exception as e:
        print("edit failed", mid, e)
