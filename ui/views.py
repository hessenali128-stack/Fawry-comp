"""HTML renderers. Every clickable element carries data-act / data-v; theme.HEAD_JS forwards it to app.act()."""
from datetime import datetime, timedelta
from html import escape as e

P = {  # lucide-style icon paths
 "bolt": "M13 2 3 14h9l-1 8 10-12h-9z", "drop": "M12 2.7s7 7 7 12a7 7 0 0 1-14 0c0-5 7-12 7-12z",
 "wifi": "M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 20h.01", "phone": "M7 2h10v20H7zM11 18h2",
 "home": "M3 11 12 3l9 8v10h-6v-6H9v6H3z", "wallet": "M3 7h16a2 2 0 0 1 2 2v10H5a2 2 0 0 1-2-2zM3 7l2-3h12M16 14h2",
 "tag": "M3 12V3h9l9 9-9 9zM7.5 7.5h.01", "menu": "M4 6h16M4 12h16M4 18h16", "bell": "M6 9a6 6 0 0 1 12 0c0 6 3 7 3 8H3c0-1 3-2 3-8zM10 21h4",
 "qr": "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h3v3M21 14v7h-4", "search": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
 "pin": "M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11zM12 7.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
 "cal": "M4 5h16v15H4zM4 10h16M8 3v4M16 3v4", "up": "M3 17l6-6 4 4 8-8M15 7h6v6", "grid": "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
 "heart": "M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.5A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z", "arrow": "M5 12h14M13 6l6 6-6 6", "plus": "M12 5v14M5 12h14",
 "card": "M2 6h20v12H2zM2 10h20", "user": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0", "out": "M9 4H4v16h5M16 8l4 4-4 4M20 12H9",
 "gift": "M3 8h18v4H3zM5 12v9h14v-9M12 8v13M12 8S10 3 8 4s0 4 4 4 6-3 4-4-4 4-4 4",
 "car": "M5 16V11l2-5h10l2 5v5zM7 16v3M17 16v3", "edu": "M2 9l10-5 10 5-10 5zM6 11v5c3 3 9 3 12 0v-5", "med": "M9 3h6v6h6v6h-6v6H9v-6H3V9h6z", "tkt": "M3 8a2 2 0 0 0 0 8v3h18v-3a2 2 0 0 1 0-8V5H3z",
}


def ic(n): return f'<svg viewBox="0 0 24 24"><path d="{P[n]}"/></svg>'
def act(a, v=""): return f'data-act="{a}" data-v="{e(str(v))}"'
def money(x): return f"{x:,.2f}"
def initials(n): return "".join(w[0] for w in n.split()[:2]).upper() or "F"


def when(ts):
    d = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=3); n = datetime.utcnow() + timedelta(hours=3)
    if d.date() == n.date(): return "Today · " + d.strftime("%I:%M %p").lstrip("0")
    return "Yesterday" if d.date() == (n - timedelta(days=1)).date() else d.strftime("%d %b")


KIND = {"bill": "bolt", "topup": "plus", "recharge": "phone", "water": "drop", "internet": "wifi"}
BILLERS = [("bolt", "Electricity", "c1"), ("drop", "Water", "c2"), ("wifi", "Internet", "c3"), ("phone", "Top-up", "c4"),
           ("car", "Traffic fines", "c1"), ("edu", "Education", "c2"), ("med", "Health", "c3"), ("tkt", "Tickets", "c4")]
CAT_IC = {"Food & Beverages": "🍔", "Entertainment": "🎬", "Travel & Hotels": "✈️", "Electronics": "💻", "Fashion & Footwear": "👟"}


def header(u, st, title=None):
    hr = (datetime.utcnow() + timedelta(hours=3)).hour
    g = title or ("Good morning" if hr < 12 else "Good afternoon" if hr < 18 else "Good evening")
    loc = st.get("area") or u.get("gov") or "Egypt"
    last4 = (("".join(c for c in u["user_id"] if c.isdigit()) or "0").zfill(4))[-4:]
    return f"""<div class="hd"><div class="row sp"><span class="logo">fawry</span><span class="pill">{ic('pin')}{e(loc)}</span></div>
<div class="row" style="margin-top:14px"><div class="av">{e(initials(u['name']))}</div><div><div class="gr">{g}</div><div class="nm">{e(u['name'])}</div></div>
<div class="row" style="margin-left:auto"><a class="ib" {act('toast','No new notifications')}>{ic('bell')}</a><a class="ib dk" {act('toast','QR scanner needs camera access on your phone')}>{ic('qr')}</a></div></div>
<div class="bal"><div><div class="l">Total balance</div><div class="a">EGP {money(u['balance'])}</div><div class="s">myFawry wallet •• {last4}</div></div>
<div class="r"><a class="btn" {act('go','wallet')}>Top up</a><a {act('go','history')}>View statement</a></div></div></div>"""


