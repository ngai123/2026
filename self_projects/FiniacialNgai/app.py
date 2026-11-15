"""FinancialNgai — Personal AI Financial Advisor."""
import streamlit as st
import streamlit.components.v1 as components
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database.repository import init_db

st.set_page_config(
    page_title="FinancialNgai",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

st.markdown("""
<style>
/* ── Design tokens ─────────────────────────────────────────────── */
:root {
  --blue:   #007aff; --green: #34c759;
  --red:    #ff3b30; --orange: #ff9500; --purple: #af52de;
  --text:   #1d1d1f; --muted:  #6b7280;
}

/* ── Background ────────────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main .block-container {
  background:
    radial-gradient(ellipse 55% 45% at 12% 12%, rgba(0,122,255,.08) 0%, transparent 60%),
    radial-gradient(ellipse 45% 50% at 88% 85%, rgba(175,82,222,.06) 0%, transparent 55%),
    linear-gradient(160deg, #f0f4ff 0%, #ffffff 55%, #faf5ff 100%) !important;
  background-attachment: fixed !important;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", sans-serif !important;
  color: var(--text) !important;
}

/* ── Keyframes ─────────────────────────────────────────────────── */
@keyframes fadeInUp {
  from { opacity:0; transform:translateY(22px); }
  to   { opacity:1; transform:translateY(0); }
}
@keyframes fadeIn {
  from { opacity:0; } to { opacity:1; }
}
@keyframes shimmer {
  0%   { background-position:-200% center; }
  100% { background-position: 200% center; }
}
@keyframes pulseBlue {
  0%   { box-shadow: 0 0 0  0   rgba(0,122,255,.28); }
  70%  { box-shadow: 0 0 0  14px rgba(0,122,255,0);  }
  100% { box-shadow: 0 0 0  0   rgba(0,122,255,0);   }
}
@keyframes floatUp {
  0%,100% { transform:translateY(0); }
  50%      { transform:translateY(-5px); }
}

/* ── Glass utility ─────────────────────────────────────────────── */
.glass {
  background: rgba(255,255,255,.74) !important;
  backdrop-filter: blur(28px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(28px) saturate(180%) !important;
  border: 1px solid rgba(255,255,255,.62) !important;
  border-radius: 26px !important;
  box-shadow: 0 8px 40px rgba(0,0,0,.07), inset 0 1px 0 rgba(255,255,255,.9) !important;
}

/* ── Metric cards ──────────────────────────────────────────────── */
[data-testid="metric-container"] {
  background: rgba(255,255,255,.8) !important;
  backdrop-filter: blur(22px) saturate(160%) !important;
  -webkit-backdrop-filter: blur(22px) saturate(160%) !important;
  border: 1px solid rgba(255,255,255,.68) !important;
  border-radius: 22px !important;
  padding: 20px 22px !important;
  box-shadow: 0 4px 28px rgba(0,0,0,.055), inset 0 1px 0 rgba(255,255,255,.92) !important;
  transition: transform .22s ease, box-shadow .22s ease !important;
  animation: fadeInUp .45s ease both !important;
}
[data-testid="metric-container"]:hover {
  transform: translateY(-3px) !important;
  box-shadow: 0 14px 44px rgba(0,0,0,.1) !important;
}
[data-testid="stMetricValue"] {
  font-size: 1.75rem !important; font-weight: 700 !important;
  letter-spacing: -0.02em !important; color: #1d1d1f !important;
}
[data-testid="stMetricLabel"] {
  font-size: 0.76rem !important; font-weight: 600 !important;
  color: #6b7280 !important; text-transform: uppercase !important;
  letter-spacing: .07em !important;
}

/* ── Typography ────────────────────────────────────────────────── */
h1 {
  font-size: 2.5rem !important; font-weight: 800 !important;
  letter-spacing: -0.035em !important; color: #1d1d1f !important;
  animation: fadeInUp .4s ease both !important;
}
h2 {
  font-size: 1.75rem !important; font-weight: 700 !important;
  letter-spacing: -0.025em !important;
  animation: fadeInUp .4s .08s ease both !important;
}
h3 {
  font-size: 1.15rem !important; font-weight: 600 !important;
  animation: fadeInUp .4s .14s ease both !important;
}

/* ── Buttons ───────────────────────────────────────────────────── */
.stButton > button {
  border-radius: 12px !important; font-weight: 600 !important;
  transition: transform .15s ease, box-shadow .15s ease !important;
}
.stButton > button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 22px rgba(0,122,255,.22) !important;
}
div[data-testid="stBaseButton-primary"] > button {
  background: linear-gradient(135deg,#007aff,#005ecb) !important;
  color: white !important; border: none !important;
  box-shadow: 0 4px 18px rgba(0,122,255,.32) !important;
}

/* ── Expanders ─────────────────────────────────────────────────── */
details[data-testid="stExpander"] {
  background: rgba(255,255,255,.67) !important;
  backdrop-filter: blur(22px) !important;
  border: 1px solid rgba(255,255,255,.58) !important;
  border-radius: 20px !important;
  box-shadow: 0 4px 22px rgba(0,0,0,.045) !important;
  overflow: hidden !important; margin-bottom: 14px !important;
  animation: fadeInUp .45s ease both !important;
}
details[data-testid="stExpander"] summary {
  font-weight: 600 !important; color: #1d1d1f !important;
  padding: 14px 20px !important; border-radius: 20px !important;
}

/* ── Dividers ──────────────────────────────────────────────────── */
hr {
  border: none !important; height: 1px !important;
  background: linear-gradient(90deg, transparent, rgba(0,122,255,.14), transparent) !important;
  margin: 22px 0 !important;
}

/* ── Sidebar ───────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
  background: rgba(246,248,255,.9) !important;
  backdrop-filter: blur(24px) !important;
  border-right: 1px solid rgba(0,122,255,.1) !important;
  min-width: 220px !important; max-width: 220px !important;
}

/* ── Hide Streamlit chrome ─────────────────────────────────────── */
footer { visibility: hidden !important; }
header[data-testid="stHeader"] { visibility: hidden !important; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stSidebarNav"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { visibility: visible !important; }
</style>
""", unsafe_allow_html=True)

# ── Background glow that follows the cursor ─────────────────────────────
# components.html runs in its own iframe and uses window.parent.document to
# inject a large radial-gradient glow element into the real Streamlit page.
# The glow colour shifts from blue → violet based on horizontal cursor position.
components.html("""
<style>body{margin:0;overflow:hidden;}</style>
<script>
(function() {
  var p   = window.parent;
  var doc = p.document;

  /* ── Inject the glow div once ──────────────────────────────── */
  if (!doc.getElementById('fn-bg-glow')) {
    var g = doc.createElement('div');
    g.id = 'fn-bg-glow';
    g.style.cssText = [
      'position:fixed',
      'width:900px','height:900px',
      'border-radius:50%',
      'pointer-events:none',
      'z-index:0',
      'left:50%','top:50%',
      'transform:translate(-50%,-50%)',
      'will-change:left,top',
      'background:radial-gradient(circle,rgba(0,122,255,.11) 0%,rgba(175,82,222,.06) 45%,transparent 70%)',
    ].join(';');
    doc.body.appendChild(g);
  }

  if (p.__fnGlowActive) return;
  p.__fnGlowActive = true;

  var W  = p.innerWidth  || 1400;
  var H  = p.innerHeight || 900;
  var gx = W / 2, gy = H / 2;
  var tx = gx,    ty = gy;

  doc.addEventListener('mousemove', function(e) {
    tx = e.clientX;
    ty = e.clientY;

    /* Hue: 210 (blue) at left edge → 270 (violet) at right edge */
    var hue1 = Math.round(210 + (e.clientX / W) * 60);
    var hue2 = hue1 + 35;
    var g = doc.getElementById('fn-bg-glow');
    if (g) {
      g.style.background =
        'radial-gradient(circle,' +
        'hsla('+ hue1 +',88%,64%,.12) 0%,' +
        'hsla('+ hue2 +',78%,55%,.055) 42%,' +
        'transparent 70%)';
    }
  });

  /* Smooth lag — glow trails the cursor at 5 % per frame */
  (function anim() {
    gx += (tx - gx) * 0.05;
    gy += (ty - gy) * 0.05;
    var g = doc.getElementById('fn-bg-glow');
    if (g) {
      g.style.left      = gx + 'px';
      g.style.top       = gy + 'px';
      g.style.transform = 'translate(-50%,-50%)';
    }
    p.requestAnimationFrame(anim);
  })();

  /* Resize → keep centred when window resizes */
  p.addEventListener('resize', function() {
    W = p.innerWidth; H = p.innerHeight;
  });
})();
</script>
""", height=0)

if "language" not in st.session_state:
    st.session_state["language"] = "en"

# ── Sidebar navigation ──────────────────────────────────────────────────
with st.sidebar:
    # -- Precision Noir sidebar CSS --
    st.markdown("""
    <style>
    [data-testid="stSidebarContent"] {
        padding: 1.6rem 0.85rem 1rem !important;
        display: flex !important;
        flex-direction: column !important;
        position: relative !important;
        min-height: 100vh !important;
    }
    div[data-testid="stSidebar"] .stRadio > label { display: none !important; }
    div[data-testid="stSidebar"] .stRadio [role="radiogroup"] { gap: 3px !important; }
    div[data-testid="stSidebar"] .stRadio label {
        display: flex !important; align-items: center !important;
        padding: 9px 14px !important; border-radius: 12px !important;
        transition: background .14s ease, box-shadow .14s ease !important;
        margin: 0 !important; width: 100% !important;
        position: relative !important;
    }
    div[data-testid="stSidebar"] .stRadio label:hover {
        background: rgba(255,255,255,0.04) !important;
    }
    div[data-testid="stSidebar"] [data-baseweb="radio"] { display: none !important; }
    div[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {
        font-size: .875rem !important; font-weight: 500 !important;
        color: #9ca3af !important; line-height: 1 !important; margin: 0 !important;
        font-family: Outfit, sans-serif !important;
    }
    div[data-testid="stSidebar"] .stRadio label:has(input:checked) {
        background: rgba(232,184,75,0.08) !important;
        box-shadow: inset 3px 0 0 0 #e8b84b !important;
        border-radius: 0 12px 12px 0 !important;
        padding-left: 11px !important;
    }
    div[data-testid="stSidebar"] .stRadio label:has(input:checked)
        [data-testid="stMarkdownContainer"] p {
        color: #e8b84b !important; font-weight: 700 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # -- Precision Noir FN logo mark --
    st.markdown("""
    <div style='padding:24px 20px 20px;'>
      <div style='display:flex;align-items:center;gap:12px;'>
        <div style='width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#e8b84b,#c49a2a);display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 16px rgba(232,184,75,0.35);'>
          <span style='font-family:Fraunces,serif;font-style:italic;font-weight:700;font-size:1.1rem;color:#080c12;line-height:1;'>FN</span>
        </div>
        <div>
          <div style='font-family:Outfit,sans-serif;font-weight:700;font-size:0.95rem;color:#e8e6e1;letter-spacing:-0.01em;'>FinancialNgai</div>
          <div style='font-family:Outfit,sans-serif;font-weight:400;font-size:0.68rem;color:#6b7385;margin-top:1px;letter-spacing:0.02em;'>Personal AI Advisor</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # -- Group label: Overview --
    st.markdown("""
    <div style='padding-bottom:4px;'>
      <div style='padding:12px 20px 4px;font-family:Outfit,sans-serif;font-size:0.62rem;font-weight:600;letter-spacing:0.12em;color:#3d4356;text-transform:uppercase;'>Overview</div>
    </div>
    """, unsafe_allow_html=True)

    # -- Radio navigation --
    page = st.radio(
        "Navigate",
        [
            "📊  Dashboard",
            "🏦  Balance Sheet",
            "📈  P&L Statement",
            "🔍  Monitoring",
            "🔬  Analysis",
            "🚀  Projections",
            "🧪  Backtesting",
            "💬  AI Chat",
            "🛡️  Risk Profile",
            "⚙️  Settings",
        ],
        label_visibility="collapsed",
        key="nav_page",
    )

    # -- Precision Noir bottom bar --
    st.markdown("""
    <div style='position:absolute;bottom:0;left:0;right:0;padding:16px 20px;border-top:1px solid rgba(255,255,255,0.06);display:flex;align-items:center;justify-content:space-between;'>
      <span style='font-family:Outfit,sans-serif;font-size:0.7rem;color:#3d4356;'>v2.0</span>
      <span style='font-family:Outfit,sans-serif;font-size:0.7rem;color:#3d4356;'>FinancialNgai</span>
    </div>
    """, unsafe_allow_html=True)


# ── Page render ──────────────────────────────────────────────────────────
if page == "📊  Dashboard":
    from ui.pages import dashboard
    dashboard.render()

elif page == "🏦  Balance Sheet":
    from ui.pages import balance_sheet
    balance_sheet.render()

elif page == "📈  P&L Statement":
    from ui.pages import pnl
    pnl.render()

elif page == "🔍  Monitoring":
    from ui.pages import simulation
    simulation.render()

elif page == "🔬  Analysis":
    from ui.pages import history
    history.render()

elif page == "🚀  Projections":
    from ui.pages import projections
    projections.render()

elif page == "🧪  Backtesting":
    from ui.pages import backtesting
    backtesting.render()

elif page == "💬  AI Chat":
    from ui.pages import ai_chat
    ai_chat.render()

elif page == "🛡️  Risk Profile":
    from ui.pages import risk_profile
    risk_profile.render()

elif page == "⚙️  Settings":
    from ui.pages import settings
    settings.render()
