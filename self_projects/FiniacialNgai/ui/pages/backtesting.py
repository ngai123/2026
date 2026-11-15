"""Strategy backtesting page — replay historical returns with real Malaysian data."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import datetime

from analysis.backtester import Backtester, PRESET_STRATEGIES, BacktestResult
from ui.i18n import get_text


# ── Plotly chart builders ────────────────────────────────────────────────────

PLOTLY_COLORS = ["#007aff", "#34c759", "#ff9500", "#af52de", "#ff3b30"]


def _equity_curve_chart(results: list[BacktestResult]) -> go.Figure:
    """Line chart showing portfolio value over time for each strategy."""
    fig = go.Figure()
    for i, r in enumerate(results):
        years = sorted(r.yearly_values.keys())
        values = [r.yearly_values[y] for y in years]
        color = PLOTLY_COLORS[i % len(PLOTLY_COLORS)]
        fig.add_trace(go.Scatter(
            x=years, y=values,
            mode="lines+markers",
            name=r.strategy_name,
            line=dict(color=color, width=3),
            marker=dict(size=8),
            hovertemplate=(
                f"<b>{r.strategy_name}</b><br>"
                "Year: %{x}<br>RM %{y:,.2f}<extra></extra>"
            ),
        ))

    fig.update_layout(
        xaxis_title="Year",
        yaxis_title="Portfolio Value (RM)",
        yaxis_tickformat=",.0f",
        yaxis_tickprefix="RM ",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=450,
        margin=dict(l=60, r=20, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"),
    )
    return fig


def _annual_returns_bar_chart(result: BacktestResult) -> go.Figure:
    """Bar chart of each year's return — green for positive, red for negative."""
    years = sorted(result.yearly_values.keys())
    if len(years) < 2:
        return go.Figure()

    # Compute annual returns
    sorted_vals = [result.yearly_values[y] for y in years]
    annual_returns = []
    for idx in range(1, len(sorted_vals)):
        prev = sorted_vals[idx - 1]
        curr = sorted_vals[idx]
        if prev > 0:
            annual_returns.append(((curr - prev) / prev) * 100)
        else:
            annual_returns.append(0.0)
    bar_years = years[1:]  # first year has no return to compare

    colors = ["#34c759" if r >= 0 else "#ff3b30" for r in annual_returns]

    fig = go.Figure(go.Bar(
        x=bar_years,
        y=annual_returns,
        marker_color=colors,
        text=[f"{r:+.1f}%" for r in annual_returns],
        textposition="outside",
        hovertemplate="Year %{x}<br>Return: %{y:+.2f}%<extra></extra>",
    ))

    fig.update_layout(
        xaxis_title="Year",
        yaxis_title="Return (%)",
        yaxis_ticksuffix="%",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=380,
        margin=dict(l=60, r=20, t=40, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"),
    )
    return fig


# ── Insights generator ───────────────────────────────────────────────────────

def _generate_insights(results: list[BacktestResult]) -> str:
    """Generate a text summary of backtest results."""
    if not results:
        return ""

    lines = []

    # Best strategy by CAGR
    best = max(results, key=lambda r: r.cagr)
    lines.append(
        f"**The best strategy was {best.strategy_name}** with a CAGR of "
        f"{best.cagr:.2f}%."
    )

    # Compare each to 100% KWSP if present
    kwsp_result = next((r for r in results if "100% KWSP" in r.strategy_name), None)
    if kwsp_result:
        for r in results:
            if r is kwsp_result:
                continue
            diff = r.total_return_pct - kwsp_result.total_return_pct
            suffix = "more" if diff >= 0 else "less"
            lines.append(
                f"Compared to 100% KWSP, **{r.strategy_name}** returned "
                f"**{abs(diff):.1f}% {suffix}** over "
                f"{r.end_year - r.start_year + 1} years."
            )

    # Show final value for best strategy
    lines.append(
        f"Your RM {best.initial_capital:,.0f} grew to **RM {best.final_value:,.0f}** "
        f"with {best.strategy_name} "
        f"(total invested: RM {best.total_invested:,.0f})."
    )

    # Max drawdown warning
    worst_dd = min(results, key=lambda r: r.max_drawdown_pct)
    if worst_dd.max_drawdown_pct < -10:
        lines.append(
            f"⚠️ **{worst_dd.strategy_name}** had the largest drawdown at "
            f"{worst_dd.max_drawdown_pct:.1f}% — consider your risk tolerance."
        )

    return "\n\n".join(lines)


# ── Summary table builder ────────────────────────────────────────────────────

def _build_summary_df(results: list[BacktestResult]) -> pd.DataFrame:
    """Build the summary table DataFrame with 8 columns."""
    rows = []
    for r in results:
        rows.append({
            "Strategy": r.strategy_name,
            "Final Value (RM)": f"RM {r.final_value:,.0f}",
            "CAGR %": f"{r.cagr:.2f}%",
            "Total Return %": f"{r.total_return_pct:.1f}%",
            "Best Year %": f"{r.best_year_pct:.1f}%",
            "Worst Year %": f"{r.worst_year_pct:.1f}%",
            "Max Drawdown %": f"{r.max_drawdown_pct:.1f}%",
            "Sharpe Ratio": f"{r.sharpe_ratio:.2f}",
        })
    return pd.DataFrame(rows)


# ── Main render ──────────────────────────────────────────────────────────────

def render():
    """Render the full backtesting page: Part B + Part C."""
    try:
        _render_inner()
    except Exception as exc:
        st.error(f"**{get_text('error_generic')}**")
        with st.expander("Details"):
            st.exception(exc)


def _render_inner():
    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(f"# {get_text('backtesting_title')}")
    st.caption(get_text("backtesting_desc"))

    # ── Part B: Two-column layout ────────────────────────────────────────────
    col_left, col_right = st.columns([1, 2])

    # ── Left column: Controls ────────────────────────────────────────────────
    with col_left:
        st.subheader("Parameters")

        selected_strategies = st.multiselect(
            get_text("select_strategies_label"),
            options=list(PRESET_STRATEGIES.keys()),
            default=["100% KWSP", "Balanced (EPF + ASNB + Stocks)"],
        )

        start_year = st.number_input(
            get_text("backtest_start_year_label"),
            min_value=2010, max_value=2023, value=2015, step=1,
        )

        monthly_contribution = st.number_input(
            get_text("monthly_contribution_label"),
            min_value=0.0, value=500.0, step=100.0,
        )

        initial_capital = st.number_input(
            get_text("initial_capital_label"),
            min_value=0.0, value=10000.0, step=1000.0,
        )

        run_clicked = st.button(
            get_text("run_backtest_btn"),
            type="primary",
            use_container_width=True,
        )

    # ── Right column: Results ────────────────────────────────────────────────
    with col_right:
        if not run_clicked:
            st.info("👈 Select strategies and click **Run Backtest** to see results.")
            return

        # ── Validation ───────────────────────────────────────────────────────
        if not selected_strategies:
            st.warning(get_text("error_no_strategies"))
            return

        if initial_capital <= 0 and monthly_contribution <= 0:
            st.warning(get_text("error_no_capital"))
            return

        # ── Run backtest ─────────────────────────────────────────────────────
        end_year = datetime.date.today().year - 1

        backtester = Backtester()
        results = backtester.compare_strategies(
            strategies=selected_strategies,
            initial_capital=initial_capital,
            start_year=int(start_year),
            monthly_contribution=monthly_contribution,
        )

        if not results:
            st.warning("No results generated.")
            return

        # ── 1. Summary table ─────────────────────────────────────────────────
        st.subheader(get_text("strategy_stats_header"))
        summary_df = _build_summary_df(results)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        # ── 2. Equity curve chart ────────────────────────────────────────────
        st.subheader(get_text("performance_chart_header"))
        fig_equity = _equity_curve_chart(results)
        st.plotly_chart(fig_equity, use_container_width=True)

        # ── 3. Annual returns bar chart (best strategy) ──────────────────────
        best_result = max(results, key=lambda r: r.cagr)
        st.subheader(
            f"{get_text('annual_returns_chart_header')} — {best_result.strategy_name}"
        )
        fig_returns = _annual_returns_bar_chart(best_result)
        st.plotly_chart(fig_returns, use_container_width=True)

        # ── 4. Insights card ─────────────────────────────────────────────────
        st.subheader(get_text("insights_header"))
        insights_text = _generate_insights(results)
        st.markdown(insights_text)

        # ── 5. Year-by-year detail (collapsible) ────────────────────────────
        with st.expander(get_text("year_by_year_details_header")):
            for r in results:
                st.markdown(f"**{r.strategy_name}**")
                yoy_df = pd.DataFrame([
                    {"Year": yr, "Portfolio Value (RM)": f"RM {val:,.0f}"}
                    for yr, val in sorted(r.yearly_values.items())
                ])
                st.dataframe(yoy_df, use_container_width=True, hide_index=True)

    # ── Part C: PTPTN Payoff Calculator ──────────────────────────────────────
    st.divider()
    st.subheader(get_text("ptptn_calculator_title"))

    p1, p2, p3 = st.columns(3)
    with p1:
        ptptn_balance = st.number_input(
            get_text("ptptn_balance_label"),
            value=20000.0, min_value=0.0, step=1000.0,
        )
    with p2:
        ptptn_payment = st.number_input(
            get_text("ptptn_monthly_payment_label"),
            value=150.0, min_value=50.0, step=50.0,
        )
    with p3:
        ptptn_rate_choice = st.selectbox(
            get_text("ptptn_interest_rate_label"),
            options=["ICR (1% p.a.)", "Standard (3% p.a.)"],
        )
        ptptn_rate = 1.0 if "1%" in ptptn_rate_choice else 3.0

    if ptptn_balance > 0 and st.button(get_text("calculate_ptptn_btn")):
        backtester = Backtester()
        ptptn_result = backtester.calculate_ptptn_payoff(
            outstanding=ptptn_balance,
            monthly_payment=ptptn_payment,
            annual_rate=ptptn_rate,
        )

        # Summary metrics
        years_payoff = ptptn_result["months_to_payoff"] // 12
        months_payoff = ptptn_result["months_to_payoff"] % 12
        st.markdown(
            f"### You will pay off your PTPTN in **{years_payoff} years "
            f"and {months_payoff} months**"
        )

        m1, m2, m3 = st.columns(3)
        m1.metric(
            get_text("total_interest_paid_label"),
            f"RM {ptptn_result['total_interest']:,.2f}",
        )
        m2.metric(
            get_text("total_amount_paid_label"),
            f"RM {ptptn_result['total_paid']:,.2f}",
        )
        m3.metric(
            "Monthly Payment",
            f"RM {ptptn_payment:,.0f}",
        )

        # Amortization schedule
        st.subheader(get_text("amortization_schedule_header"))
        if ptptn_result["schedule"]:
            sched_df = pd.DataFrame(ptptn_result["schedule"])
            sched_df = sched_df.rename(columns={
                "month": "Month",
                "payment": "Payment (RM)",
                "principal": "Principal (RM)",
                "interest": "Interest (RM)",
                "balance": "Remaining Balance (RM)",
            })
            st.dataframe(sched_df, use_container_width=True, hide_index=True)

        # Tip: savings vs standard rate
        if ptptn_rate < 3.0:
            standard_result = backtester.calculate_ptptn_payoff(
                outstanding=ptptn_balance,
                monthly_payment=ptptn_payment,
                annual_rate=3.0,
            )
            savings = standard_result["total_interest"] - ptptn_result["total_interest"]
            st.info(
                f"💡 **{get_text('ptptn_tip_label')}**: By using ICR (1%) instead of "
                f"Standard (3%), you save **RM {savings:,.2f}** in interest payments!"
            )
