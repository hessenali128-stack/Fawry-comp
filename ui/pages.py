"""
pages.py
--------
Each function builds one page's contents inside a gr.Column and
returns whatever interactive handles the app needs to wire callbacks
(buttons, inputs, status labels). All visual pieces come from
components.py so every page reuses the exact same look.
"""

import gradio as gr
import components as C


# ---------------------------------------------------------------------------
# AUTH PAGES
# ---------------------------------------------------------------------------
def build_login_page():
    with gr.Column(elem_classes="fw-page", visible=True) as col:
        C.auth_shell("Welcome back", "Log in to your Fawry account to continue.")
        with gr.Column(elem_classes="fw-auth-card"):
            email = gr.Textbox(label="Customer ID, email or phone", placeholder="Your customer ID")
            password = gr.Textbox(label="Password", type="password", placeholder="••••••••")
            login_btn = gr.Button("Log in", elem_classes="fw-btn-primary")
            status = gr.Markdown("")
            gr.HTML('<div class="fw-divider">or</div>')
            to_signup_btn = gr.Button("Create a new account", elem_classes="fw-btn-outline")
    return {
        "col": col, "email": email, "password": password,
        "login_btn": login_btn, "status": status, "to_signup_btn": to_signup_btn,
    }


def build_signup_page():
    with gr.Column(elem_classes="fw-page", visible=False) as col:
        C.auth_shell("Create account", "Sign up in a minute and start paying smarter.")
        with gr.Column(elem_classes="fw-auth-card"):
            name = gr.Textbox(label="Full name", placeholder="Ahmed Mohamed")
            phone = gr.Textbox(label="Mobile number", placeholder="01xxxxxxxxx")
            email = gr.Textbox(label="Email", placeholder="you@example.com")
            password = gr.Textbox(label="Password", type="password", placeholder="Create a password")
            signup_btn = gr.Button("Create account", elem_classes="fw-btn-primary")
            status = gr.Markdown("")
            gr.HTML('<div class="fw-divider">already have an account?</div>')
            to_login_btn = gr.Button("Log in instead", elem_classes="fw-btn-outline")
    return {
        "col": col, "name": name, "phone": phone, "email": email, "password": password,
        "signup_btn": signup_btn, "status": status, "to_login_btn": to_login_btn,
    }


# ---------------------------------------------------------------------------
# MAIN APP PAGES (post-login)
# ---------------------------------------------------------------------------
def build_home_page(user_name="Ahmed Mohamed"):
    with gr.Column(elem_classes="fw-page", visible=False) as col:
        header_html, top_up_btn, statement_btn = C.page_header(name=user_name)

        gr.HTML(C.section_title_html("For you", see_all=True))
        for_you_html = gr.HTML(C.for_you_offers_html())

        gr.HTML(C.promo_card_html())

        gr.HTML(C.section_title_html("Quick pay"))
        gr.HTML(C.quick_pay_grid_html())

        gr.HTML(C.section_title_html("Do more with Fawry"))
        gr.HTML(C.feature_grid_html())

        gr.HTML(C.cashback_banner_html())

        gr.HTML(C.section_title_html("Recent payments"))
        gr.HTML(C.recent_payments_html())
    return {"col": col, "header_html": header_html, "for_you_html": for_you_html,
            "top_up_btn": top_up_btn, "statement_btn": statement_btn}


def build_wallet_page(user_name="Ahmed Mohamed"):
    with gr.Column(elem_classes="fw-page", visible=False) as col:
        gr.HTML(C.app_header_html(name=user_name, greeting="My wallet"))
        gr.HTML(C.balance_card_html())
        with gr.Row():
            add_money_btn = gr.Button("Add money", elem_classes="fw-btn-yellow", size="sm")
            send_btn = gr.Button("Send", elem_classes="fw-btn-outline", size="sm")

        gr.HTML(C.section_title_html("Linked cards", see_all=False))
        gr.HTML("""
          <div class="fw-list-row">
            <div class="fw-list-icon">💳</div>
            <div>
              <div class="fw-list-name">Fawry Yellow Card</div>
              <div class="fw-list-date">•• 4521 · Active</div>
            </div>
          </div>
        """)

        gr.HTML(C.section_title_html("Transaction history"))
        gr.HTML(C.recent_payments_html())
    return {"col": col, "add_money_btn": add_money_btn, "send_btn": send_btn}


EVENTS = [("click", "Click"), ("open", "Open"), ("purchase", "Buy"), ("redemption", "Redeem")]


def build_offers_page(user_name="Ahmed Mohamed", max_slots=10):
    with gr.Column(elem_classes="fw-page", visible=False) as col:
        gr.HTML(C.app_header_html(name=user_name, greeting="Offers for you"))
        gr.HTML(C.search_bar_html("Search offers..."))
        area_dd = gr.Dropdown(choices=["Auto"], value="Auto", label="Area (Auto = device location, then your profile)",
                              interactive=True)
        model_status = gr.HTML("")
        event_status = gr.Markdown("")
        refresh_btn = gr.Button("Refresh recommendations", elem_classes="fw-btn-outline", size="sm")
        slots = []
        for i in range(max_slots):
            with gr.Column(visible=False, elem_classes="fw-slot") as slot_col:
                slot_html = gr.HTML("")
                with gr.Row():
                    btns = {ev: gr.Button(label, size="sm",
                                          elem_classes="fw-btn-yellow" if ev == "purchase" else "fw-btn-outline")
                            for ev, label in EVENTS}
            slots.append({"col": slot_col, "html": slot_html, "buttons": btns})
        gr.HTML(C.section_title_html("Featured", see_all=False))
        gr.HTML(C.feature_grid_html())
    return {"col": col, "area_dd": area_dd, "model_status": model_status, "event_status": event_status,
            "refresh_btn": refresh_btn, "slots": slots}


def build_quickpay_page(user_name="Ahmed Mohamed"):
    with gr.Column(elem_classes="fw-page", visible=False) as col:
        gr.HTML(C.app_header_html(name=user_name, greeting="Quick pay"))
        gr.HTML(C.search_bar_html("Search a biller or service..."))
        gr.HTML(C.quick_pay_grid_html())
        gr.HTML(C.quick_pay_grid_html(items=[
            ("🚗", "Cars"), ("🎓", "Education"),
            ("🏥", "Health"), ("🎟️", "Tickets"),
        ]))
        gr.HTML(C.section_title_html("Saved billers", see_all=False))
        gr.HTML(C.recent_payments_html())
    return {"col": col}
