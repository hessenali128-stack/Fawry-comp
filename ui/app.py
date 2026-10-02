"""
app.py
------
Fawry-styled Gradio app wired to the recommendation backend (through Traefik).

  Login / Sign up  -> the identifier becomes the user_id sent to the API
  On page load     -> the browser asks for the device location (lat/lon); it is sent with each recommendation request
                      and never stored. The Offers page also has a manual Area selector that overrides it.
  Home / Offers    -> live POST /recommendations (expired and out-of-area offers are filtered server-side)
  Offers buttons   -> POST /events (click / open / purchase / redemption), then fresh recommendations

Run with:  python app.py      (env: API_BASE, PORT)
"""
import os
import re

import gradio as gr

import backend as B
import components as C
import pages as P
from theme import CUSTOM_CSS, EXTRA_CSS

APP_PAGES = ["home", "wallet", "offers", "quickpay"]
PAGE_KEYS = ["login", "signup", "home", "wallet", "offers", "quickpay", "nav"]
MAX_SLOTS = 10
N_VIEW = 4 + 2 * MAX_SLOTS  # session, for-you strip, model status, area dropdown, (column, html) per slot

GEO_JS = """() => new Promise((resolve) => {
  if (!navigator.geolocation) { resolve([null, null]); return; }
  navigator.geolocation.getCurrentPosition(
    (p) => resolve([p.coords.latitude, p.coords.longitude]),
    () => resolve([null, null]),
    { timeout: 10000, maximumAge: 300000 });
})"""


