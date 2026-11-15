"""AI Industry Monitoring — minimalist five-layer AI stack dashboard."""
import datetime
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from ui.export import export_button


# ── HTML helper ────────────────────────────────────────────────────────────────

def _clean(html: str) -> str:
    """Strip HTML comments and blank lines to prevent CommonMark truncation."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    return "\n".join(ln for ln in html.splitlines() if ln.strip())

def _md(html: str) -> None:
    st.markdown(_clean(html), unsafe_allow_html=True)


# ── Layer definitions ──────────────────────────────────────────────────────────

AI_LAYERS = [
    {
        "name": "Energy",
        "subtitle": "Power & data-centre infrastructure",
        "stocks": ["XOM", "CVX", "SLB"],
        "etf": "XLE",
        "description": "Energy providers and data-centre power that fuel AI chip fabs and large-scale model training.",
        "width_pct": 100,
    },
    {
        "name": "Chips",
        "subtitle": "Semiconductors & accelerators",
        "stocks": ["NVDA", "ASML", "TSM"],
        "etf": "SOXX",
        "description": "Semiconductor and accelerator companies providing the compute core of every AI system.",
        "width_pct": 92,
    },
    {
        "name": "Infrastructure",
        "subtitle": "Cloud & data-centre operations",
        "stocks": ["AMZN", "MSFT", "GOOGL"],
        "etf": "SKYY",
        "description": "Cloud providers and networking operators delivering the scale layer for AI workloads.",
        "width_pct": 84,
    },
    {
        "name": "Models",
        "subtitle": "Foundation models & AI services",
        "stocks": ["META", "NVDA", "AMD"],
        "etf": "ARKQ",
        "description": "Foundation models, inference platforms, and AI services that turn compute into capability.",
        "width_pct": 76,
    },
    {
        "name": "Applications",
        "subtitle": "End-user AI software",
        "stocks": ["MSFT", "META", "CRM"],
        "etf": "XLK",
        "description": "User-facing AI applications and software that capture value at the end of the stack.",
        "width_pct": 68,
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fc(v) -> str:
    return "—" if v is None else f"${v:,.2f}"

def _fp(v) -> str:
    if v is None:
        return "—"
    return f"+{v:.0f}%" if v >= 0 else f"{v:.0f}%"

def _ret_color(v) -> str:
    if v is None:
        return "#6b7280"
    return "#34c759" if v >= 0 else "#ff3b30"


# ── Data fetching ──────────────────────────────────────────────────────────────

def _fetch_one(ticker: str) -> dict:
    try:
        obj  = yf.Ticker(ticker)
        info = obj.info
        hist = obj.history(period="1y")
    except Exception:
        return {}
    if hist.empty:
        return {}
    close  = hist["Close"].dropna()
    if close.empty:
        return {}
    latest = close.iloc[-1]
    tz     = close.index.tz
    ys     = pd.Timestamp(year=datetime.datetime.now().year, month=1, day=1, tz=tz)
    ytd_sl = close.loc[close.index >= ys]
    ytd    = (latest / ytd_sl.iloc[0] - 1) * 100 if not ytd_sl.empty else None
    return {
        "name":            info.get("longName", ticker),
        "ticker":          ticker,
        "price":           latest,
        "market_cap":      info.get("marketCap"),
        "industry":        info.get("industry", "Technology"),
        "52w_high":        info.get("fiftyTwoWeekHigh"),
        "52w_low":         info.get("fiftyTwoWeekLow"),
        "ytd_return":      ytd,
        "one_year_return": (latest / close.iloc[0] - 1) * 100,
        "price_history":   close,
    }

@st.cache_data(ttl=3600, show_spinner="Fetching market data…")
def _fetch_all(tickers: tuple) -> dict:
    return {t: _fetch_one(t) for t in tickers}


# ── Chart builders ─────────────────────────────────────────────────────────────

def _pyramid_chart(m: dict) -> go.Figure:
    """
    Trapezoid layer-cake pyramid.
    All layers share the same neutral fill; 1Y return is shown as a text label.
    Energy is the wide base, Applications the narrow apex.
    """
    fig = go.Figure()
    n   = len(AI_LAYERS)

    for i, layer in enumerate(AI_LAYERS):
        em   = m.get(layer["etf"], {})
        ret  = em.get("one_year_return")
        sr   = [m[t]["one_year_return"] for t in layer["stocks"]
                if m.get(t) and m[t].get("one_year_return") is not None]
        disp = ret if ret is not None else (sum(sr)/len(sr) if sr else None)

        gap   = 0.06
        y_bot = i + gap / 2
        y_top = i + 1 - gap / 2
        w_bot = layer["width_pct"] / 100.0
        w_top = (AI_LAYERS[i + 1]["width_pct"] / 100.0) if i + 1 < n \
                else (layer["width_pct"] - 8) / 100.0

        xs = [-w_bot/2, w_bot/2,  w_top/2, -w_top/2, -w_bot/2]
        ys = [ y_bot,   y_bot,    y_top,    y_top,     y_bot  ]

        # Neutral fill — slight blue tint, consistent across all layers
        fill = f"rgba(0,122,255,{0.05 + i * 0.025:.3f})"

        etf_ytd = _fp(em.get("ytd_return"))
        stocks  = "  ·  ".join(layer["stocks"])
        hover   = (
            f"<b>{layer['name']}</b><br>"
            f"ETF {layer['etf']}  ·  Price {_fc(em.get('price'))}<br>"
            f"1Y Return: <b>{_fp(disp)}</b>  ·  YTD: <b>{etf_ytd}</b><br>"
            f"Stocks: {stocks}<extra></extra>"
        )

        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            fill="toself",
            fillcolor=fill,
            line=dict(color="rgba(255,255,255,0.9)", width=2),
            mode="lines",
            name=layer["name"],
            hovertemplate=hover,
            showlegend=False,
        ))

        mid_y     = (y_bot + y_top) / 2
        ret_txt   = f"  {_fp(disp)}" if disp is not None else ""
        fig.add_annotation(
            x=0, y=mid_y,
            text=f"<b>{layer['name']}</b>{ret_txt}",
            showarrow=False,
            font=dict(size=13, color="#1d1d1f",
                      family="-apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif"),
            xanchor="center",
        )
        fig.add_annotation(
            x=w_bot / 2 + 0.025, y=mid_y,
            text=layer["etf"],
            showarrow=False,
            font=dict(size=11, color="#6b7280"),
            xanchor="left",
        )

    fig.add_annotation(
        x=0, y=n + 0.15,
        text="AI Value Chain",
        showarrow=False,
        font=dict(size=12, color="#6b7280"),
        xanchor="center",
    )
    fig.add_annotation(
        x=0, y=-0.28,
        text="Hover each layer for ETF & stock data",
        showarrow=False,
        font=dict(size=10, color="#9ca3af"),
        xanchor="center",
    )

    fig.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   range=[-0.60, 0.72]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   range=[-0.45, n + 0.35]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=480,
        margin=dict(l=8, r=8, t=8, b=8),
        hovermode="closest",
        hoverlabel=dict(
            bgcolor="rgba(29,29,31,0.9)",
            font=dict(color="white", size=12,
                      family="-apple-system, BlinkMacSystemFont, sans-serif"),
            bordercolor="rgba(255,255,255,0.15)",
        ),
    )
    return fig


def _perf_bars(m: dict) -> go.Figure:
    """Horizontal bar chart — 1Y ETF return, ranked."""
    rows = sorted(
        [{"layer": l, "m": m.get(l["etf"], {})} for l in AI_LAYERS],
        key=lambda x: x["m"].get("one_year_return") or -999,
        reverse=True,
    )
    labels = [f"{r['layer']['name']}  ({r['layer']['etf']})" for r in rows]
    vals   = [r["m"].get("one_year_return") or 0 for r in rows]
    colors = ["rgba(0,122,255,0.75)" if v >= 0 else "rgba(255,59,48,0.72)" for v in vals]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=vals,
        orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.5)", width=1)),
        text=[f"{'%+.0f' % v}%" for v in vals],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>1Y Return: %{x:+.0f}%<extra></extra>",
        width=0.5,
    ))
    fig.add_vline(x=0, line_color="rgba(0,0,0,0.15)", line_width=1)

    fig.update_layout(
        xaxis=dict(ticksuffix="%", tickformat=".0f", gridcolor="rgba(0,0,0,0.05)", zeroline=False),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=280,
        margin=dict(l=8, r=80, t=8, b=30),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif",
                  size=12, color="#374151"),
        showlegend=False,
        hoverlabel=dict(bgcolor="rgba(29,29,31,0.9)",
                        font=dict(color="white", size=12),
                        bordercolor="rgba(255,255,255,0.15)"),
    )
    return fig


def _trend_chart(
    etf_history: pd.Series,
    etf_label: str,
    stocks: list[dict],
    height: int = 480,
) -> go.Figure:
    """
    Multi-line % return chart — ETF + up to 3 stocks, all normalised to 0 % at
    the start of the 1-year window so different price scales are comparable.

    ETF:    blue,  2.5 px, solid
    Stocks: grays, 1.5 px, solid (progressively lighter)
    """
    STOCK_COLORS = ["#ff9500", "#34c759", "#af52de"]   # orange · green · purple

    def _norm(series: pd.Series) -> pd.Series:
        base = series.iloc[0]
        return (series / base - 1) * 100 if base else series * 0

    def _fmt(pct_series: pd.Series) -> list[str]:
        """Pre-format % values as integer strings so hover always shows integers."""
        return [f"{int(round(v)):+d}%" for v in pct_series.values]

    fig = go.Figure()

    # ── ETF line (main, blue) ────────────────────────────────────────────────
    etf_pct = _norm(etf_history)
    fig.add_trace(go.Scatter(
        x=etf_history.index,
        y=etf_pct.values,
        customdata=_fmt(etf_pct),
        mode="lines",
        name=etf_label,
        line=dict(color="#007aff", width=2.5),
        hovertemplate=f"<b>{etf_label}</b>  %{{x|%b %d, %Y}}<br>Return: %{{customdata}}<extra></extra>",
    ))

    # ── Stock lines ───────────────────────────────────────────────────────────
    for stock, color in zip(stocks[:3], STOCK_COLORS):
        ph = stock.get("price_history")
        if ph is None or ph.empty:
            continue
        pct    = _norm(ph)
        ticker = stock.get("ticker", "")
        fig.add_trace(go.Scatter(
            x=ph.index,
            y=pct.values,
            customdata=_fmt(pct),
            mode="lines",
            name=ticker,
            line=dict(color=color, width=1.5),
            hovertemplate=f"<b>{ticker}</b>  %{{x|%b %d, %Y}}<br>Return: %{{customdata}}<extra></extra>",
        ))

    # Zero reference line
    fig.add_hline(y=0, line_color="rgba(0,0,0,0.1)", line_width=1)

    fig.update_layout(
        margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False, zeroline=False,
            tickfont=dict(size=10, color="#9ca3af"),
            tickformat="%b %y",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10, color="#9ca3af"),
            ticksuffix="%",
            tickformat=".0f",
            hoverformat="+.0f",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.01,
            xanchor="left",   x=0,
            font=dict(size=11, color="#374151"),
            bgcolor="rgba(0,0,0,0)",
        ),
        hovermode="x unified",
        height=height,
        hoverlabel=dict(
            bgcolor="rgba(29,29,31,0.9)",
            font=dict(color="white", size=12),
            bordercolor="rgba(255,255,255,0.15)",
        ),
    )
    return fig


# ── Layer detail ───────────────────────────────────────────────────────────────

def _layer_detail(layer: dict, stocks: list[dict], etf_m: dict) -> None:
    """
    50 / 50 split:
      Left  — ETF price history chart only
      Right — all data: layer info, ETF metrics, stock rows

    The chart height is computed from the number of stocks so both sides
    are the same height regardless of content.
    """
    ret = etf_m.get("one_year_return")
    ytd = etf_m.get("ytd_return")
    pos = (ret or 0) >= 0
    rc  = "#34c759" if pos else "#ff3b30"

    # Estimate right-column height so the chart can match it:
    #   header block  ≈  90 px
    #   2 metric rows ≈ 180 px  (each row ~90 px)
    #   YTD line      ≈  36 px
    #   section label ≈  28 px
    #   3 stock rows  ≈  55 px × n_stocks
    n_stocks   = min(len(stocks), 3)
    chart_h    = 90 + 180 + 36 + 28 + n_stocks * 55 + 28  # +28 for legend row

    col_chart, col_data = st.columns(2, gap="large")

    # ── Left: chart only ──────────────────────────────────────────────────────
    with col_chart:
        st.markdown(
            f"<div style='font-size:.68rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
            f"letter-spacing:.14em;margin-bottom:6px;'>{layer['etf']} · 1-year price</div>",
            unsafe_allow_html=True,
        )
        ph = etf_m.get("price_history")
        if ph is not None and not ph.empty:
            fig = _trend_chart(
                etf_history=ph,
                etf_label=layer["etf"],
                stocks=stocks,
                height=chart_h,
            )
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.caption("Price history unavailable.")

    # ── Right: data only ─────────────────────────────────────────────────────
    with col_data:
        # Layer + ETF header
        _md(f"""