def tx_list(rows):
    if not rows: return '<div class="list"><div class="empty">No payments yet.<br>Top up your wallet or pay a bill to get started.</div></div>'
    return '<div class="list">' + "".join(
        f'<div class="li"><div class="ic {"c3" if r["amount"] > 0 else "c1"}">{ic(KIND.get(r["kind"], "bolt"))}</div><div><b>{e(r["title"])}</b><small>{when(r["ts"])}</small></div>'
        f'<div class="am {"pos" if r["amount"] > 0 else ""}">{"+" if r["amount"] > 0 else "-"} EGP {money(abs(r["amount"]))}</div></div>' for r in rows) + "</div>"


def sec(t, a=None, v=""): return f'<div class="sec"><h3>{t}</h3>' + (f'<a {act("go", a)}>See all</a>' if a else "") + "</div>"


def offer_card(o, i, badge=""):
    from catalog import today
    price = f" · EGP {float(o['price']):,.0f}" if o.get("price") else ""
    cat = (o.get("category") or "").replace("_", " ").title().strip()
    ends = str(o.get("ends") or o.get("end") or "")[:10]
    expired = bool(ends) and ends < today()
    if o.get("dtype") == "PERCENTAGE" and float(o.get("dvalue") or 0): disc = f"{float(o['dvalue']):g}% off"
    elif float(o.get("cash") or 0): disc = f"EGP {float(o['cash']):,.0f} voucher"
    else: disc = ""
    badges = "".join(f'<span class="badge {c}">{e(t)}</span>' for t, c in ((badge, ""), (disc, ""), ("Expired" if expired else "", "x")) if t)
    where = o.get("gov") or ""
    where = "" if where.upper() == "NATIONWIDE" else f" · {where}"
    btn = '<a class="btn o" style="opacity:.5;pointer-events:none">Expired</a>' if expired else f'<a class="btn" {act("ev:purchase", o["offer_id"])}>Get offer</a>'
    return f"""<div class="of {'xp' if expired else ''}"><div class="bgs">{badges}</div><div class="row"><div class="ic c1">{CAT_IC.get(cat, '🎁')}</div>
<div><h4 dir="auto">{e((o.get('description') or o.get('partner') or o['offer_id'])[:110])}</h4><div class="meta" dir="auto">{e(o.get('partner') or '')} · {e(cat)}{price}{e(where)}</div></div></div>
<div class="meta">{'Ended' if expired else 'Valid until'} {e(ends)}</div>
<div class="acts"><a class="btn o" {act('ev:open', o['offer_id'])}>Details</a>{btn}</div></div>"""


def offers_block(st, limit=None):
    tab, items, err = st.get("tab", "rec"), [], st.get("oerr")
    if tab == "rec":
        items = [(r, {"explore": "Explore", "similar": "Similar to your last pick"}.get(r.get("source"), "Top pick")) for r in st.get("recs", [])]
    else:
        items = [(o, "") for o in st.get("all", {}).get("offers", [])]
    if limit: items = items[:limit]
    if err: return f'<div class="list"><div class="empty">⚠️ {e(err)}</div></div>'
    if not items: return '<div class="list"><div class="empty">No offers available right now.</div></div>'
    more = ""
    if tab == "all" and not limit and st["all"]["total"] > len(items):
        more = f'<a class="btn o f" {act("more")}>Show more ({st["all"]["total"] - len(items)} left)</a>'
    return '<div class="og">' + "".join(offer_card(o, i, b) for i, (o, b) in enumerate(items)) + "</div>" + more


def tabs(st): return f'<div class="seg"><a class="{"on" if st.get("tab", "rec") == "rec" else ""}" {act("tab", "rec")}>Recommended for you</a><a class="{"on" if st.get("tab") == "all" else ""}" {act("tab", "all")}>All offers</a></div>'


