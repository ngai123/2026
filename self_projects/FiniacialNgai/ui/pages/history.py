"""History — asset trends, P&L trends, and Value Investing Decision System."""
from __future__ import annotations
from datetime import datetime
import hashlib
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from database import repository as repo
from ui.export import export_button


def _stable_color(name: str, palette: list) -> str:
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return palette[h % len(palette)]


_TRAILING = [" account", " accounts", " savings", " saving", " stocks", " stock", " crypto"]
_PNL_ALIASES: dict[str, str] = {"makan": "Eat"}


def _canon(name: str) -> str:
    s = name.lower().strip()
    changed = True
    while changed:
        changed = False
        for suf in _TRAILING:
            if s.endswith(suf):
                s = s[: -len(suf)].strip()
                changed = True
    return s


def _period_label(p: str) -> str:
    try:
        return datetime.strptime(p, "%Y-%m").strftime("%b %Y")
    except Exception:
        return p


# ── Balance Sheet charts ──────────────────────────────────────────────────────

def _asset_display_names(period_snaps: dict[str, dict]) -> list[str]:
    asset_data: dict[str, dict[str, float]] = {}
    display_name: dict[str, str] = {}
    for p in sorted(period_snaps):
        for a in repo.get_snapshot_assets(period_snaps[p]["id"]):
            if a["is_liability"]:
                continue
            key = _canon(a["name"])
            asset_data.setdefault(key, {})
            asset_data[key][p] = asset_data[key].get(p, 0.0) + float(a["balance"])
            display_name[key] = a["name"]
    avg = {k: sum(v.values()) / len(v) for k, v in asset_data.items()}
    return [display_name.get(k, k) for k in sorted(avg, key=lambda k: avg[k], reverse=True)]


def _pnl_item_names(pnl_rows: list[dict], item_type: str) -> list[str]:
    item_data: dict[str, float] = {}
    for row in pnl_rows:
        for item in row.get(f"{item_type}_items", []):
            raw = item.get("description") or item.get("category", "")
            if not raw:
                continue
            key = _PNL_ALIASES.get(raw.lower().strip(), raw.strip())
            item_data[key] = item_data.get(key, 0.0) + float(item.get("amount", 0))
    return [k for k in sorted(item_data, key=lambda k: item_data[k], reverse=True)]