<div style="margin-bottom:20px;">
<div style="font-size:.68rem;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.14em;margin-bottom:6px;">{layer['subtitle']}</div>
<div style="font-size:1.25rem;font-weight:800;color:#1d1d1f;letter-spacing:-.02em;">{layer['name']}</div>
<div style="font-size:.85rem;color:#6b7280;margin-top:6px;line-height:1.6;">{layer['description']}</div>
</div>""")

        # 4 key ETF metrics
        m0, m1 = st.columns(2)
        m2, m3 = st.columns(2)
        m0.metric("Price",     _fc(etf_m.get("price")))
        m1.metric("1Y Return", _fp(ret))
        m2.metric("52W Low",   _fc(etf_m.get("52w_low")))
        m3.metric("52W High",  _fc(etf_m.get("52w_high")))

        # YTD in a small caption row
        st.markdown(
            f"<div style='font-size:.78rem;color:#6b7280;margin:6px 0 18px;'>"
            f"YTD &nbsp;<b style='color:{rc}'>{_fp(ytd)}</b></div>",
            unsafe_allow_html=True,
        )

        # Divider label
        st.markdown(
            "<div style='font-size:.68rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:.14em;margin-bottom:10px;'>Representative stocks</div>",
            unsafe_allow_html=True,
        )

        # Stock rows
        for s in stocks[:3]:
            r    = s.get("one_year_return") or 0
            sp   = r >= 0
            src  = "#34c759" if sp else "#ff3b30"
            _md(f"""
