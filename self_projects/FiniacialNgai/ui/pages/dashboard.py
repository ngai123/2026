"""Main dashboard page — portfolio overview and health score."""
import streamlit as st
import pandas as pd
from database import repository as repo
from analysis.health_score import calculate_health_score
from ui.components.charts import (
    allocation_donut, net_worth_timeline, health_score_gauge
)
from ui.export import export_button
from ui.i18n import get_text


_GRADE_COLOR = {
    "A+": "#34c759", "A": "#34c759", "A-": "#34c759",
    "B+": "#007aff", "B": "#007aff", "B-": "#007aff",
    "C+": "#ff9500", "C": "#ff9500", "C-": "#ff9500",
    "D":  "#ff3b30", "F": "#ff3b30",
}

_GRADE_LABEL = {
    "A+": "Excellent", "A": "Excellent", "A-": "Excellent",
    "B+": "Good", "B": "Good", "B-": "Good",
    "C+": "Fair", "C": "Fair", "C-": "Fair",
    "D": "Poor", "F": "Critical",
}


def _health_color(grade: str) -> str:
    for prefix in (grade, grade[:2], grade[0]):
        if prefix in _GRADE_COLOR:
            return _GRADE_COLOR[prefix]
    return "#6b7280"


def _health_label(grade: str) -> str:
    for prefix in (grade, grade[:2], grade[0]):
        if prefix in _GRADE_LABEL:
            return _GRADE_LABEL[prefix]
    return ""


