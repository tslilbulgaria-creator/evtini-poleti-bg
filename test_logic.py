import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as M  # noqa: E402

TODAY = date(2026, 11, 24)


def t(dest, price, day, origin="SOF", airline="W6"):
    return {"origin": origin, "destination": dest, "price": price, "airline": airline,
            "departure_at": f"2026-12-{day:02d}T10:00:00+02:00", "transfers": 0,
            "link": f"/search/SOF{day:02d}12{dest}1?t=abc"}


def test_drop_deal_detected():
    rows = [t("BCN", p, d) for p, d in [(80, 5), (85, 6), (90, 7), (78, 8), (35, 9)]]
    deals = M.find_deals(rows, {}, TODAY)
    assert len(deals) == 1 and deals[0]["price"] == 35 and deals[0]["reason"] == "drop"


def test_no_deal_when_prices_flat():
    rows = [t("BCN", p, d) for p, d in [(80, 5), (85, 6), (90, 7), (78, 8), (75, 9)]]
    assert M.find_deals(rows, {}, TODAY) == []


def test_always_deal_and_too_soon_skipped():
    rows = [t("BGY", 15, 10), t("VIE", 12, 25)]
    rows[1]["departure_at"] = "2026-11-25T10:00:00+02:00"  # tomorrow -> skipped
    deals = M.find_deals(rows, {}, TODAY)
    assert [d["destination"] for d in deals] == ["BGY"]


def test_history_used_as_typical():
    history = {"SOF-LON": {f"2026-11-{d:02d}": 90 for d in range(1, 10)}}
    deals = M.find_deals([t("LON", 45, 12)], history, TODAY)
    assert deals and deals[0]["typical"] == 90


def test_dedupe():
    now = datetime(2026, 11, 24, 12, tzinfo=ZoneInfo("Europe/Sofia"))
    posted = {"SOF-BCN": {"at": "2026-11-23T12:00:00+02:00", "price": 35}}
    assert M.already_posted({"route": "SOF-BCN", "price": 34}, posted, now)
    assert not M.already_posted({"route": "SOF-BCN", "price": 29}, posted, now)


def test_post_text():
    M.C.TP_MARKER = "400696"
    deal = M.find_deals([t("BCN", p, d) for p, d in [(80, 5), (85, 6), (90, 7), (78, 8), (35, 9)]], {}, TODAY)[0]
    text = M.format_post(deal, {}, html=False)
    print(text)
    assert "София → Барселона" in text and "35 €" in text and "marker=400696" in text and "Wizz Air" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