<div style="display:flex;align-items:center;justify-content:space-between;background:rgba(255,255,255,0.78);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid rgba(0,0,0,0.07);border-radius:14px;padding:11px 16px;margin-bottom:7px;box-shadow:0 2px 10px rgba(0,0,0,0.04);">
<div>
<div style="display:flex;align-items:baseline;gap:8px;">
<span style="font-size:.95rem;font-weight:800;color:#1d1d1f;">{s['ticker']}</span>
<span style="font-size:.73rem;color:#9ca3af;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:140px;">{s.get('name', s['ticker'])}</span>
</div>
<div style="font-size:.7rem;color:#9ca3af;margin-top:2px;">{s.get('industry','Technology')}</div>
</div>
<div style="text-align:right;">
<div style="font-size:.95rem;font-weight:700;color:#1d1d1f;">{_fc(s.get('price'))}</div>
<div style="font-size:.75rem;font-weight:700;color:{src};margin-top:3px;">{_fp(r)}</div>
</div>
</div>""")


# ── Metrics table ──────────────────────────────────────────────────────────────

def _metrics_table(m: dict) -> None:
    sorted_layers = sorted(
        AI_LAYERS,
        key=lambda l: m.get(l["etf"], {}).get("one_year_return") or -999,
        reverse=True,
    )
    rows = ""
    for rank, layer in enumerate(sorted_layers, 1):
        em  = m.get(layer["etf"], {})
        ret = em.get("one_year_return")
        ytd = em.get("ytd_return")
        rc  = "#34c759" if (ret or 0) >= 0 else "#ff3b30"
        rows += (
            f"<tr style='border-bottom:1px solid rgba(0,0,0,.05);'>"
            f"<td style='padding:13px 16px;'>"
            f"<span style='font-size:.7rem;color:#9ca3af;margin-right:12px;'>#{rank}</span>"
            f"<b style='color:#1d1d1f;'>{layer['name']}</b>"
            f"<span style='font-size:.72rem;color:#6b7280;margin-left:8px;'>{layer['etf']}</span>"
            f"</td>"
            f"<td style='padding:13px 16px;color:#374151;font-weight:600;'>{_fc(em.get('price'))}</td>"
            f"<td style='padding:13px 16px;'><span style='font-weight:700;color:{rc};'>{_fp(ret)}</span></td>"
            f"<td style='padding:13px 16px;color:#6b7280;'>{_fp(ytd)}</td>"
            f"<td style='padding:13px 16px;color:#9ca3af;'>{_fc(em.get('52w_low'))}</td>"
            f"<td style='padding:13px 16px;color:#9ca3af;'>{_fc(em.get('52w_high'))}</td>"
            f"</tr>"
        )
    th = "text-align:left;padding:10px 16px;font-size:.65rem;color:#9ca3af;text-transform:uppercase;letter-spacing:.12em;font-weight:600;"
    _md(f"""
