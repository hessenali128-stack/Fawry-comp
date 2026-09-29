"""
components.py
--------------
Reusable building blocks shared by every page (Home, Wallet, Offers,
Quick Pay, Login, Sign up). Each function returns either a raw HTML
string (rendered with gr.HTML) or builds real Gradio widgets so the
same card/list/grid never has to be re-written per page.
"""

import gradio as gr


# ---------------------------------------------------------------------------
# HTML snippet builders
# ---------------------------------------------------------------------------
def app_header_html(name="Ahmed Mohamed", location="Cairo, Egypt", greeting="Good morning"):
    return f"""
    <div class="fw-header">
      <div class="fw-header-top">
        <span class="fw-logo-badge">fawry</span>
        <span>📍 {location}</span>
      </div>
      <div class="fw-header-user">
        <div class="fw-avatar">👤</div>
        <div>
          <div class="fw-greeting">{greeting}</div>
          <div class="fw-username">{name}</div>
        </div>
        <div class="fw-header-icons">🔔</div>
      </div>
    </div>
    """


def balance_card_html(balance="EGP 12,450.00", wallet_last4="4521"):
    return f"""
    <div class="fw-balance-card">
      <div>
        <div class="fw-balance-label">Total balance</div>
        <div class="fw-balance-amount">{balance}</div>
        <div class="fw-balance-sub">myFawry wallet •• {wallet_last4}</div>
      </div>
    </div>
    """


def search_bar_html(placeholder="Pay bills, recharge, donate..."):
    return f"""<div class="fw-search">🔍 {placeholder}</div>"""


def for_you_offers_html(items=None):
    """Personalized 'For you' offers strip — small cashback-style cards."""
    items = items or [
        ("🎁", "50% cashback", "On your first Yellow Card top-up"),
        ("⚡", "5% back on electricity", "This month · myFawry wallet"),
        ("🧾", "0% installments", "On Taqseet orders over EGP 500"),
    ]
    cards = "".join(
        f"""<div class="fw-foryou-card">
              <div class="fw-cashback-icon">{icon}</div>
              <div>
                <div class="fw-cashback-title">{title}</div>
                <div class="fw-cashback-sub">{sub}</div>
              </div>
            </div>""" for icon, title, sub in items
    )
    return f"""<div class="fw-foryou-row">{cards}</div>"""


def promo_card_html(badge="New", title="Get your Fawry Yellow Card",
                     sub="Free delivery. Pay, save and split everywhere in Egypt."):
    return f"""
    <div class="fw-promo-card">
      <div class="fw-promo-badge">{badge}</div>
      <div class="fw-promo-title">{title}</div>
      <div class="fw-promo-sub">{sub}</div>
    </div>
    """


def section_title_html(title, see_all=True):
    tail = "<span>See all</span>" if see_all else ""
    return f"""<div class="fw-section-title"><h3>{title}</h3>{tail}</div>"""


def quick_pay_grid_html(items=None):
    items = items or [
        ("⚡", "Electricity"), ("💧", "Water"),
        ("📶", "Internet"), ("📱", "Top-up"),
    ]
    cells = "".join(
        f"""<div class="fw-quick-item">
              <div class="fw-quick-icon">{icon}</div>
              <div class="fw-quick-label">{label}</div>
            </div>""" for icon, label in items
    )
    return f"""<div class="fw-grid-4">{cells}</div>"""


def feature_grid_html(items=None):
    items = items or [
        ("🧾", "Taqseet", "Installments up to 24 months", "0% APR"),
        ("📈", "Investments", "Gold & funds from EGP 100", "From EGP 100"),
        ("🎟️", "Services", "Bills, tickets, donations", "300+ services"),
        ("💜", "For you", "Picks based on your spend", "Personalized"),
    ]
    cells = "".join(
        f"""<div class="fw-feature-card">
              <div class="fw-feature-icon">{icon}</div>
              <div class="fw-feature-title">{title}</div>
              <div class="fw-feature-sub">{sub}</div>
              <span class="fw-tag">{tag}</span>
            </div>""" for icon, title, sub, tag in items
    )
    return f"""<div class="fw-grid-2">{cells}</div>"""


def cashback_banner_html(text="50% cashback on first Yellow Card top-up",
                          sub="Ends Sunday · Selected merchants"):
    return f"""
    <div class="fw-cashback">
      <div class="fw-cashback-icon">🎁</div>
      <div>
        <div class="fw-cashback-title">{text}</div>
        <div class="fw-cashback-sub">{sub}</div>
      </div>
    </div>
    """


def recent_payments_html(rows=None):
    rows = rows or [
        ("⚡", "North Cairo Electricity", "Today · 10:24 AM", "- EGP 342.00", False),
        ("📱", "Vodafone recharge", "Yesterday", "- EGP 100.00", False),
        ("💧", "Cairo Water Company", "12 Sep", "- EGP 86.50", False),
    ]
    items = "".join(
        f"""<div class="fw-list-row">
              <div class="fw-list-icon">{icon}</div>
              <div>
                <div class="fw-list-name">{name}</div>
                <div class="fw-list-date">{date}</div>
              </div>
              <div class="fw-list-amount {'positive' if positive else ''}">{amount}</div>
            </div>""" for icon, name, date, amount, positive in rows
    )
    return items


