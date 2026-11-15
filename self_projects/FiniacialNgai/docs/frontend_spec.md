# Frontend Improvement Specification
## Written by: Claude (tech lead) | To be implemented by: Xiaomi MiMo

---

## What we're working with

- Streamlit app with glassmorphism design (blur cards, Apple SF Pro font)
- CSS is injected via st.markdown() in app.py
- Design tokens already defined: --blue #007aff, --green #34c759, --red #ff3b30, --purple #af52de
- Navigation: 10 pages in a sidebar radio
- Pages: Dashboard, Balance Sheet, P&L, Monitoring, Analysis, Projections, Backtesting, AI Chat, Risk Profile, Settings

---

## Improvement 1 — Sidebar redesign (app.py)

### Current problem
The sidebar is a plain radio button list with emoji labels. No visual grouping, no logo mark, no version info, and the active state is just a faint blue background — hard to read.

### What to build

**Logo area** (top of sidebar):
```
[ FN ]   FinancialNgai
         Personal AI Advisor
```
The `[FN]` is a 40×40px pill/square with a blue-to-purple gradient background, white bold text "FN" centered. Use inline HTML/CSS inside st.sidebar.

**Grouped navigation** — split 10 pages into 3 groups with small uppercase labels:

Group 1 — OVERVIEW
  📊  Dashboard
  🏦  Balance Sheet
  📈  P&L Statement

Group 2 — ANALYSIS
  🔍  Monitoring
  🔬  Analysis
  🚀  Projections
  🧪  Backtesting

Group 3 — TOOLS
  💬  AI Chat
  🛡️  Risk Profile
  ⚙️  Settings