<div style="background:rgba(255,255,255,0.78);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px);border:1px solid rgba(0,0,0,0.07);border-radius:20px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.05);">
<table style="width:100%;border-collapse:collapse;">
<thead><tr style="background:rgba(0,0,0,.02);"><th style="{th}">Layer</th><th style="{th}">Price</th><th style="{th}">1Y Return</th><th style="{th}">YTD</th><th style="{th}">52W Low</th><th style="{th}">52W High</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>""")


# ── Main render ────────────────────────────────────────────────────────────────

def render() -> None:
    # Fetch (cached 1 h)
    tickers = tuple(sorted(
        {t for l in AI_LAYERS for t in l["stocks"]} |
        {l["etf"] for l in AI_LAYERS}
    ))
    m = _fetch_all(tickers)

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        "<h1 style='margin-bottom:4px;'>AI Industry Monitoring</h1>"
        "<p style='color:#6b7280;font-size:.95rem;margin:0 0 28px;'>"
        "Five-layer AI value chain — energy to applications</p>",
        unsafe_allow_html=True,
    )

    # ── KPI strip ─────────────────────────────────────────────────────────────
    rets      = [m.get(l["etf"], {}).get("one_year_return") for l in AI_LAYERS]
    valid     = [r for r in rets if r is not None]
    avg_ret   = sum(valid) / len(valid) if valid else None
    pos_count = sum(1 for r in valid if r >= 0)
    best      = max(AI_LAYERS, key=lambda l: m.get(l["etf"], {}).get("one_year_return") or -999)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Pyramid Layers", "5")
    k2.metric("ETF Trackers",   "5",  help="XLE · SOXX · SKYY · ARKQ · XLK")
    k3.metric("Positive Layers", f"{pos_count} / 5")
    k4.metric("Avg 1Y Return",  _fp(avg_ret))

    st.divider()

    # ── Layer Cake + Performance Bars ─────────────────────────────────────────
    col_l, col_r = st.columns([0.52, 0.48], gap="large")

    with col_l:
        st.markdown(
            "<div style='font-size:.7rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:.14em;margin-bottom:4px;'>Layer cake — hover for details</div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(_pyramid_chart(m), use_container_width=True,
                        config={"displayModeBar": False})

    with col_r:
        st.markdown(
            "<div style='font-size:.7rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:.14em;margin-bottom:4px;margin-top:28px;'>1-year ETF return, ranked</div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(_perf_bars(m), use_container_width=True,
                        config={"displayModeBar": False})

        st.markdown(
            "<div style='font-size:.7rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:.14em;margin-bottom:4px;margin-top:12px;'>Best layer</div>",
            unsafe_allow_html=True,
        )
        best_ret = m.get(best["etf"], {}).get("one_year_return")
        _md(f"""