def home(u, st):
    card = (f'<div class="ycard"><div class="row sp"><span>myFawry</span>{ic("wifi")}</div><div class="chip"></div><div><div>•• {(u["user_id"][-4:])}</div><div>{e(u["name"].upper()[:14])}</div></div></div>')
    promo = f"""<div class="promo"><div><span class="tag">{'Active' if u['has_card'] else 'New'}</span><h2>{'Your Fawry Yellow Card' if u['has_card'] else 'Get your Fawry Yellow Card'}</h2>
<p>Free delivery. Pay, save and split everywhere in Egypt.</p>{'<a class="btn k" ' + act('go', 'wallet') + '>View card</a>' if u['has_card'] else '<div class="row"><a class="btn k" ' + act('card') + '>Request card — free</a><a class="btn l" ' + act('go', 'offers') + '>Add +</a></div>'}</div>{card}</div>"""
    q = "".join(f'<a class="card q" {act("pay", n)}><span class="ic {c}">{ic(i)}</span>{n}</a>' for i, n, c in BILLERS[:4])
    f = [("cal", "Taqseet", "Installments up to 24 months", "0% APR", "c1", ("toast", "Taqseet is coming soon to your account")),
         ("up", "Investments", "Gold & funds from EGP 100", "From EGP 100", "c3", ("toast", "Investments is coming soon to your account")),
         ("grid", "Services", "Bills, tickets, donations", "300+ services", "c2", ("go", "quickpay")),
         ("heart", "For you", "Picks based on your spend", "Personalized", "c4", ("tab", "rec"))]
    ft = "".join(f'<a class="card ft" {act(*a)}><span class="ic {c}">{ic(i)}</span><b>{t}</b><small>{s}</small><span class="chip2">{g}</span></a>' for i, t, s, g, c, a in f)
    return f"""{header(u, st)}<div class="bd"><div class="srch">{ic('search')}<input data-f="q" data-enter="search" placeholder="Pay bills, recharge, search offers..."><a class="btn k" {act('search')}>Scan</a></div>
{promo}<div class="cols"><div style="display:grid;gap:14px">{sec('Quick pay', 'quickpay')}<div class="g4">{q}</div>{sec('Do more with Fawry', 'quickpay')}<div class="g2 f4">{ft}</div>
<a class="card cb" {act('go', 'offers')}><span class="ic">{ic('gift')}</span><div><b>50% cashback on first Yellow Card top-up</b><br><small>Ends Sunday • Selected merchants</small></div><span class="ic" style="margin-left:auto">{ic('arrow')}</span></a></div>
<div style="display:grid;gap:14px">{sec('Recent payments')}{tx_list(st['tx'][:3])}</div></div>
{sec('Offers', 'offers')}{tabs(st)}{offers_block(st, 4)}</div>"""


def offers(u, st):
    al = st.get("all", {})
    chips = f'<a class="{"" if st.get("cat") else "on"}" {act("cat", "")}>All</a>' + "".join(
        f'<a class="{"on" if st.get("cat") == c["name"] else ""}" {act("cat", c["name"])}>{e(c["name"])} · {c["count"]}</a>' for c in al.get("categories", [])[:14])
    govs = "".join(f'<option value="{e(g)}" {"selected" if g == st.get("gov") else ""}>{e(g)}</option>' for g in st.get("govs", []))
    on = st.get("active_only")
    filt = f"""<div class="srch">{ic('search')}<input data-f="q" data-enter="search" value="{e(st.get('q', ''))}" placeholder="Search by word, brand, category or city...">
<a class="btn k" {act('search')}>Search</a></div>
<div class="row" style="flex-wrap:wrap"><select data-chg="gov"><option value="">All cities</option>{govs}</select>
<div class="seg" style="flex:1;min-width:190px"><a class="{'' if on else 'on'}" {act('active', '')}>All</a><a class="{'on' if on else ''}" {act('active', '1')}>Active now</a></div></div>
<div class="chips">{chips}</div>""" if st.get("tab") == "all" else ""
    note = (f'<div class="meta" style="font-size:12px;color:var(--m)">{al["total"]} offers · {al["active"]} active today ({al["as_of"]})' + (f' · "{e(st["q"])}"' if st.get("q") else "") + "</div>") if st.get("tab") == "all" and al else ""
    return f'{header(u, st, "Offers")}<div class="bd">{tabs(st)}{filt}{note}{offers_block(st)}</div>'


def wallet(u, st, history=False):
    card = (f'<div class="list"><div class="li"><div class="ic c1">{ic("card")}</div><div><b>Fawry Yellow Card</b><small>•• {u["user_id"][-4:]} · Active</small></div></div></div>'
            if u["has_card"] else f'<div class="list"><div class="empty">No card yet.<br><br><a class="btn k" {act("card")}>Request Yellow Card — free</a></div></div>')
    add = f"""<div class="card" style="cursor:default"><label class="lb" style="margin-top:0">Add money to wallet (EGP)</label><input class="fi" data-f="amount" data-enter="topup" inputmode="decimal" placeholder="e.g. 500">
<div class="chips" style="margin:10px 0">{''.join(f'<a {act("amt", a)}>+{a}</a>' for a in (100, 200, 500, 1000))}</div><a class="btn f" {act('topup')}>Top up</a></div>"""
    return f'{header(u, st, "My wallet")}<div class="bd"><div class="cols"><div style="display:grid;gap:14px">{sec("Add money")}{add}{sec("Linked cards")}{card}</div><div style="display:grid;gap:14px">{sec("Transaction history")}{tx_list(st["tx"] if history else st["tx"][:10])}</div></div></div>'


