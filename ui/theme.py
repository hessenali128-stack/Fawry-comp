"""
theme.py
--------
Single source of truth for the Fawry-inspired look & feel.
Import COLORS / CUSTOM_CSS anywhere you build a Gradio Block so every
page shares the exact same theme.
"""

# ---------------------------------------------------------------------------
# Brand palette (sampled from the reference screenshot)
# ---------------------------------------------------------------------------
YELLOW = "#FFCC00"
YELLOW_DARK = "#F0BF00"
BLACK = "#171717"
SOFT_BLACK = "#232323"
BG = "#F4F4F5"
WHITE = "#FFFFFF"
MUTED = "#8A8A8E"
GREEN = "#1E7B4D"
RED = "#D9483B"
BLUE = "#3B6FE0"
RADIUS_LG = "20px"
RADIUS_MD = "14px"
RADIUS_SM = "10px"

CUSTOM_CSS = f"""
:root {{
    --fw-yellow: {YELLOW};
    --fw-yellow-dark: {YELLOW_DARK};
    --fw-black: {BLACK};
    --fw-soft-black: {SOFT_BLACK};
    --fw-bg: {BG};
    --fw-white: {WHITE};
    --fw-muted: {MUTED};
    --fw-green: {GREEN};
    --fw-red: {RED};
    --fw-blue: {BLUE};
    --fw-radius-lg: {RADIUS_LG};
    --fw-radius-md: {RADIUS_MD};
    --fw-radius-sm: {RADIUS_SM};
}}

/* ---------- App shell ---------- */
.gradio-container {{
    background: var(--fw-bg) !important;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}}
#fw-shell {{
    max-width: 1080px;
    width: 100%;
    margin: 0 auto;
    padding: 0 20px 100px 20px;
    box-sizing: border-box;
    position: relative;
}}
@media (min-width: 900px) {{
    #fw-shell {{ padding: 0 40px 110px 40px; }}
    .fw-header {{ padding: 20px 28px 28px 28px; margin: -16px -40px 18px -40px; border-radius: 0 0 28px 28px; }}
    .fw-balance-card {{ padding: 22px 28px; }}
    .fw-grid-2 {{ grid-template-columns: repeat(4, 1fr); }}
    .fw-grid-4 {{ max-width: 560px; }}
}}
.fw-page {{ padding: 4px 2px 12px 2px; }}

/* ---------- Header ---------- */
.fw-header {{
    background: var(--fw-yellow);
    border-radius: 0 0 var(--fw-radius-lg) var(--fw-radius-lg);
    padding: 14px 16px 20px 16px;
    margin: -16px -16px 14px -16px;
}}
.fw-header-top {{
    display: flex; justify-content: space-between; align-items: center;
    font-size: 12px; color: var(--fw-black); margin-bottom: 14px;
}}
.fw-logo-badge {{
    background: var(--fw-black); color: var(--fw-yellow);
    font-weight: 700; font-size: 12px; padding: 4px 10px;
    border-radius: 20px; letter-spacing: .5px;
}}
.fw-header-user {{ display: flex; align-items: center; gap: 10px; }}
.fw-avatar {{
    width: 38px; height: 38px; border-radius: 50%;
    background: var(--fw-white); display: flex; align-items: center;
    justify-content: center; font-size: 18px; flex-shrink: 0;
}}
.fw-greeting {{ font-size: 12px; color: var(--fw-soft-black); opacity: .75; }}
.fw-username {{ font-size: 15px; font-weight: 700; color: var(--fw-black); }}
.fw-header-icons {{ margin-left: auto; font-size: 16px; color: var(--fw-black); }}

/* ---------- Balance card ---------- */
.fw-balance-card {{
    background: var(--fw-black);
    color: var(--fw-white);
    border-radius: var(--fw-radius-lg);
    padding: 16px 18px;
    margin: -30px 2px 16px 2px;
    display: flex; justify-content: space-between; align-items: center;
}}
.fw-balance-label {{ font-size: 12px; color: #C9C9C9; }}
.fw-balance-amount {{ font-size: 22px; font-weight: 700; margin: 2px 0 6px 0; }}
.fw-balance-sub {{ font-size: 11px; color: #9A9A9A; }}

/* ---------- Generic section ---------- */
.fw-section-title {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin: 18px 4px 10px 4px;
}}
.fw-section-title h3 {{ font-size: 15px; font-weight: 700; color: var(--fw-black); margin: 0; }}
.fw-section-title span {{ font-size: 12px; color: var(--fw-blue); font-weight: 600; }}

/* ---------- Search bar ---------- */
.fw-search {{
    background: var(--fw-white); border-radius: 24px;
    padding: 10px 16px; display: flex; align-items: center; gap: 8px;
    color: var(--fw-muted); font-size: 13px; margin: 0 2px 14px 2px;
    box-shadow: 0 1px 2px rgba(0,0,0,.05);
}}

/* ---------- For you (offers) strip ---------- */
.fw-foryou-row {{
    display: flex; gap: 10px; overflow-x: auto; margin: 0 2px 16px 2px;
    padding-bottom: 2px; scrollbar-width: thin;
}}
.fw-foryou-card {{
    background: var(--fw-white); border-radius: var(--fw-radius-md);
    padding: 12px 14px; display: flex; align-items: center; gap: 10px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04); flex: 0 0 auto; min-width: 220px;
}}

/* ---------- Promo / Yellow card banner ---------- */
.fw-promo-card {{
    background: var(--fw-yellow); border-radius: var(--fw-radius-lg);
    padding: 16px; margin: 0 2px 16px 2px; position: relative;
}}
.fw-promo-badge {{
    background: var(--fw-black); color: var(--fw-yellow); font-size: 10px;
    font-weight: 700; padding: 3px 9px; border-radius: 12px; display: inline-block;
    margin-bottom: 8px;
}}
.fw-promo-title {{ font-weight: 700; font-size: 14px; color: var(--fw-black); margin-bottom: 4px; }}
.fw-promo-sub {{ font-size: 12px; color: var(--fw-soft-black); opacity: .8; max-width: 70%; }}

/* ---------- Quick pay grid ---------- */
.fw-grid-4 {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
    margin: 0 2px 6px 2px;
}}
.fw-quick-item {{
    background: var(--fw-white); border-radius: var(--fw-radius-md);
    padding: 12px 6px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
.fw-quick-icon {{ font-size: 20px; margin-bottom: 6px; }}
.fw-quick-label {{ font-size: 11px; color: var(--fw-soft-black); font-weight: 600; }}

/* ---------- 2-col feature cards ---------- */
.fw-grid-2 {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
    margin: 0 2px 6px 2px;
}}
.fw-feature-card {{
    background: var(--fw-white); border-radius: var(--fw-radius-md);
    padding: 14px; box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
.fw-feature-icon {{ font-size: 20px; margin-bottom: 8px; }}
.fw-feature-title {{ font-size: 13px; font-weight: 700; color: var(--fw-black); }}
.fw-feature-sub {{ font-size: 11px; color: var(--fw-muted); margin: 2px 0 10px 0; }}
.fw-tag {{
    background: var(--fw-yellow); color: var(--fw-black); font-size: 10px;
    font-weight: 700; padding: 3px 8px; border-radius: 10px; display: inline-block;
}}

/* ---------- Cashback banner ---------- */
.fw-cashback {{
    background: var(--fw-white); border-radius: var(--fw-radius-md);
    padding: 12px 14px; display: flex; align-items: center; gap: 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04); margin: 4px 2px 6px 2px;
}}
.fw-cashback-icon {{
    background: var(--fw-black); color: var(--fw-yellow); border-radius: 10px;
    width: 34px; height: 34px; display: flex; align-items: center;
    justify-content: center; font-size: 16px; flex-shrink: 0;
}}
.fw-cashback-title {{ font-size: 12.5px; font-weight: 700; color: var(--fw-black); }}
.fw-cashback-sub {{ font-size: 11px; color: var(--fw-muted); }}

/* ---------- Recent payments ---------- */
.fw-list-row {{
    background: var(--fw-white); display: flex; align-items: center;
    gap: 12px; padding: 12px 14px; margin: 0 2px 8px 2px;
    border-radius: var(--fw-radius-md); box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
.fw-list-icon {{
    width: 34px; height: 34px; border-radius: 50%; background: #F1F1F2;
    display: flex; align-items: center; justify-content: center; font-size: 15px;
}}
.fw-list-name {{ font-size: 13px; font-weight: 700; color: var(--fw-black); }}
.fw-list-date {{ font-size: 11px; color: var(--fw-muted); }}
.fw-list-amount {{ margin-left: auto; font-size: 13px; font-weight: 700; color: var(--fw-red); }}
.fw-list-amount.positive {{ color: var(--fw-green); }}

/* ---------- Bottom nav ---------- */
#fw-bottom-nav {{
    position: fixed; bottom: 0; left: 50%; transform: translateX(-50%);
    width: 100%; max-width: 1080px; background: var(--fw-white);
    border-top: 1px solid #ECECEC; padding: 8px 24px 12px 24px;
    box-sizing: border-box;
    display: flex; justify-content: space-around; z-index: 999;
}}
@media (min-width: 900px) {{
    #fw-bottom-nav {{ justify-content: center; gap: 48px; }}
}}
.fw-nav-btn button {{
    background: transparent !important; border: none !important;
    box-shadow: none !important; color: var(--fw-muted) !important;
    font-size: 11px !important; font-weight: 600 !important; min-width: 0 !important;
}}
.fw-nav-btn-active button {{ color: var(--fw-black) !important; }}

/* ---------- Buttons ---------- */
.fw-btn-primary button {{
    background: var(--fw-black) !important; color: var(--fw-yellow) !important;
    border-radius: 24px !important; font-weight: 700 !important; border: none !important;
}}
.fw-btn-outline button {{
    background: transparent !important; color: var(--fw-black) !important;
    border: 1.5px solid var(--fw-black) !important; border-radius: 24px !important;
    font-weight: 700 !important;
}}
.fw-btn-yellow button {{
    background: var(--fw-yellow) !important; color: var(--fw-black) !important;
    border-radius: 24px !important; font-weight: 700 !important; border: none !important;
}}

/* ---------- Auth pages ---------- */
.fw-auth-wrap {{ padding: 10px 4px 20px 4px; }}
.fw-auth-logo {{
    background: var(--fw-black); color: var(--fw-yellow); font-weight: 700;
    font-size: 14px; padding: 6px 14px; border-radius: 20px; display: inline-block;
    margin-bottom: 18px;
}}
.fw-auth-title {{ font-size: 22px; font-weight: 800; color: var(--fw-black); margin-bottom: 4px; }}
.fw-auth-sub {{ font-size: 13px; color: var(--fw-muted); margin-bottom: 18px; }}
.fw-auth-card input, .fw-auth-card textarea {{
    border-radius: var(--fw-radius-md) !important;
    background: var(--fw-white) !important;
}}
.fw-divider {{ text-align: center; color: var(--fw-muted); font-size: 12px; margin: 14px 0; }}
.fw-switch-link {{ text-align: center; font-size: 13px; color: var(--fw-soft-black); margin-top: 10px; }}
"""


EXTRA_CSS = """
.fw-status { font-size: 11px; color: var(--fw-muted); margin: 0 4px 10px 4px; }
.fw-rec { position: relative; }
.fw-rec-rank { position: absolute; top: 8px; right: 12px; font-size: 10px; font-weight: 700; color: var(--fw-muted); }
.fw-rec .fw-tag { margin-top: 6px; display: inline-block; }
.fw-slot { gap: 4px !important; margin-bottom: 8px; }
.fw-slot .fw-btn-outline, .fw-slot .fw-btn-yellow { min-width: 0 !important; padding: 4px 6px !important; font-size: 11px !important; }
"""