def _asset_stacked_chart(period_snaps: dict[str, dict], selected: list[str] | None = None) -> go.Figure:
    periods = sorted(period_snaps)
    labels  = [_period_label(p) for p in periods]
    asset_data: dict[str, dict[str, float]] = {}
    display_name: dict[str, str] = {}
    for p in periods:
        snap = period_snaps[p]
        for a in repo.get_snapshot_assets(snap["id"]):
            if a["is_liability"]:
                continue
            name = a["name"]
            key = _canon(name)
            if key not in asset_data:
                asset_data[key] = {}
            asset_data[key][p] = asset_data[key].get(p, 0.0) + float(a["balance"])
            display_name[key] = name
    if not asset_data:
        return go.Figure()
    avg = {n: sum(v.values()) / len(v) for n, v in asset_data.items()}
    sorted_names = sorted(avg, key=lambda n: avg[n], reverse=True)
    if selected is not None:
        sorted_names = [k for k in sorted_names if display_name.get(k, k) in selected]
    palette = [
        "#007aff", "#34c759", "#ff9500", "#ff3b30", "#af52de",
        "#5ac8fa", "#ffcc00", "#ff2d55", "#4cd964", "#5856d6",
        "#e91e63", "#00bcd4", "#8bc34a", "#ff5722", "#9c27b0",
    ]
    fig = go.Figure()
    for key in sorted_names:
        label = display_name.get(key, key)
        y = [asset_data[key].get(p, 0.0) for p in periods]
        fig.add_trace(go.Scatter(
            name=label, x=labels, y=y, mode="lines+markers",
            line=dict(color=_stable_color(key, palette), width=2),
            marker=dict(size=7),
            hovertemplate=f"<b>{label}</b><br>%{{x}}: RM %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        title="Asset Breakdown by Month", xaxis_title="Month",
        yaxis_title="Balance (RM)", yaxis_tickprefix="RM ", yaxis_tickformat=",.0f",
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=480, legend=dict(orientation="v", x=1.02, y=1, xanchor="left"),
        margin=dict(l=60, r=200, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    )
    return fig


def _net_worth_chart(period_snaps: dict[str, dict]) -> go.Figure:
    periods = sorted(period_snaps)
    labels  = [_period_label(p) for p in periods]
    net     = [period_snaps[p].get("net_worth", 0) for p in periods]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        name="Net Worth", x=labels, y=net, mode="lines+markers",
        line=dict(color="#007aff", width=2), marker=dict(size=8),
        fill="tozeroy", fillcolor="rgba(0,122,255,0.08)",
        hovertemplate="Net Worth<br>%{x}: RM %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Net Worth by Month", xaxis_title="Month",
        yaxis_title="Net Worth (RM)", yaxis_tickprefix="RM ", yaxis_tickformat=",.0f",
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=280, showlegend=False, margin=dict(l=60, r=20, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    )
    return fig


def _liability_chart(period_snaps: dict[str, dict]) -> go.Figure:
    periods = sorted(period_snaps)
    labels  = [_period_label(p) for p in periods]
    liab_data: dict[str, dict[str, float]] = {}
    liab_display: dict[str, str] = {}
    for p in periods:
        snap = period_snaps[p]
        for a in repo.get_snapshot_assets(snap["id"]):
            if not a["is_liability"]:
                continue
            name = a["name"]
            key = _canon(name)
            if key not in liab_data:
                liab_data[key] = {}
            liab_data[key][p] = liab_data[key].get(p, 0.0) + float(a["balance"])
            liab_display[key] = name
    if not liab_data:
        return go.Figure()
    avg = {n: sum(v.values()) / len(v) for n, v in liab_data.items()}
    sorted_names = sorted(avg, key=lambda n: avg[n], reverse=True)
    palette = ["#ff3b30", "#ff9500", "#ff2d55", "#ff6b6b", "#e91e63"]
    fig = go.Figure()
    for key in sorted_names:
        label = liab_display.get(key, key)
        y = [liab_data[key].get(p, 0.0) for p in periods]
        fig.add_trace(go.Scatter(
            name=label, x=labels, y=y, mode="lines+markers",
            line=dict(color=_stable_color(key, palette), width=2), marker=dict(size=7),
            hovertemplate=f"<b>{label}</b><br>%{{x}}: RM %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        title="Liability Breakdown by Month", xaxis_title="Month",
        yaxis_title="Amount (RM)", yaxis_tickprefix="RM ", yaxis_tickformat=",.0f",
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=320, legend=dict(orientation="v", x=1.02, y=1, xanchor="left"),
        margin=dict(l=60, r=200, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    )
    return fig


def _pnl_bar_chart(pnl_rows: list[dict]) -> go.Figure:
    periods = [_period_label(p["period"]) for p in pnl_rows]
    income  = [p["total_income"]  for p in pnl_rows]
    expense = [p["total_expense"] for p in pnl_rows]
    profit  = [p["net_savings"]   for p in pnl_rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Income", x=periods, y=income, marker_color="#34c759",
                         hovertemplate="Income<br>%{x}: RM %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(name="Expenses", x=periods, y=expense, marker_color="#ff3b30",
                         hovertemplate="Expenses<br>%{x}: RM %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(name="Net Profit", x=periods, y=profit, mode="lines+markers",
                             line=dict(color="#007aff", width=2), marker=dict(size=8, color="#007aff"),
                             hovertemplate="Net Profit<br>%{x}: RM %{y:,.0f}<extra></extra>"))
    fig.update_layout(
        barmode="group", title="Income vs Expenses by Month", xaxis_title="Month",
        yaxis_title="Amount (RM)", yaxis_tickprefix="RM ", yaxis_tickformat=",.0f",
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=380, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    )
    return fig


def _pnl_detail_chart(pnl_rows: list[dict], item_type: str, selected: list[str] | None = None) -> go.Figure:
    item_data: dict[str, dict[str, float]] = {}
    periods = []
    for row in pnl_rows:
        p = row["period"]
        periods.append(p)
        for item in row.get(f"{item_type}_items", []):
            raw = item.get("description") or item.get("category", "")
            if not raw:
                continue
            key = _PNL_ALIASES.get(raw.lower().strip(), raw.strip())
            if key not in item_data:
                item_data[key] = {}
            item_data[key][p] = item_data[key].get(p, 0.0) + float(item.get("amount", 0))
    if not item_data:
        return go.Figure()
    labels = [_period_label(p) for p in periods]
    avg    = {n: sum(v.values()) / len(v) for n, v in item_data.items()}
    sorted_names = sorted(avg, key=lambda n: avg[n], reverse=True)
    if selected is not None:
        sorted_names = [n for n in sorted_names if n in selected]
    palette = [
        "#34c759", "#007aff", "#ff9500", "#af52de", "#5ac8fa",
        "#ff3b30", "#ffcc00", "#ff2d55", "#4cd964", "#5856d6",
        "#e91e63", "#00bcd4", "#8bc34a", "#ff5722", "#9c27b0",
    ]
    fig = go.Figure()
    for name in sorted_names:
        y = [item_data[name].get(p, 0.0) for p in periods]
        fig.add_trace(go.Scatter(
            name=name, x=labels, y=y, mode="lines+markers",
            line=dict(color=_stable_color(name, palette), width=2), marker=dict(size=7),
            hovertemplate=f"<b>{name}</b><br>%{{x}}: RM %{{y:,.0f}}<extra></extra>",
        ))
    title = "Income Breakdown by Month" if item_type == "income" else "Expense Breakdown by Month"
    fig.update_layout(
        title=title, xaxis_title="Month", yaxis_title="Amount (RM)",
        yaxis_tickprefix="RM ", yaxis_tickformat=",.0f",
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=400, legend=dict(orientation="v", x=1.02, y=1, xanchor="left"),
        margin=dict(l=60, r=200, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    )
    return fig


# ── CSS ───────────────────────────────────────────────────────────────────────

_FILTER_CSS = """
<style>
span[data-baseweb="tag"] {
    background-color: #c7c7cc !important;
    border: none !important;
    border-radius: 12px !important;
}
span[data-baseweb="tag"] span {
    color: #ffffff !important;
    font-size: 0.75rem !important;
    font-weight: 500 !important;
}
span[data-baseweb="tag"] span[role="presentation"] {
    color: #ffffff !important;
    opacity: 0.7 !important;
}
</style>
"""


# ── My Financials tab ─────────────────────────────────────────────────────────

def _render_my_charts() -> None:
    all_snapshots = sorted(
        [s for s in repo.list_snapshots() if s.get("period")],
        key=lambda x: x["period"]
    )
    period_snaps: dict[str, dict] = {}
    for s in all_snapshots:
        period_snaps[s["period"]] = s

    if period_snaps:
        st.subheader("Balance Sheet")
        st.plotly_chart(_net_worth_chart(period_snaps), use_container_width=True)
        all_asset_names = _asset_display_names(period_snaps)
        with st.expander("Filter assets", expanded=False):
            sel_assets = st.multiselect("Assets", options=all_asset_names, default=[],
                                        key="hist_asset_filter", label_visibility="collapsed")
        st.plotly_chart(_asset_stacked_chart(period_snaps, selected=sel_assets), use_container_width=True)
        if any(a["is_liability"] for snap in period_snaps.values()
               for a in repo.get_snapshot_assets(snap["id"])):
            st.plotly_chart(_liability_chart(period_snaps), use_container_width=True)
    else:
        st.info("No balance sheet records yet.")

    st.divider()

    pnl_rows = []
    for p in sorted(repo.list_pnl_periods()):
        data = repo.get_pnl_by_period(p)
        if data:
            pnl_rows.append(data)

    if pnl_rows:
        st.subheader("P&L Statement")
        st.plotly_chart(_pnl_bar_chart(pnl_rows), use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            all_inc = _pnl_item_names(pnl_rows, "income")
            with st.expander("Filter income", expanded=False):
                sel_inc = st.multiselect("Income", options=all_inc, default=[],
                                         key="hist_income_filter", label_visibility="collapsed")
            st.plotly_chart(_pnl_detail_chart(pnl_rows, "income", selected=sel_inc), use_container_width=True)
        with c2:
            all_exp = _pnl_item_names(pnl_rows, "expense")
            with st.expander("Filter expenses", expanded=False):
                sel_exp = st.multiselect("Expenses", options=all_exp, default=[],
                                         key="hist_expense_filter", label_visibility="collapsed")
            st.plotly_chart(_pnl_detail_chart(pnl_rows, "expense", selected=sel_exp), use_container_width=True)
    else:
        st.info("No P&L records yet.")


# ── Value Investing Decision System ───────────────────────────────────────────

# Asset classification map  →  (class_name, hex_color)
_ASSET_CLASS: dict[str, tuple[str, str]] = {
    "Liquid / Cash":              ("Cash",        "#ff9500"),
    "Savings & Fixed Deposits":   ("Defensive",   "#5ac8fa"),
    "Retirement (EPF/KWSP)":      ("Productive",  "#34c759"),
    "Unit Trusts & Mutual Funds": ("Productive",  "#34c759"),
    "Stocks & Equities":          ("Productive",  "#34c759"),
    "Gold & Precious Metals":     ("Defensive",   "#5ac8fa"),
    "Real Estate / Property":     ("Productive",  "#34c759"),
    "Bonds & Fixed Income":       ("Defensive",   "#5ac8fa"),
    "Education Savings":          ("Defensive",   "#5ac8fa"),
    "Insurance / Takaful":        ("Defensive",   "#5ac8fa"),
    "Cryptocurrency":             ("Speculative", "#ff3b30"),
    "Investments":                ("Productive",  "#34c759"),
    "Other Assets":               ("Cash",        "#ff9500"),
}


@st.cache_data(ttl=3600)
def _fetch_value_metrics(ticker: str) -> dict:
    import yfinance as yf
    try:
        t    = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="5y")
        ph   = hist["Close"].dropna() if not hist.empty else None
        return {
            "name":           info.get("longName", ticker),
            "price":          info.get("currentPrice") or info.get("regularMarketPrice"),
            "pe":             info.get("trailingPE"),
            "pb":             info.get("priceToBook"),
            "roe":            info.get("returnOnEquity"),
            "debt_equity":    info.get("debtToEquity"),
            "dividend_yield": info.get("dividendYield"),
            "eps":            info.get("trailingEps"),
            "eps_growth":     info.get("earningsGrowth"),
            "current_ratio":  info.get("currentRatio"),
            "net_margin":     info.get("profitMargins"),
            "market_cap":     info.get("marketCap"),
            "sector":         info.get("sector", ""),
            "industry":       info.get("industry", ""),
            "summary":        info.get("longBusinessSummary", ""),
            "price_history":  ph,
            "52w_high":       info.get("fiftyTwoWeekHigh"),
            "52w_low":        info.get("fiftyTwoWeekLow"),
        }
    except Exception:
        return {}


def _grade(value, low_good: bool, thresholds: tuple) -> tuple[str, str]:
    if value is None:
        return "N/A", "#86868b"
    great, ok = thresholds
    if low_good:
        if value <= great:  return "优秀", "#34c759"
        elif value <= ok:   return "尚可",    "#ff9500"
        else:               return "过高",  "#ff3b30"
    else:
        if value >= great:  return "优秀", "#34c759"
        elif value >= ok:   return "尚可",    "#ff9500"
        else:               return "过低",   "#ff3b30"


def _metric_card(label: str, value_str: str, grade_text: str, grade_color: str,
                 explanation: str, buffett_note: str = "") -> str:
    note = (
        f"<div style='font-size:0.72rem;color:#007aff;margin-top:8px;line-height:1.55;"
        f"border-left:2px solid #007aff;padding-left:8px;'>"
        f"<b>巴菲特说：</b> {buffett_note}</div>"
    ) if buffett_note else ""
    return (
        f"<div style='background:#f5f5f7;border-radius:14px;padding:16px 18px;margin-bottom:10px;'>"
        f"<div style='display:flex;justify-content:space-between;align-items:flex-start;'>"
        f"<div>"
        f"<div style='font-size:0.7rem;font-weight:600;color:#86868b;"
        f"text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;'>{label}</div>"
        f"<div style='font-size:1.5rem;font-weight:700;color:#1d1d1f;"
        f"letter-spacing:-0.03em;line-height:1;'>{value_str}</div>"
        f"</div>"
        f"<div style='background:{grade_color};color:white;border-radius:8px;"
        f"padding:3px 10px;font-size:0.72rem;font-weight:700;margin-top:2px;"
        f"white-space:nowrap;'>{grade_text}</div>"
        f"</div>"
        f"<div style='font-size:0.75rem;color:#3c3c43;margin-top:8px;line-height:1.55;'>{explanation}</div>"
        f"{note}"
        f"</div>"
    )


def _score_ring(score: int, total: int) -> str:
    pct   = score / total
    color = "#34c759" if pct >= 0.7 else "#ff9500" if pct >= 0.4 else "#ff3b30"
    label = "强大的价值股" if pct >= 0.7 else "观察并深入研究" if pct >= 0.4 else "避免买入"
    desc  = {
        "强大的价值股": "通过了巴菲特8项标准中的大部分。在买入前仍需做好自己的研究。",
        "观察并深入研究": "有一些优点，但也存在危险信号。在买入前需要更深入地挖掘。",
        "避免买入": "对于价值投资者来说太多的危险信号。去寻找更好的公司吧。",
    }[label]
    return (
        f"<div style='background:#f5f5f7;border-radius:18px;padding:24px;text-align:center;'>"
        f"<div style='font-size:3rem;font-weight:800;color:{color};"
        f"letter-spacing:-0.04em;line-height:1;'>{score}/{total}</div>"
        f"<div style='font-size:0.76rem;font-weight:600;color:#86868b;margin-top:4px;'>价值评分</div>"
        f"<div style='display:inline-block;background:{color};color:white;"
        f"border-radius:10px;padding:4px 16px;font-size:0.78rem;font-weight:700;"
        f"margin-top:10px;'>{label}</div>"
        f"<div style='font-size:0.71rem;color:#86868b;margin-top:10px;line-height:1.5;'>{desc}</div>"
        f"</div>"
    )


def _filter_box(number: str, title: str, subtitle: str) -> str:
    return (
        f"<div style='background:#f5f5f7;border-radius:14px;padding:16px 20px 4px;margin-bottom:6px;'>"
        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px;'>"
        f"<div style='background:#1d1d1f;color:white;border-radius:8px;"
        f"width:28px;height:28px;display:flex;align-items:center;justify-content:center;"
        f"font-weight:800;font-size:0.85rem;flex-shrink:0;'>{number}</div>"
        f"<div>"
        f"<div style='font-size:0.93rem;font-weight:700;color:#1d1d1f;'>{title}</div>"
        f"<div style='font-size:0.73rem;color:#86868b;line-height:1.4;'>{subtitle}</div>"
        f"</div></div>"
    )


def _verdict_bar(filters_passed: int) -> None:
    color = "#34c759" if filters_passed == 4 else "#ff9500" if filters_passed == 3 else "#ff3b30"
    texts = {
        4: "买入 — 4 个过滤器全部通过。这看起来像是以合理价格进行的优质投资。",
        3: "进一步研究 — 在投入真金白银之前，请修复该弱势过滤器的未通过项。",
        2: "观察 — 还没准备好买入。继续监控，直到更多过滤器通过。",
        1: "避免 — 太多未知因素。寻找更好的公司吧。",
        0: "坚决放弃 — 没有通过任何过滤器。这不是价值投资。",
    }
    st.markdown(
        f"<div style='background:{color};border-radius:16px;padding:20px 24px;text-align:center;margin-top:16px;'>"
        f"<div style='font-size:0.68rem;font-weight:700;color:rgba(255,255,255,0.7);"
        f"text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;'>最终裁决 — 已通过 {filters_passed}/4 个过滤器</div>"
        f"<div style='font-size:1.1rem;font-weight:800;color:white;line-height:1.4;'>{texts[filters_passed]}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_value_investing() -> None:
    import math

    # ═══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown(
        "<div style='background:linear-gradient(135deg,#1d1d1f 0%,#2c2c2e 100%);"
        "border-radius:18px;padding:28px 28px 22px;margin-bottom:28px;'>"
        "<div style='font-size:0.68rem;font-weight:700;color:#636366;"
        "text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;'>沃伦·巴菲特方法</div>"
        "<div style='font-size:1.9rem;font-weight:800;color:#ffffff;"
        "letter-spacing:-0.03em;line-height:1.2;margin-bottom:12px;'>"
        "价值投资<br>决策系统</div>"
        "<div style='font-size:0.82rem;color:#aeaeb2;line-height:1.7;margin-bottom:16px;'>"
        "一个完整的框架，用于评估你的投资组合、决定买什么，"
        "以及找到优质企业——就像沃伦·巴菲特60年来一直做的那样。</div>"
        "<div style='display:flex;gap:8px;flex-wrap:wrap;'>"
        "<span style='background:rgba(255,255,255,0.08);border-radius:8px;padding:4px 12px;"
        "font-size:0.72rem;color:#aeaeb2;'>第1步 · 投资组合成绩单</span>"
        "<span style='color:#636366;font-size:0.72rem;line-height:2;'>→</span>"
        "<span style='background:rgba(255,255,255,0.08);border-radius:8px;padding:4px 12px;"
        "font-size:0.72rem;color:#aeaeb2;'>第2步 · 决策清单</span>"
        "<span style='color:#636366;font-size:0.72rem;line-height:2;'>→</span>"
        "<span style='background:rgba(255,255,255,0.08);border-radius:8px;padding:4px 12px;"
        "font-size:0.72rem;color:#aeaeb2;'>第3步 · 寻找优质股票</span>"
        "<span style='color:#636366;font-size:0.72rem;line-height:2;'>→</span>"
        "<span style='background:rgba(255,255,255,0.08);border-radius:8px;padding:4px 12px;"
        "font-size:0.72rem;color:#aeaeb2;'>第4步 · 计算合理价格</span>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 1 — PORTFOLIO REPORT CARD
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown(
        "<div style='font-size:1.1rem;font-weight:800;color:#1d1d1f;"
        "letter-spacing:-0.02em;margin-bottom:4px;'>第1步  —  您的投资组合成绩单</div>"
        "<div style='font-size:0.78rem;color:#86868b;margin-bottom:16px;'>"
        "在寻找新投资之前，先了解您已经拥有的资产，"
        "以及它们是否符合价值投资的原则。数据提取自您最新的资产负债表。</div>",
        unsafe_allow_html=True,
    )

    all_snaps = sorted(
        [s for s in repo.list_snapshots() if s.get("period")],
        key=lambda x: x["period"],
    )

    if not all_snaps:
        st.info("尚未保存资产负债表。请前往“资产”页面，填写您的资产，然后点击保存。")
    else:
        snap       = all_snaps[-1]
        all_assets = repo.get_snapshot_assets(snap["id"])
        assets     = [a for a in all_assets if not a["is_liability"]]
        liabilities = [a for a in all_assets if a["is_liability"]]
        total_assets      = sum(float(a["balance"]) for a in assets) or 1.0
        total_liabilities = sum(float(a["balance"]) for a in liabilities)
        net_worth         = total_assets - total_liabilities

        # Classify every asset
        class_totals: dict[str, float] = {"Productive": 0.0, "Defensive": 0.0, "Cash": 0.0, "Speculative": 0.0}
        asset_rows: list[dict] = []
        for a in assets:
            cat        = a.get("category", "Other Assets")
            cls, color = _ASSET_CLASS.get(cat, ("Cash", "#ff9500"))
            bal        = float(a["balance"])
            class_totals[cls] = class_totals.get(cls, 0.0) + bal
            asset_rows.append({"name": a["name"], "balance": bal, "class": cls, "color": color})

        prod_pct  = class_totals["Productive"] / total_assets * 100
        spec_pct  = class_totals["Speculative"] / total_assets * 100
        cash_pct  = class_totals["Cash"] / total_assets * 100
        debt_ratio = total_liabilities / total_assets * 100

        # Grade
        if prod_pct >= 55 and spec_pct <= 10 and debt_ratio <= 30:
            grade, gc, gm = "A", "#34c759", "符合价值投资者"
        elif prod_pct >= 40 and spec_pct <= 20 and debt_ratio <= 50:
            grade, gc, gm = "B", "#007aff", "方向正确"
        elif prod_pct >= 25 or spec_pct <= 30:
            grade, gc, gm = "C", "#ff9500", "需要重新平衡"
        else:
            grade, gc, gm = "D", "#ff3b30", "高风险 — 建议紧急审查"

        # Pre-compute indicator colors to avoid nested f-strings
        prod_dot  = "#34c759" if prod_pct >= 50 else "#ff9500"
        spec_dot  = "#34c759" if spec_pct <= 10 else ("#ff9500" if spec_pct <= 20 else "#ff3b30")
        cash_dot  = "#34c759" if cash_pct <= 20 else "#ff9500"
        debt_dot  = "#34c759" if debt_ratio <= 30 else ("#ff9500" if debt_ratio <= 50 else "#ff3b30")

        g_col, p_col = st.columns([1, 2])

        with g_col:
            st.markdown(
                f"<div style='background:#f5f5f7;border-radius:18px;padding:22px;'>"
                f"<div style='font-size:0.68rem;font-weight:600;color:#86868b;"
                f"text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;'>投资组合成绩</div>"
                f"<div style='font-size:4rem;font-weight:900;color:{gc};"
                f"letter-spacing:-0.04em;line-height:1;'>{grade}</div>"
                f"<div style='display:inline-block;background:{gc};color:white;"
                f"border-radius:8px;padding:3px 14px;font-size:0.74rem;font-weight:700;"
                f"margin-top:10px;'>{gm}</div>"
                f"<div style='margin-top:16px;'>"
                f"<div style='font-size:0.73rem;color:#3c3c43;margin-bottom:7px;'>"
                f"<span style='color:{prod_dot};font-weight:700;'>●</span>"
                f" 生产性资产: <b>{prod_pct:.0f}%</b>  <span style='color:#86868b;'>(目标 ≥50%)</span></div>"
                f"<div style='font-size:0.73rem;color:#3c3c43;margin-bottom:7px;'>"
                f"<span style='color:{spec_dot};font-weight:700;'>●</span>"
                f" 投机性资产: <b>{spec_pct:.0f}%</b>  <span style='color:#86868b;'>(目标 ≤10%)</span></div>"
                f"<div style='font-size:0.73rem;color:#3c3c43;margin-bottom:7px;'>"
                f"<span style='color:{cash_dot};font-weight:700;'>●</span>"
                f" 现金/流动资金: <b>{cash_pct:.0f}%</b>  <span style='color:#86868b;'>(目标 ≤20%)</span></div>"
                f"<div style='font-size:0.73rem;color:#3c3c43;'>"
                f"<span style='color:{debt_dot};font-weight:700;'>●</span>"
                f" 债务/资产比: <b>{debt_ratio:.0f}%</b>  <span style='color:#86868b;'>(目标 ≤30%)</span></div>"
                f"</div>"
                f"<div style='margin-top:14px;padding-top:12px;border-top:1px solid #e5e5ea;'>"
                f"<div style='font-size:0.7rem;color:#86868b;'>净资产</div>"
                f"<div style='font-size:1.2rem;font-weight:800;color:#1d1d1f;letter-spacing:-0.02em;'>"
                f"RM {net_worth:,.0f}</div>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        with p_col:
            # Donut chart
            labels_pi = list(class_totals.keys())
            values_pi = [class_totals[k] for k in labels_pi]
            colors_pi = {"Productive": "#34c759", "Defensive": "#5ac8fa",
                         "Cash": "#ff9500", "Speculative": "#ff3b30"}
            fig_pi = go.Figure(go.Pie(
                labels=labels_pi, values=values_pi, hole=0.55,
                marker=dict(colors=[colors_pi[k] for k in labels_pi]),
                textinfo="label+percent", textfont=dict(size=11),
                hovertemplate="<b>%{label}</b><br>RM %{value:,.0f} (%{percent})<extra></extra>",
            ))
            nw_label = f"RM {net_worth/1000:.1f}K" if abs(net_worth) < 1e6 else f"RM {net_worth/1e6:.2f}M"
            fig_pi.update_layout(
                showlegend=False, margin=dict(l=0, r=0, t=10, b=10), height=260,
                paper_bgcolor="rgba(0,0,0,0)",
                annotations=[dict(text=nw_label, x=0.5, y=0.5, showarrow=False,
                                  font=dict(size=13, color="#1d1d1f"))]
            )
            st.plotly_chart(fig_pi, use_container_width=True, config={"displayModeBar": False})

            # Asset breakdown
            with st.expander("所有资产 — 它们属于哪一类？", expanded=False):
                advice_map = {
                    "Productive":  "为您工作生钱。请持有或增加。",
                    "Defensive":   "安全但回报低。适合作为基础储备。",
                    "Cash":        "闲置现金会因通胀贬值。请投资于生产性资产。",
                    "Speculative": "无现金流。请保持在总资产的10%以内。",
                }
                for a in sorted(asset_rows, key=lambda x: x["balance"], reverse=True):
                    pct = a["balance"] / total_assets * 100
                    adv = advice_map.get(a["class"], "")
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:10px;"
                        f"padding:7px 0;border-bottom:1px solid #f0f0f0;'>"
                        f"<div style='width:8px;height:8px;border-radius:50%;"
                        f"background:{a['color']};flex-shrink:0;'></div>"
                        f"<div style='flex:1;font-size:0.8rem;font-weight:600;color:#1d1d1f;'>{a['name']}"
                        f"<span style='font-size:0.7rem;color:#86868b;font-weight:400;"
                        f"margin-left:6px;'>{a['class']}</span></div>"
                        f"<div style='font-size:0.8rem;font-weight:700;color:#1d1d1f;'>"
                        f"RM {a['balance']:,.0f}"
                        f"<span style='font-size:0.7rem;color:#86868b;font-weight:400;"
                        f"margin-left:4px;'>({pct:.0f}%)</span></div>"
                        f"<div style='font-size:0.69rem;color:{a['color']};font-weight:600;"
                        f"width:160px;text-align:right;'>{adv}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        # Actionable recommendations
        st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
        recs = []
        if spec_pct > 20:
            recs.append(("#ff3b30",
                f"您的投机性资产 ({spec_pct:.0f}%) 过高。巴菲特避免投资"
                f"没有现金流的资产（例如加密货币、投机性黄金）。考虑将其降至"
                f"≤10%，并重新部署到优质股票或单位信托中。"))
        if cash_pct > 25:
            recs.append(("#ff9500",
                f"您有 {cash_pct:.0f}% 的闲置现金。巴菲特说：‘长期来看，现金是糟糕的"
                f"投资。’保留3-6个月的支出作为紧急储备金，"
                f"其余部分投资于生产性资产。"))
        if debt_ratio > 40:
            recs.append(("#ff3b30",
                f"债务占您总资产的 {debt_ratio:.0f}%。高额债务会通过利息支付"
                f"摧毁财富。巴菲特说：‘我见过太多人因为杠杆而破产。’"
                f"在进行更多投资之前，优先清除个人贷款。"))
        if prod_pct < 40:
            recs.append(("#007aff",
                f"只有 {prod_pct:.0f}% 的资产在为您积极工作。"
                f"目标是达到50%+的生产性资产（EPF、优质股票、单位信托）。"
                f"它们随着时间复利增长——其他资产则不会。"))
        if not recs:
            recs.append(("#34c759",
                f"您的投资组合结构很坚实。现在关注您所有个人股票的"
                f"具体质量。使用下方的第3步分析每一只股票。"))

        for color, msg in recs:
            st.markdown(
                f"<div style='background:#f5f5f7;border-left:4px solid {color};"
                f"border-radius:0 12px 12px 0;padding:12px 16px;margin-bottom:10px;"
                f"font-size:0.79rem;color:#3c3c43;line-height:1.65;'>{msg}</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 2 — BUFFETT'S DECISION SYSTEM
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown(
        "<div style='font-size:1.1rem;font-weight:800;color:#1d1d1f;"
        "letter-spacing:-0.02em;margin-bottom:4px;'>第2步  —  巴菲特的四重过滤系统</div>"
        "<div style='font-size:0.78rem;color:#86868b;margin-bottom:16px;'>"
        "想想您正在考虑投资的一家特定公司，然后诚实地回答每个问题。"
        "在投入任何资金之前必须通过所有 4 个过滤器。跳过任何一个，证明您只是在投机，而不是在投资。</div>",
        unsafe_allow_html=True,
    )

    # ── Filter 1: Business Understanding ──────────────────────────────────────
    st.markdown(_filter_box("1", "我了解这项业务吗？",
        "巴菲特法则第1条：只投资您完全了解的东西。"
        "如果您无法向一个10岁的孩子解释清楚，就不要投资。"), unsafe_allow_html=True)

    q1a = st.checkbox("我可以用一句话解释这家公司是如何赚钱的", key="vi_q1a")
    st.caption("例子：“Visa在世界各地人们刷卡时都会收取少量手续费。”")
    q1b = st.checkbox("我亲自使用、看过或体验过这个产品/服务", key="vi_q1b")
    st.caption("您喝可口可乐，使用Google，去沃尔玛购物。从您已经熟悉的东西开始。")
    q1c = st.checkbox("我了解未来10年可能严重打击这项业务的因素", key="vi_q1c")
    st.caption("电动车冲击石油，流媒体冲击DVD租赁。了解风险是理解业务的一部分。")
    q1d = st.checkbox("这不是一家我不了解的生物技术公司、复杂的科技公司或金融工具", key="vi_q1d")
    st.caption("坚持简单的业务。对初学者来说，复杂性是回报的大敌。")

    f1_score = sum([q1a, q1b, q1c, q1d])
    f1_pass  = f1_score >= 3
    f1_color = "#34c759" if f1_pass else "#ff3b30"
    f1_label = "通过 — 您了解这项业务" if f1_pass else "停止 — 不要投资您不了解的东西"
    st.markdown(
        f"<div style='background:{f1_color};color:white;border-radius:8px;"
        f"padding:8px 14px;font-size:0.8rem;font-weight:700;margin:8px 0 4px;'>{f1_label}</div>"
        f"</div>",  # closes the filter box div
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── Filter 2: Economic Moat ────────────────────────────────────────────────
    st.markdown(_filter_box("2", "它有经济护城河吗？",
        "护城河是一种持久的竞争优势——就像城堡的护城河——保护企业"
        "不受竞争对手的影响。没有护城河，任何利润都会在竞争中消失。"), unsafe_allow_html=True)

    q2a = st.checkbox("品牌力量：即使有更便宜的替代品，人们也选择它", key="vi_q2a")
    st.caption("耐克对比无名鞋。可口可乐对比普通可乐。人们愿意为品牌支付溢价。")
    q2b = st.checkbox("转换成本：客户转向竞争对手会损失太多时间/金钱", key="vi_q2b")
    st.caption("公司使用微软Office——更换软件意味着要重新培训1万名员工。他们会选择留下。")
    q2c = st.checkbox("网络效应：使用的人越多它就越有价值", key="vi_q2c")
    st.caption("Visa：接受的商家越多 → 想要它的人越多 → 商家越多。自我强化的循环。")
    q2d = st.checkbox("成本优势：该公司的生产成本比行业内任何其他人都低", key="vi_q2d")
    st.caption("沃尔玛庞大的规模让它能以任何小型竞争对手无法匹敌的价格从供应商那里进货。")
    q2e = st.checkbox("我相信这条护城河在10年后依然会存在，而不仅仅是今天", key="vi_q2e")
    st.caption("最难回答的问题。技术可以轻易推翻护城河。在勾选前请深思熟虑。")

    f2_score = sum([q2a, q2b, q2c, q2d, q2e])
    f2_pass  = f2_score >= 2
    f2_color = "#34c759" if f2_score >= 3 else "#ff9500" if f2_score >= 2 else "#ff3b30"
    f2_label = ("通过 — 护城河深厚" if f2_score >= 3
                else "较弱 — 有一些保护但很脆弱" if f2_score >= 2
                else "失败 — 没有明显的竞争优势")
    st.markdown(
        f"<div style='background:{f2_color};color:white;border-radius:8px;"
        f"padding:8px 14px;font-size:0.8rem;font-weight:700;margin:8px 0 4px;'>{f2_label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── Filter 3: Management Quality ───────────────────────────────────────────
    st.markdown(_filter_box("3", "我可以信任管理层吗？",
        "伟大的企业也会被不诚实或无能的领导者摧毁。"
        "您将您的钱托付给他们数年。"), unsafe_allow_html=True)

    q3a = st.checkbox("CEO/创始人拥有大量股份（他们与利益挂钩）", key="vi_q3a")
    st.caption("查看年报。持有股份的管理者会像所有者一样思考，而不是像被雇佣的员工。")
    q3b = st.checkbox("公司持续通过分红或股票回购向股东返还资金", key="vi_q3b")
    st.caption("这表明管理层关心股东利益，而不仅仅是建立自己的商业帝国。")
    q3c = st.checkbox("过去5年中没有重大的丑闻、欺诈或违规行为", key="vi_q3c")
    st.caption("如果他们曾在钱上撒谎，就不要把您的钱托付给他们。一次打击都嫌太多。")
    q3d = st.checkbox("管理层能够诚实地承认错误——他们不会总是指责外部因素", key="vi_q3d")
    st.caption("阅读年报中的CEO致股东信。寻找‘我们犯了一个错误’，而不是只有‘宏观逆风’。")

    f3_score = sum([q3a, q3b, q3c, q3d])
    f3_pass  = f3_score >= 3
    f3_color = "#34c759" if f3_pass else "#ff9500" if f3_score >= 2 else "#ff3b30"
    f3_label = ("通过 — 管理层似乎值得信赖" if f3_pass
                else "注意 — 进一步了解管理层" if f3_score >= 2
                else "失败 — 不要将您的钱托付给这个管理层")
    st.markdown(
        f"<div style='background:{f3_color};color:white;border-radius:8px;"
        f"padding:8px 14px;font-size:0.8rem;font-weight:700;margin:8px 0 4px;'>{f3_label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── Filter 4: Price & Margin of Safety ────────────────────────────────────
    st.markdown(_filter_box("4", "我支付的价格合理并有安全边际吗？",
        "即使是一家出色的公司，如果您支付了过高的价格，这也是一项糟糕的投资。"
        "巴菲特希望以低于真实价值至少20-30%的价格购买——这个缓冲带就是安全边际。"),
        unsafe_allow_html=True)

    f4_c1, f4_c2, f4_c3 = st.columns(3)
    with f4_c1:
        f4_eps = st.number_input("EPS — 每股收益 ($)", value=5.0, step=0.1,
                                  format="%.2f", key="f4_eps",
                                  help="在雅虎财经（Yahoo Finance）中查找 → Statistics → EPS (TTM)。公司每股的利润。")
    with f4_c2:
        f4_g = st.number_input("预期增长率 (%/年)", value=10.0, step=1.0,
                                format="%.0f", key="f4_g",
                                help="保守一点。即便是优秀公司，巴菲特也只使用8-12%。千万不要使用20%以上。")
    with f4_c3:
        f4_price = st.number_input("当前市场价格 ($)", value=100.0, step=1.0,
                                    format="%.2f", key="f4_price",
                                    help="您今天在股票市场上需要支付的价格。")

    f4_pass = False
    if f4_eps > 0 and f4_price > 0:
        iv_f4   = f4_eps * (8.5 + 2 * f4_g) * 4.4 / 4.5   # fixed 4.5% AAA yield
        mos_f4  = (iv_f4 - f4_price) / iv_f4 * 100 if iv_f4 > 0 else -100
        f4_pass = mos_f4 >= 20

        f4_color = "#34c759" if mos_f4 >= 30 else "#ff9500" if mos_f4 >= 15 else "#ff3b30"
        f4_label = (f"通过 — {mos_f4:.0f}% 安全边际。价格具有吸引力。" if mos_f4 >= 30
                    else f"等待 — 只有 {mos_f4:.0f}% 边际。还不够便宜。" if mos_f4 >= 15
                    else f"溢价 — 您支付的价格高出其内在价值 {abs(mos_f4):.0f}%。")

        st.markdown(
            f"<div style='display:flex;gap:10px;margin-top:12px;'>"
            f"<div style='background:white;border-radius:10px;padding:10px 14px;flex:1;text-align:center;'>"
            f"<div style='font-size:0.68rem;color:#86868b;font-weight:600;margin-bottom:2px;'>内在价值</div>"
            f"<div style='font-size:1.25rem;font-weight:800;color:#1d1d1f;'>${iv_f4:,.2f}</div></div>"
            f"<div style='background:white;border-radius:10px;padding:10px 14px;flex:1;text-align:center;'>"
            f"<div style='font-size:0.68rem;color:#86868b;font-weight:600;margin-bottom:2px;'>您的价格</div>"
            f"<div style='font-size:1.25rem;font-weight:800;color:#1d1d1f;'>${f4_price:,.2f}</div></div>"
            f"<div style='background:white;border-radius:10px;padding:10px 14px;flex:1;text-align:center;'>"
            f"<div style='font-size:0.68rem;color:#86868b;font-weight:600;margin-bottom:2px;'>安全边际</div>"
            f"<div style='font-size:1.25rem;font-weight:800;color:{f4_color};'>{mos_f4:.0f}%</div></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='background:{f4_color};color:white;border-radius:8px;"
            f"padding:8px 14px;font-size:0.8rem;font-weight:700;margin:8px 0 4px;'>{f4_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("</div>", unsafe_allow_html=True)

    # Final verdict
    filters_passed = sum([f1_pass, f2_pass, f3_pass, f4_pass])
    _verdict_bar(filters_passed)

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 3 — HOW TO FIND GOOD COMPANIES + LIVE ANALYZER
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown(
        "<div style='font-size:1.1rem;font-weight:800;color:#1d1d1f;"
        "letter-spacing:-0.02em;margin-bottom:4px;'>第3步  —  如何寻找优质公司</div>"
        "<div style='font-size:0.78rem;color:#86868b;margin-bottom:16px;'>"
        "最好的起点是您自己的生活。您每天都在使用哪些产品？"
        "您信任哪些品牌？您在周围看到了哪些蓬勃发展的企业？</div>",
        unsafe_allow_html=True,
    )

    col_easy, col_hard = st.columns(2)
    with col_easy:
        st.markdown(
            "<div style='background:#f5f5f7;border-radius:14px;padding:18px;height:100%;'>"
            "<div style='font-size:0.76rem;font-weight:700;color:#34c759;margin-bottom:10px;"
            "text-transform:uppercase;letter-spacing:0.06em;'>容易理解（适合初学者）</div>"
            "<div style='font-size:0.78rem;color:#3c3c43;line-height:1.9;'>"
            "<b>消费品牌</b> — 可口可乐 (KO), 麦当劳 (MCD), 耐克 (NKE)<br>"
            "<b>支付网络</b> — Visa (V), 万事达卡 (MA) — 从每次刷卡中获益<br>"
            "<b>必备零售</b> — 沃尔玛 (WMT), 好市多 (COST) — 人们总是需要杂货<br>"
            "<b>您每天使用的大型科技公司</b> — 苹果 (AAPL), Alphabet/谷歌 (GOOGL)<br>"
            "<b>基础医疗保健</b> — 强生 (JNJ) — 人们总是需要药物<br>"
            "<b>您经常用的银行</b> — 摩根大通 (JPM) — 简单的贷款+存款模式"
            "</div>"
            "<div style='margin-top:12px;background:#dcfce7;border-radius:8px;padding:10px 12px;"
            "font-size:0.74rem;color:#166534;line-height:1.55;'>"
            "<b>10岁儿童测试：</b>一个孩子能理解这家公司是如何赚钱的吗？"
            "如果可以，它会自动通过巴菲特的第一个过滤器。"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with col_hard:
        st.markdown(
            "<div style='background:#f5f5f7;border-radius:14px;padding:18px;height:100%;'>"
            "<div style='font-size:0.76rem;font-weight:700;color:#ff3b30;margin-bottom:10px;"
            "text-transform:uppercase;letter-spacing:0.06em;'>难以理解（初学者请避开）</div>"
            "<div style='font-size:0.78rem;color:#3c3c43;line-height:1.9;'>"
            "<b>生物技术 / 医药研发</b> — 一次药物被拒即可能抹去80%的市值<br>"
            "<b>半导体（芯片）</b> — 周期复杂、受地缘政治影响、技术护城河难以理解<br>"
            "<b>巨型综合企业</b> — 同时运营太多业务；难以对各项业务估值<br>"
            "<b>SPAC壳公司 / 新股IPO</b> — 没有历史业绩。纯粹的投机。<br>"
            "<b>模因股/网红股</b> — 受Reddit和TikTok驱动，而非基本面<br>"
            "<b>加密货币</b> — 没有收益，没有现金流，没有内在价值"
            "</div>"
            "<div style='margin-top:12px;background:#fee2e2;border-radius:8px;padding:10px 12px;"
            "font-size:0.74rem;color:#991b1b;line-height:1.55;'>"
            "<b>巴菲特法则：</b>如果您在5分钟内无法理解一项业务，"
            "就把它扔进“太难”的一堆里并继续前进。世界上还有成千上万家其他的公司。"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # Where to research
    st.markdown(
        "<div style='background:#1d1d1f;border-radius:14px;padding:18px 20px;margin-bottom:18px;'>"
        "<div style='font-size:0.76rem;font-weight:700;color:#aeaeb2;margin-bottom:12px;"
        "text-transform:uppercase;letter-spacing:0.06em;'>免费研究资源</div>"
        "<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;'>"
        "<div style='background:rgba(255,255,255,0.06);border-radius:10px;padding:12px;'>"
        "<div style='font-size:0.8rem;font-weight:600;color:#fff;margin-bottom:4px;'>雅虎财经 (Yahoo Finance)</div>"
        "<div style='font-size:0.72rem;color:#86868b;line-height:1.5;'>finance.yahoo.com — 搜索任何股票代码。"
        "查看：市盈率(P/E)、每股收益(EPS)、收入(Revenue)、利润率(Profit Margin)、分红(Dividends)标签页。</div></div>"
        "<div style='background:rgba(255,255,255,0.06);border-radius:10px;padding:12px;'>"
        "<div style='font-size:0.8rem;font-weight:600;color:#fff;margin-bottom:4px;'>年度报告 (10-K)</div>"
        "<div style='font-size:0.72rem;color:#86868b;line-height:1.5;'>公司网站 → 投资者关系 (Investor Relations)。"
        "先看CEO致股东信。诚实的CEO会承认错误。</div></div>"
        "<div style='background:rgba(255,255,255,0.06);border-radius:10px;padding:12px;'>"
        "<div style='font-size:0.8rem;font-weight:600;color:#fff;margin-bottom:4px;'>伯克希尔致股东信</div>"
        "<div style='font-size:0.72rem;color:#86868b;line-height:1.5;'>berkshirehathaway.com/letters — "
        "巴菲特自1977年以来的年度信件。免费的价值投资MBA课程。</div></div>"
        "<div style='background:rgba(255,255,255,0.06);border-radius:10px;padding:12px;'>"
        "<div style='font-size:0.8rem;font-weight:600;color:#fff;margin-bottom:4px;'>Macrotrends网站</div>"
        "<div style='font-size:0.72rem;color:#86868b;line-height:1.5;'>macrotrends.net — 查看过去20多年的"
        "历史财务数据。检查净资产收益率(ROE)和利润率是否一直保持稳定。</div></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    # Live Stock Analyzer
    st.markdown(
        "<div style='font-size:0.92rem;font-weight:700;color:#1d1d1f;margin-bottom:4px;'>"
        "实时股票分析器 — 巴菲特8项指标得分卡</div>"
        "<div style='font-size:0.76rem;color:#86868b;margin-bottom:12px;'>"
        "输入任何美股代码（如 AAPL）。分析器将提取真实数据并将其与"
        "巴菲特的8个关键指标进行对比，并附有各项数据的通俗中文解释。</div>",
        unsafe_allow_html=True,
    )

    t_col, r_col = st.columns([5, 1])
    with t_col:
        ticker_input = st.text_input(
            "ticker", label_visibility="collapsed", key="vi_ticker_input",
            placeholder="输入股票代码：KO, AAPL, V, JNJ, WMT, MCD, MSFT...",
        ).strip().upper()
    with r_col:
        if st.button("清除缓存", key="vi_clear", use_container_width=True):
            _fetch_value_metrics.clear()
            st.rerun()

    if ticker_input:
        with st.spinner(f"正在加载 {ticker_input} 的数据…"):
            m = _fetch_value_metrics(ticker_input)

        if not m or not m.get("price"):
            st.warning(f"没有 **{ticker_input}** 的数据。请尝试输入如 KO, AAPL, V, JNJ 等在美上市的股票代码。")
        else:
            mktcap  = m.get("market_cap")
            cap_str = (f"${mktcap/1e12:.2f}T" if mktcap and mktcap >= 1e12
                       else f"${mktcap/1e9:.1f}B" if mktcap and mktcap >= 1e9
                       else f"${mktcap/1e6:.0f}M" if mktcap else "N/A")

            st.markdown(
                f"<div style='background:#1d1d1f;border-radius:14px;padding:18px 20px;margin-bottom:16px;'>"
                f"<div style='font-size:1.25rem;font-weight:800;color:#fff;letter-spacing:-0.02em;'>"
                f"{m['name']}<span style='font-size:0.78rem;color:#636366;font-weight:500;"
                f"margin-left:10px;'>{ticker_input}</span></div>"
                f"<div style='font-size:0.76rem;color:#86868b;margin-top:4px;'>"
                f"{m.get('sector','')}{'  ·  ' + m.get('industry','') if m.get('industry') else ''}"
                f"  ·  市值 {cap_str}</div>"
                f"<div style='font-size:1.9rem;font-weight:800;color:#fff;"
                f"letter-spacing:-0.04em;margin-top:10px;'>${m['price']:,.2f}"
                f"<span style='font-size:0.76rem;color:#636366;font-weight:400;margin-left:12px;'>"
                f"52周范围  {m.get('52w_low','?')} – {m.get('52w_high','?')}</span></div></div>",
                unsafe_allow_html=True,
            )

            pe = m.get("pe");    pb = m.get("pb");    roe = m.get("roe")
            de = m.get("debt_equity");   cr = m.get("current_ratio")
            nm = m.get("net_margin");    dy = m.get("dividend_yield")
            eg = m.get("eps_growth")

            score = sum([
                pe  is not None and pe  < 25,
                pb  is not None and pb  < 3,
                roe is not None and roe >= 0.15,
                de  is not None and de  < 100,
                cr  is not None and cr  >= 1.5,
                nm  is not None and nm  >= 0.10,
                dy  is not None and dy  > 0,
                eg  is not None and eg  >= 0.05,
            ])

            sc_col, ch_col = st.columns([1, 2])
            with sc_col:
                st.markdown(_score_ring(score, 8), unsafe_allow_html=True)
                if m.get("summary"):
                    with st.expander("业务摘要"):
                        st.caption(m["summary"][:700] + ("…" if len(m.get("summary","")) > 700 else ""))
            with ch_col:
                ph = m.get("price_history")
                if ph is not None and not ph.empty:
                    pct5 = (ph.iloc[-1] / ph.iloc[0] - 1) * 100
                    c5   = "#34c759" if pct5 >= 0 else "#ff3b30"
                    r5, g5, b5 = int(c5[1:3], 16), int(c5[3:5], 16), int(c5[5:7], 16)
                    fig5 = go.Figure()
                    fig5.add_trace(go.Scatter(
                        x=ph.index, y=ph.values, mode="lines",
                        line=dict(color=c5, width=1.8), fill="tozeroy",
                        fillcolor=f"rgba({r5},{g5},{b5},0.10)",
                        hovertemplate="<b>%{x|%Y年%m月}</b><br>$%{y:,.2f}<extra></extra>",
                    ))
                    fig5.update_layout(
                        title=dict(text=f"5年价格走势  ·  {'+' if pct5>=0 else ''}{pct5:.1f}%",
                                   font=dict(size=12)),
                        xaxis=dict(showgrid=False, zeroline=False),
                        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", zeroline=False, tickprefix="$"),
                        plot_bgcolor="white", paper_bgcolor="white",
                        margin=dict(l=8, r=8, t=40, b=8), height=200,
                        showlegend=False, hovermode="x unified",
                    )
                    st.plotly_chart(fig5, use_container_width=True, config={"displayModeBar": False})

            def _fmt(v, fmt=".1f", suffix="", mult=1):
                return f"{v * mult:{fmt}}{suffix}" if v is not None else "N/A"

            st.markdown(
                "<div style='font-size:0.84rem;font-weight:700;color:#1d1d1f;"
                "margin:14px 0 10px;'>巴菲特的 8 项关键指标</div>",
                unsafe_allow_html=True,
            )
            col_a, col_b = st.columns(2)

            with col_a:
                g_pe, c_pe = _grade(pe, True, (15, 25))
                st.markdown(_metric_card(
                    "市盈率 (P/E) — 价格 ÷ 收益", _fmt(pe, ".1f", "x"), g_pe, c_pe,
                    "您为当前利润支付了多少年的价格。低于15 = 物超所值。"
                    "高于30 = 市场预期未来会有巨大增长——如果增长放缓，风险很高。",
                    "我寻找市盈率低于15-20的真正伟大企业。超过25会让我感到不安。",
                ), unsafe_allow_html=True)

                g_pb, c_pb = _grade(pb, True, (1.5, 3.0))
                st.markdown(_metric_card(
                    "市净率 (P/B) — 价格 ÷ 账面价值", _fmt(pb, ".2f", "x"), g_pb, c_pb,
                    "您支付的价格是否高于净资产的价值？低于1.0 = 用不到1美元买到了"
                    "价值1美元的资产。高于5 = 非常昂贵。",
                    "我喜欢以接近或低于账面价值的价格购买公司，尤其是金融公司。",
                ), unsafe_allow_html=True)

                g_de, c_de = _grade(de, True, (50, 100))
                st.markdown(_metric_card(
                    "债务股本比 (Debt/Equity) — 借了多少钱？",
                    _fmt(de, ".0f", "%") if de is not None else "N/A", g_de, c_de,
                    "债务越多，在经济衰退时就越脆弱。低于50% = 保守稳健。"
                    "高于100% = 公司欠的钱比拥有的多。",
                    "我避开严重依赖债务的公司。杠杆会把小错误变成巨大的灾难。",
                ), unsafe_allow_html=True)

                g_nm, c_nm = _grade(nm, False, (0.20, 0.10))
                st.markdown(_metric_card(
                    "净利润率 (Net Margin) — 扣除所有成本后保留的百分比",
                    _fmt(nm, ".1f", "%", 100), g_nm, c_nm,
                    "每一美元的销售额中，有多少是实际利润？高于20% = 具有定价权和护城河。"
                    "低于5% = 毫无优势的商品化业务。",
                    "高而稳定的利润率是持久竞争优势最清晰的印记。",
                ), unsafe_allow_html=True)

            with col_b:
                g_roe, c_roe = _grade(roe, False, (0.20, 0.15))
                st.markdown(_metric_card(
                    "净资产收益率 (ROE)",
                    _fmt(roe, ".1f", "%", 100), g_roe, c_roe,
                    "公司使用股东资金的效率如何。"
                    "连续10年以上保持在15%以上 = 强大的护城河。这是巴菲特最看重的单一指标。",
                    "我寻找多年来一直保持在15%以上的ROE。那是护城河最清晰的标志。",
                ), unsafe_allow_html=True)

                g_cr, c_cr = _grade(cr, False, (2.0, 1.5))
                st.markdown(_metric_card(
                    "流动比率 (Current Ratio) — 能否支付短期账单？",
                    _fmt(cr, ".2f", "x"), g_cr, c_cr,
                    "流动资产 ÷ 流动负债。低于1.0 = 公司无法支付近期债务。"
                    "高于2.0 = 非常安全。",
                    "一个无法支付账单的公司距离崩溃仅差一次经济衰退。",
                ), unsafe_allow_html=True)

                g_dy, c_dy = _grade(dy, False, (0.03, 0.01))
                st.markdown(_metric_card(
                    "股息率 (Dividend Yield) — 支付给股东的现金",
                    _fmt(dy, ".2f", "%", 100), g_dy, c_dy,
                    "年度派息 ÷ 股价。如果20多年来有可靠、增长的股息，"
                    "这是健康企业最强烈的信号之一。",
                    "股息不能被伪造。如果一家公司30年来一直向您支付现金，那是一项真正的生意。",
                ), unsafe_allow_html=True)

                g_eg, c_eg = _grade(eg, False, (0.10, 0.05))
                st.markdown(_metric_card(
                    "每股收益增长率 (EPS Growth) — 收益是否逐年增长？",
                    _fmt(eg, ".1f", "%", 100), g_eg, c_eg,
                    "每股收益的年增长率。在5-10年中保持8-15%的一致增长，"
                    "是优质企业最强烈的标志之一。",
                    "我想要那些盈利能力像时钟一样年复一年复利增长的公​​司。",
                ), unsafe_allow_html=True)

            # Graham Number
            eps_v = m.get("eps"); price_v = m.get("price"); pb_v = m.get("pb")
            if eps_v and eps_v > 0 and pb_v and pb_v > 0 and price_v:
                bvps     = price_v / pb_v
                graham_n = math.sqrt(22.5 * eps_v * bvps)
                mos_g    = (graham_n - price_v) / graham_n * 100
                mg_color = "#34c759" if mos_g >= 20 else "#ff9500" if mos_g >= 0 else "#ff3b30"
                mg_label = "被低估" if mos_g >= 20 else "估值合理" if mos_g >= 0 else "被高估"

                st.divider()
                st.markdown(
                    "<div style='font-size:0.86rem;font-weight:700;color:#1d1d1f;margin-bottom:6px;'>"
                    "格雷厄姆数字 (Graham Number) — 快速合理价格检查</div>"
                    "<div style='font-size:0.75rem;color:#86868b;margin-bottom:12px;'>"
                    "公式：√(22.5 × EPS × 每股账面价值)。"
                    "本·格雷厄姆认为保守投资者应该支付的最高价格。</div>",
                    unsafe_allow_html=True,
                )
                gn1, gn2, gn3 = st.columns(3)
                with gn1: st.metric("格雷厄姆数字 (合理价格)", f"${graham_n:,.2f}")
                with gn2: st.metric("当前市场价格", f"${price_v:,.2f}")
                with gn3: st.metric("安全边际", f"{mos_g:.1f}%", delta=mg_label)
                st.markdown(
                    f"<div style='background:#f5f5f7;border-radius:12px;padding:12px 16px;"
                    f"font-size:0.76rem;color:#3c3c43;line-height:1.6;'>"
                    f"以 ${price_v:,.2f} 的价格来看，相对于 ${graham_n:,.2f} 的格雷厄姆合理价格，"
                    f"该股票 <span style='color:{mg_color};font-weight:700;'>{mg_label} "
                    f"{abs(mos_g):.1f}%</span>。"
                    f"{'安全垫良好 — 值得进一步研究。' if mos_g >= 20 else '接近公允价值 — 这里的业务质量比价格更重要。' if mos_g >= 0 else '价格高于格雷厄姆合理价值。等待回调。'}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 4 — INTRINSIC VALUE CALCULATOR
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown(
        "<div style='font-size:1.1rem;font-weight:800;color:#1d1d1f;"
        "letter-spacing:-0.02em;margin-bottom:4px;'>第4步  —  计算真实价值</div>"
        "<div style='font-size:0.78rem;color:#86868b;margin-bottom:6px;line-height:1.6;'>"
        "使用<b>本杰明·格雷厄姆的内在价值公式</b> — 这是巴菲特从他在"
        "哥伦比亚大学的导师那里学到的同一个公式：</div>"
        "<div style='background:#f5f5f7;border-radius:10px;padding:12px 16px;margin-bottom:16px;"
        "font-family:monospace;font-size:0.82rem;color:#1d1d1f;'>"
        "IV = EPS × (8.5 + 2g) × 4.4 / Y"
        "<div style='font-size:0.72rem;color:#86868b;margin-top:6px;font-family:sans-serif;'>"
        "EPS = 每股收益  ·  g = 预期年增长率 %  ·  "
        "8.5 = 零增长公司的基本市盈率  ·  4.4 = 格雷厄姆设定的基本债券名义收益率  ·  Y = 当前 AAA 级公司债券收益率 (~4.5%)"
        "</div></div>",
        unsafe_allow_html=True,
    )

    iv_c1, iv_c2, iv_c3, iv_c4 = st.columns(4)
    with iv_c1:
        iv_eps = st.number_input("EPS (过去12个月, $)", value=5.0, step=0.1, format="%.2f", key="iv_eps",
                                  help="在雅虎财经（Yahoo Finance）查找 → Statistics → EPS (TTM)")
    with iv_c2:
        iv_g = st.number_input("预期增长率 %/年", value=10.0, step=0.5, format="%.1f", key="iv_g",
                                help="保守一点。即便是优秀公司，巴菲特也只使用8-12%。")
    with iv_c3:
        iv_y = st.number_input("AAA级债券收益率 %", value=4.5, step=0.1, format="%.1f", key="iv_y",
                                help="当前美国30年期AAA级公司债券收益率（2025年约为4-5%）。")
    with iv_c4:
        iv_price = st.number_input("当前市场价格 ($)", value=100.0, step=1.0, format="%.2f", key="iv_price")

    if iv_eps > 0 and iv_y > 0:
        iv    = iv_eps * (8.5 + 2 * iv_g) * 4.4 / iv_y
        mos   = (iv - iv_price) / iv * 100 if iv > 0 else 0
        mc    = "#34c759" if mos >= 30 else "#ff9500" if mos >= 15 else "#ff3b30"
        mlabel = "强力买入区" if mos >= 30 else "估值合理" if mos >= 15 else "定价过高 — 等待"

        m1, m2, m3 = st.columns(3)
        with m1: st.metric("内在价值 (格雷厄姆)", f"${iv:,.2f}")
        with m2: st.metric("当前价格", f"${iv_price:,.2f}")
        with m3: st.metric("安全边际", f"{mos:.1f}%", delta=mlabel)

        if mos >= 30:
            interp = f"以 {mos:.1f}% 的折扣买入 — 强大的安全边际。"
        elif mos >= 0:
            interp = f"支付的价格接近公允价值 — 等待更便宜的买入机会。"
        else:
            interp = f"支付的价格比内在价值高出 {abs(mos):.1f}% — 避免买入直到价格下跌。"

        st.markdown(
            f"<div style='background:#f5f5f7;border-radius:12px;padding:14px 18px;"
            f"font-size:0.78rem;color:#3c3c43;line-height:1.65;margin-top:4px;'>"
            f"<b>这意味着什么：</b> 根据您的输入，估计内在真实价值为 "
            f"<b>${iv:,.2f}</b>。以 ${iv_price:,.2f} 的价格来看，您正 "
            f"<span style='color:{mc};font-weight:700;'>{interp}</span> "
            f"巴菲特要求在买入前至少有 20-30% 的安全边际。</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='background:#f5f5f7;border-radius:12px;padding:12px 16px;"
            "font-size:0.75rem;color:#3c3c43;line-height:1.65;margin-top:8px;'>"
            "<b>如何对您的估计进行压力测试：</b> 尝试将增长率降低 3-5%。"
            "如果在保守的数据下该股票仍然被低估，那是一个强烈的买入信号。"
            "巴菲特说：'宁可模糊地正确，也不要精确地错误。'</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # GLOSSARY
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown(
        "<div style='font-size:1rem;font-weight:700;color:#1d1d1f;"
        "margin-bottom:14px;letter-spacing:-0.01em;'>快速参考 — 价值投资词汇表</div>",
        unsafe_allow_html=True,
    )

    glossary = [
        ("内在价值 (Intrinsic Value)",
         "基于未来收益和现金流的企业真实价值——"
         "而不是股票价格。它代表如果您完全拥有整个业务，它会值多少钱。"),
        ("安全边际 (Margin of Safety)",
         "内在价值与您支付价格之间的差距。"
         "如果真实价值是100美元，以70美元买入（30%的缓冲）。这是您对估值错误的保护垫。"),
        ("经济护城河 (Economic Moat)",
         "阻碍竞争对手窃取利润的持久竞争优势（品牌、网络效应、转换成本、成本领先优势）。"
         "这是巴菲特最看重的概念。"),
        ("市盈率 (P/E Ratio)",
         "价格 ÷ 每股收益。您为当前利润支付了多少年的价格。"
         "越低 = 越便宜。但要总是问自己：它为什么便宜？"),
        ("净资产收益率 (ROE)",
         "净收入 ÷ 股东权益。巴菲特最喜欢的单一指标。"
         "连续保持在15%以上 = 强大的护城河。这是持久优势最清晰的标志。"),
        ("市净率 (P/B Ratio)",
         "价格 ÷ 每股账面价值。您支付的价格是否高于净资产被清算的价值？"
         "低于1.0 = 用不到1美元买到了价值1美元的资产（格雷厄姆的经典信号）。"),
        ("自由现金流 (Free Cash Flow)",
         "扣除所有费用和资本支出后剩余的现金。这是真正的钱——而不是会计数字。"
         "巴菲特称之为‘所有者收益’——实际所有者能保留的现金。"),
        ("股息率 (Dividend Yield)",
         "年度派息金额 ÷ 股价。持续稳定、不断增长的股息 = 真实运作的生意。"
         "公司可以伪造财报利润，但不能伪造支付给股东的真金白银。"),
        ("能力圈 (Circle of Competence)",
         "只投资您真正理解的企业。巴菲特说，知道自己的能力边界"
         "比拥有广泛但肤浅的知识更有价值。"),
        ("市场先生 (Mr. Market)",
         "本·格雷厄姆的隐喻：股市是一个情绪波动的生意伙伴，每天给您一个报价。"
         "当他抑郁（股市崩盘）时 = 买入。当他狂热（泡沫）时 = 卖出或观望。"),
        ("复利 (Compound Interest)",
         "利滚利。爱因斯坦称之为世界第八大奇迹。"
         "巴菲特的全部财富都建立在这之上——早早开始并持有60年以上。"),
        ("格雷厄姆数字 (Graham Number)",
         "√(22.5 × 每股收益 × 每股账面价值)。保守投资者"
         "应该支付的最高价格。低于这个数字的任何价格都有可能被格雷厄姆方法认为是低估的。"),
    ]

    g_col1, g_col2 = st.columns(2)
    for i, (term, definition) in enumerate(glossary):
        col = g_col1 if i % 2 == 0 else g_col2
        with col:
            st.markdown(
                f"<div style='background:#f5f5f7;border-radius:12px;"
                f"padding:14px 16px;margin-bottom:10px;'>"
                f"<div style='font-size:0.78rem;font-weight:700;color:#007aff;"
                f"margin-bottom:5px;'>{term}</div>"
                f"<div style='font-size:0.76rem;color:#3c3c43;line-height:1.55;'>{definition}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def render():
    st.markdown(_FILTER_CSS, unsafe_allow_html=True)
    st.markdown("# Analysis")
    st.divider()

    _render_my_charts()

    # ── Export ────────────────────────────────────────────────────────────────
    snapshots   = repo.list_snapshots()
    pnl_periods = repo.list_pnl_periods()
    pnl_rows    = [repo.get_pnl_by_period(p) for p in pnl_periods]
    pnl_rows    = [r for r in pnl_rows if r]

    export_button(
        data={
            "page": "analysis",
            "snapshots": [
                {
                    "id":                s["id"],
                    "label":             s["label"],
                    "period":            s.get("period", ""),
                    "created_at":        s["created_at"],
                    "net_worth":         s["net_worth"],
                    "total_assets":      s["total_assets"],
                    "total_liabilities": s["total_liabilities"],
                    "monthly_income":    s.get("monthly_income", 0),
                    "monthly_expense":   s.get("monthly_expense", 0),
                    "health_score":      s.get("health_score"),
                }
                for s in snapshots
            ],
            "pnl_history": [
                {
                    "period":        r.get("period", ""),
                    "label":         r.get("label", ""),
                    "total_income":  r.get("total_income", 0),
                    "total_expense": r.get("total_expense", 0),
                    "net_savings":   r.get("net_savings", 0),
                }
                for r in pnl_rows
            ],
        },
        prefix="analysis",
    )