def build_app():
    with gr.Blocks(css=CUSTOM_CSS + EXTRA_CSS, title="Fawry", theme=gr.themes.Base()) as demo:
        user_name = gr.State("Ahmed Mohamed")
        session = gr.State({"user_id": None, "recs": [], "lat": None, "lon": None, "area": None})
        geo_lat = gr.Number(elem_classes="fw-hidden", show_label=False)
        geo_lon = gr.Number(elem_classes="fw-hidden", show_label=False)

        with gr.Column(elem_id="fw-shell"):
            login = P.build_login_page()
            signup = P.build_signup_page()

            home = P.build_home_page()
            wallet = P.build_wallet_page()
            offers = P.build_offers_page(max_slots=MAX_SLOTS)
            quickpay = P.build_quickpay_page()

            nav_row, nav_buttons = C.bottom_nav(active="home", visible=False)

        all_page_cols = {
            "login": login["col"], "signup": signup["col"],
            "home": home["col"], "wallet": wallet["col"],
            "offers": offers["col"], "quickpay": quickpay["col"],
        }
        slots = offers["slots"]
        view_outputs = [session, home["for_you_html"], offers["model_status"], offers["area_dd"],
                        *[c for s in slots for c in (s["col"], s["html"])]]

        demo.load(None, None, [geo_lat, geo_lon], js=GEO_JS)

        # ---- helpers -------------------------------------------------
        def goto(target):
            updates = {key: gr.update(visible=(key == target)) for key in all_page_cols}
            updates["nav"] = gr.update(visible=(target in APP_PAGES))
            return updates

        def display_name(identifier):
            ident = identifier.strip()
            local_part = ident.split("@")[0] if "@" in ident else ident
            cleaned = local_part.replace(".", " ").replace("_", " ").replace("-", " ").strip()
            return cleaned.title() if cleaned else "Fawry User"

        def signup_user_id(phone, email):
            digits = re.sub(r"\D", "", phone)
            return f"USER_{digits}" if digits else "USER_" + re.sub(r"[^a-z0-9]+", "_", email.lower()).strip("_")

        def make_router(target):
            def _router(*_args):
                upd = goto(target)
                return [upd[k] for k in PAGE_KEYS]
            return _router

        outputs = [login["col"], signup["col"], home["col"],
                   wallet["col"], offers["col"], quickpay["col"], nav_row]

        # ---- live recommendations -----------------------------------------
        def view_updates(sess, data, err, area_choices=None):
            recs = sess["recs"]
            area_upd = (gr.update(choices=["Auto", *area_choices], value=sess["area"] or "Auto")
                        if area_choices is not None else gr.update())
            upd = [sess,
                   gr.update(value=C.rec_cards_html(recs) if recs else C.empty_recs_html("No recommendations to show.")),
                   gr.update(value=C.status_line(data, err)), area_upd]
            for i in range(MAX_SLOTS):
                if i < len(recs):
                    upd += [gr.update(visible=True), gr.update(value=C.rec_card_html(recs[i]))]
                else:
                    upd += [gr.update(visible=False), gr.update(value="")]
            return upd

        def fetch(sess, area_choices=None):
            if not sess.get("user_id"):
                return view_updates(sess, None, "Please log in first.")
            data, err = B.recommendations(sess["user_id"], MAX_SLOTS, sess["lat"], sess["lon"], sess["area"])
            if data:
                sess["recs"] = data["recommendations"]
            return view_updates(sess, data, err, area_choices)

        def new_session(user_id, lat, lon):
            return {"user_id": user_id, "recs": [], "lat": lat, "lon": lon, "area": None}

        # ---- auth flow -------------------------------------------------
        def do_login(identifier, password, lat, lon, sess):
            ok = bool(identifier and password)
            if not ok:
                upd = goto("login")
                return ["⚠️ Please enter your customer ID / email / phone and password.",
                        *[upd[k] for k in PAGE_KEYS], gr.skip(), gr.skip(), *[gr.skip()] * N_VIEW]
            sess = new_session(identifier.strip(), lat, lon)
            name = display_name(identifier)
            upd = goto("home")
            return ["✅ Logged in! Redirecting...", *[upd[k] for k in PAGE_KEYS],
                    gr.update(value=C.app_header_html(name=name)), name, *fetch(sess, B.areas())]

        def do_signup(name, phone, email, password, lat, lon, sess):
            ok = all([name, phone, email, password])
            if not ok:
                upd = goto("signup")
                return ["⚠️ Please fill in every field.",
                        *[upd[k] for k in PAGE_KEYS], gr.skip(), gr.skip(), *[gr.skip()] * N_VIEW]
            uid = signup_user_id(phone, email)
            sess = new_session(uid, lat, lon)
            upd = goto("home")
            return [f"✅ Account created! Your customer ID is {uid}. Redirecting...", *[upd[k] for k in PAGE_KEYS],
                    gr.update(value=C.app_header_html(name=name)), name, *fetch(sess, B.areas())]

        login["login_btn"].click(
            do_login, inputs=[login["email"], login["password"], geo_lat, geo_lon, session],
            outputs=[login["status"], *outputs, home["header_html"], user_name, *view_outputs], api_name="login")
        signup["signup_btn"].click(
            do_signup, inputs=[signup["name"], signup["phone"], signup["email"], signup["password"],
                               geo_lat, geo_lon, session],
            outputs=[signup["status"], *outputs, home["header_html"], user_name, *view_outputs], api_name="signup")
        login["to_signup_btn"].click(make_router("signup"), outputs=outputs)
        signup["to_login_btn"].click(make_router("login"), outputs=outputs)

        # ---- offer interactions -> POST /events ----------------------------
        def make_event_handler(i, event):
            def _handler(sess):
                recs = sess.get("recs", [])
                if i >= len(recs):
                    return ["", *fetch(sess)]
                rec = recs[i]
                ok, err = B.send_event(sess["user_id"], rec["offer_id"], event)
                msg = f"✅ **{event}** sent for `{rec['offer_id']}` - recommendations refreshed." if ok else f"⚠️ {err}"
                return [msg, *fetch(sess)]
            return _handler

        event_outputs = [offers["event_status"], *view_outputs]
        for i, slot in enumerate(slots):
            for event, btn in slot["buttons"].items():
                btn.click(make_event_handler(i, event), inputs=[session], outputs=event_outputs,
                          api_name=f"ev_{i}_{event}")
        offers["refresh_btn"].click(lambda sess: ["", *fetch(sess)], inputs=[session], outputs=event_outputs,
                                    api_name="refresh")

        def on_area(choice, sess):
            sess["area"] = None if choice in (None, "Auto") else choice
            return ["", *fetch(sess)]

        offers["area_dd"].input(on_area, inputs=[offers["area_dd"], session], outputs=event_outputs, api_name="area")

        # ---- bottom nav routing -----------------------------------------
        nav_buttons["home"].click(make_router("home"), outputs=outputs)
        nav_buttons["wallet"].click(make_router("wallet"), outputs=outputs)
        nav_buttons["offers"].click(make_router("offers"), outputs=outputs)
        nav_buttons["quickpay"].click(make_router("quickpay"), outputs=outputs)
        nav_buttons["more"].click(make_router("wallet"), outputs=outputs)  # demo fallback

        # ---- header shortcut buttons -------------------------------------
        home["top_up_btn"].click(make_router("wallet"), outputs=outputs)
        wallet["add_money_btn"].click(make_router("wallet"), outputs=outputs)

    return demo


if __name__ == "__main__":
    demo = build_app()
    demo.queue(default_concurrency_limit=8)
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), show_api=False)
