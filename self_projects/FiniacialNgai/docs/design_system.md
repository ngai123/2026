# FinancialNgai — Precision Noir Design System
## Aesthetic: Dark luxury financial terminal

---

## The Concept

"Precision Noir" — built for a young Malaysian investor who takes their money seriously.
Dark like a Bloomberg Terminal. Refined like a private bank's portal.
Every number feels important. Every interaction feels deliberate.

The one thing someone will remember: gold numbers on deep black.
Looks like nothing else in the Malaysian fintech space.

---

## Typography

Import from Google Fonts (via @import in CSS):
- **Fraunces** — display/headings (optical-size serif, editorial, distinctive)
- **JetBrains Mono** — all numbers and financial data (precise, technical)  
- **Outfit** — body text and UI labels (clean without being generic Inter)

```css
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,700;0,9..144,900;1,9..144,400&family=JetBrains+Mono:wght@400;600&family=Outfit:wght@300;400;500;600;700&display=swap');
```

Usage:
- Page titles, hero numbers: font-family: 'Fraunces', serif
- All RM amounts, percentages, stats: font-family: 'JetBrains Mono', monospace
- Navigation, labels, body: font-family: 'Outfit', sans-serif

---

## Color Palette

```css
:root {
  /* Backgrounds */
  --bg-base:    #080c12;   /* deep navy black — main background */
  --bg-surface: #0f1420;   /* slightly lighter — card backgrounds */
  --bg-raised:  #161c2d;   /* raised elements, hover states */
  --bg-overlay: rgba(255,255,255,0.04); /* glass overlay */

  /* Borders */
  --border:     rgba(255,255,255,0.08);
  --border-mid: rgba(255,255,255,0.12);
  --border-hi:  rgba(255,255,255,0.18);

  /* Text */
  --text:       #e8e6e1;   /* warm white — primary text */
  --text-muted: #6b7385;   /* muted grey */
  --text-dim:   #3d4356;   /* very muted, disabled */

  /* Accents */
  --gold:       #e8b84b;   /* primary accent — gold */
  --gold-dim:   rgba(232,184,75,0.15);
  --gold-glow:  rgba(232,184,75,0.25);
  --blue:       #3b7fff;   /* secondary accent — blue */
  --blue-dim:   rgba(59,127,255,0.12);

  /* Semantic */
  --green:      #22c55e;
  --green-dim:  rgba(34,197,94,0.12);
  --red:        #ef4444;
  --red-dim:    rgba(239,68,68,0.12);
  --purple:     #a78bfa;
}
```

---

## Component Specs

### Cards
```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 28px 32px;
  /* Subtle inner glow at top */
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.06),
    0 4px 24px rgba(0,0,0,0.4);
}
.card:hover {
  border-color: var(--border-mid);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.08),
    0 8px 40px rgba(0,0,0,0.5);
  transform: translateY(-2px);
  transition: all 0.2s ease;
}
```

### Net Worth Hero Card
Full-width card at top of Dashboard:
- Background: linear-gradient(135deg, #0f1420 0%, #111827 50%, #0f1a2e 100%)
- Gold top-border accent: border-top: 2px solid var(--gold)
- Net worth number: Fraunces, 4rem, color: var(--gold), font-weight 900
- "TOTAL NET WORTH" label: Outfit, 0.65rem, letter-spacing 0.12em, color: var(--text-muted), uppercase

### Sidebar
- Background: #060912 (darker than main bg)
- Logo mark: Gold square/pill with "FN" in Fraunces italic
- Nav items: Outfit 0.875rem, grouped with section labels
- Active item: Left gold 3px border + gold text + gold-dim background
- Bottom: version + language toggle

### Metric Numbers
All financial numbers use JetBrains Mono, tabular-nums, and are gold-colored:
```css
.rm-value {
  font-family: 'JetBrains Mono', monospace;
  font-variant-numeric: tabular-nums;
  color: var(--gold);
  font-weight: 600;
}
```

---

## Animations

Keep existing fadeInUp keyframe. Add:

```css
@keyframes goldPulse {
  0%, 100% { text-shadow: 0 0 20px rgba(232,184,75,0); }
  50%       { text-shadow: 0 0 20px rgba(232,184,75,0.4); }
}
@keyframes borderGlow {
  0%, 100% { border-color: rgba(232,184,75,0.3); }
  50%       { border-color: rgba(232,184,75,0.7); }
}
```

Net worth hero number gets goldPulse animation.

---

## What NOT to do

- No white or light grey backgrounds
- No blue-to-purple gradients on white
- No Inter, Roboto, or Arial
- No generic green "success" banners
- No rounded pill buttons in default Streamlit blue
