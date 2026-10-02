"""
Fawry web app (Gradio shell + custom HTML UI, responsive phone / tablet / desktop).

One bridge: every clickable element in views.py carries data-act; theme.HEAD_JS posts {a, v, fields, geo} into a hidden
textbox and clicks a hidden button, and act() below runs the action and re-renders the page.
  Accounts/wallet -> store.py (SQLite; existing customers seeded on first start, new sign-ups appended)
  Recommendations -> POST /recommendations   All offers -> GET /offers   Interactions -> POST /events

Run:  python app.py      (env: API_BASE, PORT, DATA_DIR, DEMO_PASSWORD)
"""
import json
import os

import gradio as gr

import backend as B
import catalog
import store
import views as V
from theme import CSS, HEAD_JS

TOP_N = 10


def refresh(st, recs=True):
    """Reload user + wallet + whatever offers the current tab needs."""
    u = store.get(st["user"]["user_id"]); st["user"], st["tx"] = u, store.tx(u["user_id"], 30)
    if not st.get("areas"): st["areas"] = B.areas()
    st["oerr"] = None
    if st.get("tab") == "all":
        st["govs"] = catalog.GOVS
        st["all"] = catalog.search(st.get("q", ""), st.get("cat", ""), st.get("gov", ""), bool(st.get("active_only")), st.get("limit", 24))
    elif recs:
        geo = st.get("geo") or (None, None)
        data, err = B.recommendations(u["user_id"], TOP_N, geo[0], geo[1], st.get("area"))
        if data: st["recs"] = data["recommendations"]
        st["oerr"] = err or (data or {}).get("warning")
    return st


def say(st, msg, err=False): st["msg"], st["err"] = msg, err


def amount(f):
    try:
        x = float(str(f.get("amount", "")).replace(",", "").strip()); return x if 0 < x <= 100000 else None
    except ValueError:
        return None


def act(payload, st):
    st = dict(st or {"page": "login"}); st["msg"] = ""
    try:
        p = json.loads(payload)
    except (TypeError, ValueError):
        return V.render(st), st
    a, v, f = p["a"], p.get("v", ""), p.get("f", {})
    st["n"] = p.get("n", 0)
    if p.get("geo"): st["geo"] = tuple(p["geo"])
    u = st.get("user")

    if a == "page": st["page"] = v
    elif a == "login":
        user, err = store.login(f.get("id", ""), f.get("pw", ""))
        if err: say(st, err, True)
        else: st.update(user=user, page="home", tab="rec", cat="", q="", area=None, gov="", limit=24, active_only=False); refresh(st); say(st, f"Welcome, {user['name'].split()[0]}!")
    elif a == "signup":
        user, err = store.signup(f.get("name", "") or "", f.get("phone", ""), f.get("email", ""), f.get("pw", ""))
        if not f.get("name", "").strip(): user, err = None, "Please enter your full name."
        if err: say(st, err, True)
        else: st.update(user=user, page="home", tab="rec", cat="", q="", area=None, gov="", limit=24, active_only=False); refresh(st); say(st, f"Account created. Your customer ID is {user['user_id']}.")
    elif not u: pass
    elif a == "logout": st = {"page": "login"}; say(st, "Logged out.")
    elif a == "go":
        st["page"] = v
        if v == "offers" and not st.get("tab"): st["tab"] = "rec"
        refresh(st)
    elif a == "tab": st.update(tab=v, limit=24); refresh(st)
    elif a == "cat": st.update(cat=v, limit=24); refresh(st)
    elif a == "gov": st.update(gov=v, limit=24); refresh(st)
    elif a == "active": st.update(active_only=bool(v), limit=24); refresh(st)
    elif a == "more": st["limit"] = st.get("limit", 24) + 24; refresh(st)
    elif a == "search":
        st.update(q=f.get("q", "").strip(), tab="all", page="offers", limit=24, cat=""); refresh(st)
    elif a.startswith("ev:"):
        ev = a[3:]
        ok, err = B.send_event(u["user_id"], v, ev)
        say(st, ("Offer opened." if ev == "open" else "Offer added to your account.") + (" Your picks are updated." if ok else "") if ok or ev == "open" else (err or "Could not save this offer right now."), not ok and ev != "open")
        refresh(st, recs=True) if st.get("tab") != "all" else refresh(st)
    elif a == "topup" or a == "amt":
        x = float(v) if a == "amt" else amount(f)
        if x is None: say(st, "Enter a valid amount.", True)
        else: store.add_tx(u["user_id"], "Wallet top-up", "topup", x); refresh(st, False); say(st, f"EGP {x:,.2f} added to your wallet.")
    elif a == "card":
        store.request_card(u["user_id"]); refresh(st, False); say(st, "Yellow Card requested - free delivery is on its way.")
    elif a == "pay": st["page"], st["biller"] = "quickpay", v; refresh(st, False)
    elif a == "dopay":
        x = amount(f)
        if not f.get("acct", "").strip(): say(st, "Enter the account / meter / mobile number.", True)
        elif x is None: say(st, "Enter a valid amount.", True)
        else:
            kind = {"Water": "water", "Internet": "internet", "Top-up": "recharge"}.get(st["biller"], "bill")
            ok, err = store.add_tx(u["user_id"], f"{st['biller']} payment", kind, -x)
            refresh(st, False); say(st, f"Paid EGP {x:,.2f} for {st['biller']}." if ok else err, not ok)
    elif a == "toast": say(st, v)
    return V.render(st), st


def build_app():
    with gr.Blocks(css=CSS, head=HEAD_JS + '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
                   title="Fawry", theme=gr.themes.Base()) as demo:
        st = gr.State({"page": "login"})
        view = gr.HTML(V.render({"page": "login"}), elem_id="fw-root")
        with gr.Group(elem_id="fw-bridge"):
            box = gr.Textbox(elem_id="fw-act", show_label=False)
            go = gr.Button("go", elem_id="fw-go")
        go.click(act, [box, st], [view, st], api_name="act", show_progress="hidden")
    return demo


if __name__ == "__main__":
    demo = build_app()
    demo.queue(default_concurrency_limit=8)
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), show_api=False)