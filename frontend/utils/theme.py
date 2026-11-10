"""ChatGPT-style look for the recruiter dashboard (dark sidebar, rounded cards, quiet chrome)."""
import streamlit as st

CSS = """
<style>
#MainMenu, footer, header[data-testid="stHeader"] {visibility:hidden;height:0}
.block-container{padding-top:1.4rem;padding-bottom:2rem;max-width:1180px}
html, body, [class*="css"]{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
section[data-testid="stSidebar"]{background:#171717;border-right:1px solid #2a2a2a}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]{border-radius:10px;margin:2px 6px;padding:6px 10px}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]:hover{background:#2a2a2a}
section[data-testid="stSidebar"] a[aria-current="page"]{background:#303030}
h1,h2,h3{font-weight:600;letter-spacing:-.2px}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:16px;border-color:#303030;background:#262626}
.stButton>button,.stDownloadButton>button,.stLinkButton>a{border-radius:12px;border:1px solid #3a3a3a;background:#2a2a2a;color:#ececec}
.stButton>button:hover,.stLinkButton>a:hover{border-color:#10a37f;color:#fff}
.stButton>button[kind="primary"]{background:#10a37f;border-color:#10a37f;color:#fff}
div[data-baseweb="input"],div[data-baseweb="select"]>div,textarea{border-radius:12px!important}
button[data-baseweb="tab"]{border-radius:10px 10px 0 0}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;border:1px solid #3a3a3a;color:#bdbdbd}
.badge.on{border-color:#10a37f;color:#34d399}.badge.off{border-color:#ef4444;color:#f87171}
iframe{border-radius:18px}
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