def quickpay(u, st):
    b = st.get("biller")
    tiles = "".join(f'<a class="card q" {act("pay", n)} style="{"border-color:#1d1d1b" if n == b else ""}"><span class="ic {c}">{ic(i)}</span>{n}</a>' for i, n, c in BILLERS)
    form = f"""<div class="card" style="cursor:default"><b>Pay {e(b)}</b><label class="lb">Account / meter / mobile number</label><input class="fi" data-f="acct" placeholder="Enter number">
<label class="lb">Amount (EGP)</label><input class="fi" data-f="amount" data-enter="dopay" inputmode="decimal" placeholder="0.00"><br><a class="btn f" {act('dopay')}>Pay now</a></div>""" if b else '<div class="empty">Choose a biller to pay.</div>'
    return f'{header(u, st, "Quick pay")}<div class="bd">{sec("Billers")}<div class="g4">{tiles}</div>{form}{sec("Recent payments")}{tx_list(st["tx"][:5])}</div>'


def more(u, st):
    row = lambda i, t, a, v="": f'<a class="li" {act(a, v)}><div class="ic c1">{ic(i)}</div><b>{t}</b></a>'
    info = f'<div class="list"><div class="li"><div class="ic c4">{ic("user")}</div><div><b>{e(u["name"])}</b><small>Customer ID: {e(u["user_id"])}</small></div></div></div>'
    return f'{header(u, st, "More")}<div class="bd">{info}<div class="list">{row("card", "My Yellow Card", "go", "wallet")}{row("tag", "Offers", "go", "offers")}{row("out", "Log out", "logout")}</div></div>'


def auth(st):
    su = st.get("page") == "signup"
    if su:
        body = ('<label class="lb">Full name</label><input class="fi" data-f="name" placeholder="Ahmed Mohamed"><label class="lb">Mobile number</label><input class="fi" data-f="phone" placeholder="01xxxxxxxxx">'
                '<label class="lb">Email</label><input class="fi" data-f="email" placeholder="you@example.com"><label class="lb">Password</label><input class="fi" type="password" data-f="pw" data-enter="signup" placeholder="At least 6 characters">'
                f'<br><a class="btn k f" {act("signup")}>Create account</a><p style="text-align:center;margin:14px 0 0">Already registered? <a style="font-weight:700;cursor:pointer" {act("page", "login")}>Log in</a></p>')
    else:
        body = ('<label class="lb">Customer ID, mobile or email</label><input class="fi" data-f="id" placeholder="CUST_2497 / 01xxxxxxxxx">'
                f'<label class="lb">Password</label><input class="fi" type="password" data-f="pw" data-enter="login" placeholder="••••••••"><br><a class="btn k f" {act("login")}>Log in</a>'
                f'<p style="text-align:center;margin:14px 0 0">New to Fawry? <a style="font-weight:700;cursor:pointer" {act("page", "signup")}>Create an account</a></p>'
                '<div class="hint">Existing demo customers: use an ID like <b>CUST_2497</b> with the demo password.</div>')
    return f'<div class="auth"><span class="logo">fawry</span><h1>{"Create account" if su else "Welcome back"}</h1><p>{"Sign up in a minute and start paying smarter." if su else "Log in to your Fawry account to continue."}</p>{body}</div>'


NAV = [("home", "home", "Home"), ("wallet", "wallet", "Wallet"), ("offers", "tag", "Offers"), ("quickpay", "bolt", "Quick pay"), ("more", "menu", "More")]


def render(st):
    toast = f'<div class="toast {"err" if st.get("err") else ""}" data-n="{st.get("n", 0)}">{e(st["msg"])}</div>' if st.get("msg") else ""
    u = st.get("user")
    if not u: return f'<div class="fw">{toast}{auth(st)}</div>'
    pg = st.get("page", "home")
    body = {"home": home, "wallet": wallet, "offers": offers, "quickpay": quickpay, "more": more}.get(pg, lambda u, s: wallet(u, s, True))(u, st)
    nav = "".join(f'<a class="{"on" if k == pg or (pg == "history" and k == "wallet") else ""}" {act("go", k)}>{ic(i)}{l}</a>' for k, i, l in NAV)
    return f'<div class="fw">{toast}{body}<div class="nav">{nav}</div></div>'