The group labels are tiny (0.65rem), uppercase, letter-spaced, muted grey (#9ca3af), with 8px top padding and 4px bottom padding. Not clickable — just visual dividers.

**Active nav item** — add a left blue bar (3px wide, #007aff, border-radius 2px) on the active item in addition to the current blue background. Makes it very clear which page is active.

**Bottom of sidebar** — add after the nav:
- Thin divider line
- Two items side by side: language toggle (EN | 中文) on the left, version "v2.0" on the right, both in muted small text

### CSS changes needed

In the existing sidebar CSS block in app.py, add:
- Active item left-border accent via CSS `::before` pseudo-element or box-shadow inset
- The group label dividers via HTML injected between radio groups

---

## Improvement 2 — Global page header component (app.py or ui/components/)

### Current problem
Every page does its own title with raw st.markdown() and different HTML. No consistency — some have subtitles, some don't, some have export buttons in different places.

### What to build

Create a Python function `page_header(title, subtitle="", icon="")` in `ui/components/__init__.py` or a new `ui/components/header.py`.

The header renders this HTML:
```
[ icon ] Title                    [optional right slot]
         Subtitle in muted text
─────────────────────────────────────────────────────── (thin divider)
```

Styling:
- Icon: 36px pill background matching the page's accent colour, centered emoji, border-radius 10px
- Title: 1.75rem, font-weight 800, letter-spacing -0.025em, color #1d1d1f
- Subtitle: 0.875rem, color #6b7280, margin-top 2px
- Divider: 1px solid rgba(0,0,0,0.06), margin 16px 0 24px 0
- Animation: fadeInUp 0.4s ease both

---

## Improvement 3 — Dashboard hero card (ui/pages/dashboard.py)

### Current problem
Net worth is displayed as a plain st.metric(). It looks like a generic Streamlit widget with no visual weight.

### What to build

A full-width "hero card" at the top of the Dashboard page showing:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Total Net Worth                          Health Score               │
│  RM 6,892                                 74 / 100  •  Grade B      │
│  ↑ RM 1,200 vs last month                 ████████░░  Good           │
│                                                                       │
│  Assets: RM 32,421   Liabilities: RM 25,529   Savings Rate: 32%     │
└─────────────────────────────────────────────────────────────────────┘
```

Styling:
- Background: linear-gradient(135deg, #007aff 0%, #5856d6 100%)
- White text throughout
- border-radius: 28px
- padding: 32px 36px
- box-shadow: 0 20px 60px rgba(0,122,255,0.25)
- Net worth number: 3rem, font-weight 900
- Health score on the right side as a circular arc gauge (use a simple CSS circle or the existing health_score_gauge chart but smaller)
- Bottom row: 3 small stat chips (Assets, Liabilities, Savings Rate) in semi-transparent white pills

Get values from:
- snapshot["net_worth"]
- snapshot["total_assets"]
- snapshot["total_liabilities"]
- health.total_score and health.grade
- savings rate from PnL if available

---

## Improvement 4 — Metric card system (app.py global CSS)

### Current problem
st.metric() cards look generic. The existing CSS improves them slightly but they lack icons, colour accents, and visual hierarchy.

### What to build

Add to the global CSS in app.py — a richer metric card style:

```css
[data-testid="metric-container"] {
  /* existing glass effect — keep */
  /* ADD: */
  border-top: 3px solid var(--blue);   /* coloured top accent */
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
[data-testid="metric-container"]:hover {
  transform: translateY(-3px);
  box-shadow: 0 16px 48px rgba(0,0,0,0.1);
}
/* Metric value — larger */
[data-testid="metric-container"] [data-testid="stMetricValue"] {
  font-size: 1.8rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.03em !important;
}
/* Delta positive = green, negative = red */
[data-testid="metric-container"] [data-testid="stMetricDelta"] svg {
  display: none !important;  /* hide default arrow icon */
}
```

---

## Improvement 5 — Button styles (app.py global CSS)

### Current problem
Streamlit default buttons look flat and inconsistent.

### What to build

Primary buttons (the main action on each page) should have:
- Blue-to-purple gradient background
- Subtle shadow: 0 4px 16px rgba(0,122,255,0.3)
- Scale up slightly on hover: transform: scale(1.02)
- Border-radius: 14px
- Font-weight: 600

Secondary / outline buttons:
- Transparent background, blue border 1.5px
- Blue text
- Same border-radius

Add to global CSS in app.py:
```css
/* Primary button */
.stButton > button[kind="primary"],
.stButton > button:not([kind="secondary"]) {
  background: linear-gradient(135deg, #007aff, #5856d6) !important;
  color: white !important;
  border: none !important;
  border-radius: 14px !important;
  font-weight: 600 !important;
  box-shadow: 0 4px 16px rgba(0,122,255,.28) !important;
  transition: transform .18s ease, box-shadow .18s ease !important;
}
.stButton > button:hover {
  transform: scale(1.02) !important;
  box-shadow: 0 8px 28px rgba(0,122,255,.38) !important;
}
```

---

## Improvement 6 — Toast notification for saves (app.py or each page)

### Current problem
When the user saves the balance sheet or P&L, there's just a plain st.success() green banner. It flashes and looks out of place.

### What to build

A CSS-animated toast notification that slides in from the bottom right and fades out after 3 seconds. Inject via st.components.v1.html() when a save action succeeds.

The toast HTML:
```html
<div id="toast" style="
  position:fixed; bottom:32px; right:32px; z-index:9999;
  background: rgba(52,199,89,0.95);
  backdrop-filter: blur(16px);
  color: white; font-weight: 600; font-size: 0.9rem;
  padding: 14px 22px; border-radius: 16px;
  box-shadow: 0 8px 32px rgba(52,199,89,0.35);
  animation: slideInToast 0.3s ease, fadeOutToast 0.4s ease 2.8s forwards;
">✅ Saved successfully</div>
<style>
@keyframes slideInToast {
  from { transform: translateY(80px); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}
@keyframes fadeOutToast {
  from { opacity: 1; } to { opacity: 0; }
}
</style>
```

Create a helper function `show_toast(message, type="success")` in `ui/components/toast.py`.
Types: success (green), error (red), info (blue).

---

## Technical rules for MiMo

1. Read app.py in full before editing
2. Read ui/pages/dashboard.py in full before editing
3. Only edit CSS — do NOT touch routing logic, imports, or page render calls
4. For the hero card: edit ui/pages/dashboard.py only
5. For the header function: create ui/components/header.py — do NOT update all pages (just create the utility; pages can adopt it later)
6. For the toast: create ui/components/toast.py only
7. After every file edit, verify with .venv/bin/python3 -m py_compile <file>
8. Keep the existing cursor glow JS completely unchanged
9. The sidebar nav MUST still use st.radio() — do not replace it with buttons (that would break routing)
10. The grouped nav labels must be injected as static HTML ABOVE the st.radio() — render them with st.markdown() inside the st.sidebar context before the radio