def render():
    latest_id = repo.get_latest_snapshot_id()

    # Page header
    st.markdown(
        f"<h1 style='margin-bottom:2px;'>{get_text('welcome')}</h1>"
        f"<p style='color:#6b7280;font-size:0.95rem;margin-top:0;margin-bottom:24px;'>"
        f"{get_text('sidebar_subtitle')}</p>",
        unsafe_allow_html=True,
    )

    if not latest_id:
        st.markdown(
            "<div style='background:rgba(255,255,255,.8);backdrop-filter:blur(22px);"
            "border:1px solid rgba(255,255,255,.65);border-radius:24px;padding:36px 40px;"
            "box-shadow:0 8px 40px rgba(0,0,0,.06);animation:fadeInUp .5s ease both;'>"
            f"<h2 style='margin-top:0;'>{get_text('go_to_balance_sheet')}</h2>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- {get_text('onboarding_1')}\n"
            f"- {get_text('onboarding_2')}\n"
            f"- {get_text('onboarding_3')}\n"
            f"- {get_text('onboarding_4')}\n"
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if st.button(get_text('nav_balance_sheet')):
            st.session_state.lang_selector = st.session_state.lang_selector
        return

    snapshot = repo.get_snapshot(latest_id)
    assets = repo.get_snapshot_assets(latest_id)
    all_snapshots = repo.list_snapshots()

    health = calculate_health_score(
        assets=assets,
        total_assets=snapshot["total_assets"],
        total_liabilities=snapshot["total_liabilities"],
        monthly_income=snapshot.get("monthly_income", 0),
        monthly_expense=snapshot.get("monthly_expense", 0),
        risk_profile=snapshot.get("risk_profile", "moderate"),
    )
    repo.update_snapshot_health(latest_id, health.total_score)

    unit = get_text('unit')
    hc = _health_color(health.grade)

    # Compute savings rate from PnL data (0 if unavailable)
    savings_rate = 0.0
    latest_pnl_id = repo.get_latest_pnl_id()
    if latest_pnl_id:
        pnl_data = repo.get_pnl(latest_pnl_id)
        if pnl_data:
            savings_rate = pnl_data.get("savings_rate", 0.0)

    # ── Precision Noir hero card ─────────────────────────────────────
    net_worth = snapshot['net_worth']
    total_assets = snapshot['total_assets']
    total_liabilities = snapshot['total_liabilities']
    health_score = health.total_score
    health_grade = health.grade
    grade_lbl = _health_label(health.grade)

    st.markdown(
        '<div style="background:linear-gradient(135deg,#0f1420,#111827,#0f1a2e);'
        'border-top:2px solid #e8b84b;border-radius:24px;padding:36px 40px;'
        'margin-bottom:32px;display:flex;align-items:center;justify-content:space-between;'
        'flex-wrap:wrap;gap:24px;">'
        '<div>'
        '<div style="font-family:Outfit,sans-serif;font-size:0.65rem;font-weight:600;'
        'text-transform:uppercase;letter-spacing:0.12em;color:#6b7385;margin-bottom:8px;">'
        'TOTAL NET WORTH</div>'
        f'<div style="font-family:Fraunces,serif;font-size:3.5rem;font-weight:900;'
        f'color:#e8b84b;line-height:1.1;letter-spacing:-0.02em;">'
        f'RM {net_worth:,.0f}</div>'
        '<div style="display:flex;gap:10px;margin-top:20px;flex-wrap:wrap;">'
        '<div style="background:rgba(232,184,75,0.08);border:1px solid rgba(232,184,75,0.15);'
        'border-radius:10px;padding:8px 16px;">'
        '<div style="font-family:Outfit,sans-serif;font-size:0.6rem;font-weight:600;'
        'text-transform:uppercase;letter-spacing:0.1em;color:#6b7385;">Assets</div>'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.95rem;'
        f'font-weight:600;color:#e8e6e1;margin-top:2px;">RM {total_assets:,.0f}</div>'
        '</div>'
        '<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);'
        'border-radius:10px;padding:8px 16px;">'
        '<div style="font-family:Outfit,sans-serif;font-size:0.6rem;font-weight:600;'
        'text-transform:uppercase;letter-spacing:0.1em;color:#6b7385;">Liabilities</div>'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.95rem;'
        f'font-weight:600;color:#e8e6e1;margin-top:2px;">RM {total_liabilities:,.0f}</div>'
        '</div>'
        f'<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);'
        'border-radius:10px;padding:8px 16px;">'
        '<div style="font-family:Outfit,sans-serif;font-size:0.6rem;font-weight:600;'
        'text-transform:uppercase;letter-spacing:0.1em;color:#6b7385;">Grade</div>'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.95rem;'
        f'font-weight:600;color:#e8e6e1;margin-top:2px;">{health_grade}</div>'
        '</div>'
        '</div>'
        '</div>'
        '<div style="text-align:center;">'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:3rem;font-weight:700;'
        f'color:#e8b84b;line-height:1;">{health_score:.0f}</div>'
        f'<div style="font-family:Outfit,sans-serif;font-size:0.72rem;font-weight:500;'
        f'color:#6b7385;margin-top:4px;">{grade_lbl}</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Secondary metrics ────────────────────────────────────────────
    monthly_savings = max(0, snapshot.get("monthly_income", 0) - snapshot.get("monthly_expense", 0))
    c1, c2, c3 = st.columns(3)
    c1.metric(get_text("total_assets"),    f"{unit} {snapshot['total_assets']:,.0f}")
    c2.metric(get_text("liabilities"),     f"{unit} {snapshot['total_liabilities']:,.0f}")
    c3.metric(get_text("monthly_savings"), f"{unit} {monthly_savings:,.0f}")

    st.divider()

    # ── Strengths & Issues ───────────────────────────────────────────
    col_a, col_b = st.columns(2)

    def _pill(text: str, color: str, bg: str) -> str:
        return (
            f"<div style='display:flex;align-items:flex-start;gap:10px;"
            f"background:{bg};border-radius:14px;padding:11px 15px;margin-bottom:8px;"
            f"border:1px solid {color}22;animation:fadeInUp .4s ease both;'>"
            f"<span style='color:{color};font-size:1rem;margin-top:1px;'>●</span>"
            f"<span style='color:#374151;font-size:.9rem;line-height:1.5;'>{text}</span></div>"
        )

    with col_a:
        if health.top_wins:
            st.markdown(
                f"<div style='font-size:.74rem;font-weight:700;color:#34c759;text-transform:uppercase;"
                f"letter-spacing:.12em;margin-bottom:12px;'>{get_text('strengths_label')}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "".join(_pill(w, "#34c759", "rgba(52,199,89,.06)") for w in health.top_wins),
                unsafe_allow_html=True,
            )

    with col_b:
        if health.top_issues:
            st.markdown(
                f"<div style='font-size:.74rem;font-weight:700;color:#ff9500;text-transform:uppercase;"
                f"letter-spacing:.12em;margin-bottom:12px;'>{get_text('areas_to_improve_label')}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "".join(_pill(iss, "#ff9500", "rgba(255,149,0,.06)") for iss in health.top_issues),
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Charts ───────────────────────────────────────────────────────
    with st.expander(get_text("asset_allocation")):
        category_totals: dict[str, float] = {}
        for a in assets:
            if not a["is_liability"]:
                cat = a["category"]
                category_totals[cat] = category_totals.get(cat, 0) + a["balance"]
        if category_totals:
            fig_donut = allocation_donut(category_totals)
            st.plotly_chart(fig_donut, use_container_width=True)

    with st.expander(get_text("net_worth_history")):
        if len(all_snapshots) > 1:
            fig_timeline = net_worth_timeline(all_snapshots)
            st.plotly_chart(fig_timeline, use_container_width=True)

            st.markdown(f"### {get_text('previous_snapshots')}")
            for s in all_snapshots:
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                col1.write(s["label"])
                col2.write(s["created_at"][:10])
                col3.write(f"{unit} {s['net_worth']:,.0f}")
                with col4:
                    if st.button("Delete", key=f"del_snap_{s['id']}", help=get_text("delete_tooltip")):
                        repo.delete_snapshot(s["id"])
                        st.rerun()
        else:
            st.info(get_text("no_snapshots"))

    if health.recommendations:
        with st.expander(get_text('recommendations'), expanded=True):
            for i, rec in enumerate(health.recommendations, 1):
                st.markdown(
                    f"<div style='display:flex;gap:14px;align-items:flex-start;"
                    f"padding:12px 0;border-bottom:1px solid rgba(0,0,0,.04);'>"
                    f"<span style='background:#007aff;color:#fff;font-size:.72rem;font-weight:700;"
                    f"border-radius:50%;width:22px;height:22px;display:flex;align-items:center;"
                    f"justify-content:center;flex-shrink:0;margin-top:1px;'>{i}</span>"
                    f"<span style='color:#374151;font-size:.92rem;line-height:1.6;'>{rec}</span></div>",
                    unsafe_allow_html=True,
                )

    st.divider()
    st.caption(f"{get_text('latest_update')}: {snapshot['label']} ({snapshot['created_at'][:10]})")

    # ── Export ───────────────────────────────────────────────────────
    export_button(
        data={
            "page": "dashboard",
            "snapshot": {k: v for k, v in dict(snapshot).items()},
            "assets": [dict(a) for a in assets],
            "health": {
                "total_score":      health.total_score,
                "grade":            health.grade,
                "top_wins":         health.top_wins,
                "top_issues":       health.top_issues,
                "recommendations":  health.recommendations,
            },
            "all_snapshots": [
                {k: v for k, v in dict(s).items() if k != "assets"}
                for s in all_snapshots
            ],
        },
        prefix="dashboard",
    )
