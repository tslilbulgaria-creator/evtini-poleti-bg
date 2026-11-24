"""Scheduled engagement content for the page and channel (runs inside the regular scan).

Weekly plan (Sofia time, each posted once per day at the first run after the hour):
  Mon 12:00  Destination of the week (cheapest big drop right now)
  Tue 13:00  Travel tip
  Thu 13:00  Question to followers (comments)
  Sat 11:00  Travel tip or question
  Daily 20:30  "Top deals of the day" digest (only if 3+ deals were posted that day)
"""
import io
import textwrap

from PIL import ImageDraw

import images

TIPS = [
    "Летете във вторник или сряда — билетите в средата на седмицата често са по-евтини.",
    "Проверете размерите за безплатен ръчен багаж на Wizz Air и Ryanair, преди да тръгнете.",
    "Включете известията на канала — най-добрите оферти изчезват за часове.",
    "За полети в Европа купувайте билетите 4–8 седмици предварително.",
    "Чекирайте се онлайн — при Ryanair чекирането на летището се таксува.",
    "Сравнявайте летищата: понякога от Пловдив или Варна е много по-евтино, отколкото от София.",
    "Гъвкави сте с датите? Търсете по месец, а не по конкретен ден.",
    "Два еднопосочни билета с различни авиокомпании често излизат по-евтино от един двупосочен.",
    "Резервирайте хотела след билета — така по-лесно сравнявате общата цена.",
    "Пътувате с дете? Проверете отстъпките за деца при авиокомпанията.",
]

QUESTIONS = [
    "Къде бихте полетели за 20 €? Пишете в коментарите 👇",
    "Кое е най-евтиното пътуване, което сте правили? Споделете цената 👇",
    "Море или град — какво предпочитате за уикенд в Европа? 👇",
    "Коя дестинация искате да следим специално? Пишете и ще публикуваме, щом поевтинее 👇",
    "От кое летище летите най-често — София, Пловдив, Варна или Бургас? 👇",
    "Wizz Air или Ryanair — с кого летите по-често? 👇",
    "Тагнете приятел, с когото бихте полетели на следващото пътуване ✈️",
    "Колко най-много бихте платили за билет до Лондон в едната посока? 👇",
]

# weekday: (hour, minute, kind)
SCHEDULE = {0: (12, 0, "destination"), 1: (13, 0, "tip"), 3: (13, 0, "question"), 5: (11, 0, "mixed")}
DIGEST_TIME = (20, 30)
DIGEST_MIN_DEALS = 3


def text_card(label, text, footer="t.me/evtini_poleti_bg"):
    """Brand card with a label pill and big wrapped text. Returns JPEG bytes."""
    W = H = 1080
    im = images.background(W, H)
    d = ImageDraw.Draw(im)
    images.plane(d, 110, 112, 42, -30)
    d.text((170, 112), "ЕВТИНИ ПОЛЕТИ", font=images.font(40), fill=images.WHITE, anchor="lm")

    f = images.font(44)
    lw = d.textlength(label, font=f) + 60
    d.rounded_rectangle([W / 2 - lw / 2, 230, W / 2 + lw / 2, 300], radius=35, fill=images.YEL)
    d.text((W / 2, 265), label, font=f, fill=images.NAVY, anchor="mm")

    size = 64
    while size >= 40:
        bf = images.font(size, "Bold")
        width = max(12, int(880 / (size * 0.56)))
        lines = textwrap.wrap(text, width=width)
        if len(lines) * size * 1.3 <= 560 and all(d.textlength(l, font=bf) <= 900 for l in lines):
            break
        size -= 4
    block = len(lines) * size * 1.3
    y = 360 + (560 - block) / 2
    for line in lines:
        d.text((W / 2, y + size * 0.65), line, font=bf, fill=images.WHITE, anchor="mm")
        y += size * 1.3
    d.text((W / 2, 1020), footer, font=images.font(32, "SemiBold"), fill=images.SOFT, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def digest_card(items):
    """items: list of (route_text, price_text). Returns JPEG bytes."""
    W = H = 1080
    im = images.background(W, H)
    d = ImageDraw.Draw(im)
    images.plane(d, 110, 112, 42, -30)
    d.text((170, 112), "ЕВТИНИ ПОЛЕТИ", font=images.font(40), fill=images.WHITE, anchor="lm")
    d.text((W / 2, 250), "Топ оферти за деня", font=images.font(72), fill=images.YEL, anchor="mm")
    y = 360
    for route, price in items[:5]:
        d.rounded_rectangle([90, y, W - 90, y + 105], radius=26, fill=(255, 255, 255))
        rf = images.fit(d, route, 640, 44, "Bold", 30)
        d.text((130, y + 52), route, font=rf, fill=images.NAVY, anchor="lm")
        d.text((W - 130, y + 52), price, font=images.font(48), fill=images.BLUE, anchor="rm")
        y += 125
    d.text((W / 2, 1020), "t.me/evtini_poleti_bg", font=images.font(32, "SemiBold"), fill=images.SOFT, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def due(now, state, key, hour, minute):
    """True once per day, at the first run at or after hour:minute."""
    if state.get(key) == now.date().isoformat():
        return False
    return (now.hour, now.minute) >= (hour, minute)


def plan(now, state, todays_deals, best_deal_text):
    """Return list of (state_key, caption_html, caption_plain, jpeg) to publish now."""
    out = []
    # daily digest
    if len(todays_deals) >= DIGEST_MIN_DEALS and due(now, state, "digest", *DIGEST_TIME):
        items = sorted(todays_deals, key=lambda x: x["price"])[:5]
        lines = [f"• {i['route_text']} — {i['price']} €" for i in items]
        plain = "🔥 Топ оферти за деня\n\n" + "\n".join(lines) + \
                "\n\nВсички оферти с линкове за резервация 👉 t.me/evtini_poleti_bg"
        html = "🔥 <b>Топ оферти за деня</b>\n\n" + "\n".join(lines) + \
               "\n\nЛинковете за резервация са в публикациите по-горе 👆"
        card_items = [(i["route_text"].replace(" ⇄ ", " ↔ "), f"{i['price']} €")
                      for i in items]
        out.append(("digest", html, plain, digest_card(card_items)))

    slot = SCHEDULE.get(now.weekday())
    if slot and due(now, state, "weekly", slot[0], slot[1]):
        kind = slot[2]
        if kind == "mixed":
            kind = "tip" if state.get("mixed_toggle", 0) % 2 == 0 else "question"
            state["mixed_toggle"] = state.get("mixed_toggle", 0) + 1
        if kind == "destination":
            if best_deal_text:
                label, body, extra = "ДЕСТИНАЦИЯ НА СЕДМИЦАТА", best_deal_text["card"], best_deal_text["caption"]
                out.append(("weekly", f"🌍 <b>Дестинация на седмицата</b>\n\n{extra}",
                            f"🌍 Дестинация на седмицата\n\n{extra}", text_card(label, body)))
        elif kind == "tip":
            i = state.get("tip_i", 0) % len(TIPS)
            state["tip_i"] = i + 1
            t = TIPS[i]
            out.append(("weekly", f"💡 <b>Съвет за пътуване</b>\n\n{t}", f"💡 Съвет за пътуване\n\n{t}",
                        text_card("СЪВЕТ", t)))
        else:
            i = state.get("q_i", 0) % len(QUESTIONS)
            state["q_i"] = i + 1
            q = QUESTIONS[i]
            out.append(("weekly", q, q, text_card("ВЪПРОС КЪМ ВАС", q.replace(" 👇", "").replace(" ✈️", ""))))
    return out