# ---------------------------------------------------------------------------
# Gradio widget builders (real, interactive components)
# ---------------------------------------------------------------------------
def bottom_nav(active="home", visible=True):
    """Returns (row, dict-of-buttons) so pages.py / app.py can wire clicks."""
    labels = [
        ("home", "🏠", "Home"),
        ("wallet", "👛", "Wallet"),
        ("offers", "🏷️", "Offers"),
        ("quickpay", "⚡", "Quick pay"),
        ("more", "☰", "More"),
    ]
    buttons = {}
    with gr.Row(elem_id="fw-bottom-nav", visible=visible) as row:
        for key, icon, label in labels:
            cls = "fw-nav-btn fw-nav-btn-active" if key == active else "fw-nav-btn"
            buttons[key] = gr.Button(f"{icon}\n{label}", elem_classes=cls, size="sm")
    return row, buttons


def page_header(name="Ahmed Mohamed", balance="EGP 12,450.00", show_search=True):
    """Header + balance card + optional search bar, used at the top of Home/Wallet/etc.
    Returns the header gr.HTML component too, so its name can be refreshed
    later (e.g. right after login/signup) with gr.update(value=...)."""
    header_html = gr.HTML(app_header_html(name=name))
    gr.HTML(balance_card_html(balance=balance))
    with gr.Row():
        top_up_btn = gr.Button("Top up", elem_classes="fw-btn-yellow", size="sm")
        statement_btn = gr.Button("View statement", elem_classes="fw-btn-outline", size="sm")
    if show_search:
        gr.HTML(search_bar_html())
    return header_html, top_up_btn, statement_btn


def auth_shell(title, subtitle):
    gr.HTML(f"""
    <div class="fw-auth-wrap">
      <div class="fw-auth-logo">fawry</div>
      <div class="fw-auth-title">{title}</div>
      <div class="fw-auth-sub">{subtitle}</div>
    </div>
    """)


# ---------------------------------------------------------------------------
# Live recommendations (rendered from POST /recommendations)
# ---------------------------------------------------------------------------
from html import escape as _esc  # noqa: E402

CATEGORY_ICONS = {
    "food_beverages": "🍔", "fashion_footwear": "👟", "electronics": "💻", "health_beauty": "💄",
    "travel_hotels": "✈️", "entertainment": "🎬", "groceries": "🛒", "household": "🏠", "gifts": "🎁",
    "online": "🌐", "services": "🧾", "transportation": "🚌", "books_stationery": "📚", "retail_services": "🏪",
}


def _rec_fields(rec):
    icon = CATEGORY_ICONS.get(rec.get("category", ""), "🎁")
    partner = rec.get("partner") or rec["offer_id"]
    title = rec.get("description") or partner
    title = title if len(title) <= 60 else title[:57] + "..."
    price = rec.get("price")
    sub = " · ".join(x for x in (partner, rec.get("category", "").replace("_", " ").title(),
                                 f"EGP {price:,.0f}" if price else "") if x)
    return icon, _esc(title), _esc(sub)


def rec_cards_html(recs, limit=6):
    """Home 'For you' strip, same markup as the original static cards."""
    cards = ""
    for rec in recs[:limit]:
        icon, title, sub = _rec_fields(rec)
        cards += f"""<div class="fw-foryou-card">
              <div class="fw-cashback-icon">{icon}</div>
              <div><div class="fw-cashback-title" dir="auto">{title}</div>
              <div class="fw-cashback-sub" dir="auto">{sub}</div></div></div>"""
    return f'<div class="fw-foryou-row">{cards}</div>'


def rec_card_html(rec):
    """One recommended offer on the Offers page (banner style + rank + source badge)."""
    icon, title, sub = _rec_fields(rec)
    badge = "Explore" if rec.get("source") == "explore" else "Top pick"
    return f"""<div class="fw-cashback fw-rec">
          <span class="fw-rec-rank">#{rec['rank']}</span>
          <div class="fw-cashback-icon">{icon}</div>
          <div><div class="fw-cashback-title" dir="auto">{title}</div>
          <div class="fw-cashback-sub" dir="auto">{sub}</div>
          <span class="fw-tag">{badge}</span></div></div>"""


def status_line(data=None, error=None):
    if error:
        return f'<div class="fw-status">⚠️ {_esc(error)}</div>'
    served = f" · served by {_esc(data['served_by'])}" if data.get("served_by") else ""
    cache = "cache hit" if data.get("cached") else "fresh"
    return (f'<div class="fw-status">Model {_esc(str(data["model_version"]))} · {cache} · '
            f'{data["latency_ms"]} ms{served}</div>')