<div style="background:rgba(255,255,255,0.78);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(0,0,0,0.07);border-radius:18px;padding:18px 22px;box-shadow:0 4px 20px rgba(0,0,0,0.05);">
<div style="display:flex;align-items:center;justify-content:space-between;">
<div>
<div style="font-size:1.1rem;font-weight:800;color:#1d1d1f;">{best['name']}</div>
<div style="font-size:.78rem;color:#6b7280;margin-top:3px;">{best['subtitle']}</div>
</div>
<div style="text-align:right;">
<div style="font-size:.75rem;color:#9ca3af;">{best['etf']}</div>
<div style="font-size:1.1rem;font-weight:800;color:#34c759;margin-top:2px;">{_fp(best_ret)}</div>
</div>
</div>
</div>""")

    st.divider()

    # ── Metrics table ─────────────────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:.7rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
        "letter-spacing:.14em;margin-bottom:12px;'>Performance overview</div>",
        unsafe_allow_html=True,
    )
    _metrics_table(m)

    st.divider()

    # ── Drill-down ────────────────────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:.7rem;font-weight:700;color:#9ca3af;text-transform:uppercase;"
        "letter-spacing:.14em;margin-bottom:12px;'>Layer detail</div>",
        unsafe_allow_html=True,
    )
    sel       = st.selectbox("Layer", [l["name"] for l in AI_LAYERS], index=1,
                             label_visibility="collapsed")
    sel_layer = next(l for l in AI_LAYERS if l["name"] == sel)
    sel_stks  = [m[t] for t in sel_layer["stocks"] if m.get(t)]
    sel_etf   = m.get(sel_layer["etf"], {})
    _layer_detail(sel_layer, sel_stks, sel_etf)

    st.markdown(
        "<div style='color:#9ca3af;font-size:.72rem;margin-top:16px;'>"
        "Data via yfinance · Prices delayed · Not financial advice</div>",
        unsafe_allow_html=True,
    )

    # ── Export ────────────────────────────────────────────────────────────────
    export_button(
        data={
            "page": "ai_monitoring",
            "layers": [
                {
                    "name":        layer["name"],
                    "subtitle":    layer["subtitle"],
                    "etf":         layer["etf"],
                    "stocks":      layer["stocks"],
                    "etf_price":   m.get(layer["etf"], {}).get("price"),
                    "etf_1y_return": m.get(layer["etf"], {}).get("one_year_return"),
                    "etf_ytd":     m.get(layer["etf"], {}).get("ytd_return"),
                    "etf_52w_high":m.get(layer["etf"], {}).get("52w_high"),
                    "etf_52w_low": m.get(layer["etf"], {}).get("52w_low"),
                    "top_stocks": [
                        {
                            "ticker":         s.get("ticker"),
                            "name":           s.get("name"),
                            "price":          s.get("price"),
                            "one_year_return":s.get("one_year_return"),
                            "ytd_return":     s.get("ytd_return"),
                            "industry":       s.get("industry"),
                        }
                        for t in layer["stocks"]
                        if (s := m.get(t))
                    ],
                }
                for layer in AI_LAYERS
            ],
        },
        prefix="ai_monitoring",
    )
