"""Monte Carlo wealth projection page."""
import streamlit as st
from database import repository as repo
from analysis.monte_carlo import MonteCarloEngine
from ui.components.charts import monte_carlo_fan_chart, sensitivity_bar_chart
import config


from ui.i18n import get_text


def render():
    st.markdown(f"# {get_text('projections_title')}")
    st.caption(get_text('projections_desc'))

    latest_id = repo.get_latest_snapshot_id()
    if not latest_id:
        st.warning(get_text("go_to_balance_sheet"))
        return

    snapshot = repo.get_snapshot(latest_id)
    assets = [a for a in repo.get_snapshot_assets(latest_id) if not a["is_liability"]]

    # ── Controls ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.subheader(get_text("projection_params_header"))
        years = st.slider(get_text("years_to_project_label"), 1, 40, 20)
        monthly_contrib = st.number_input(
            get_text("monthly_savings"),
            value=float(max(0, snapshot.get("monthly_income", 0) - snapshot.get("monthly_expense", 0))),
            min_value=0.0, step=100.0,
        )
        inflation_adjust = st.checkbox("Inflation-adjusted (Real Terms)", value=True)
        n_sims = st.select_slider(
            "Confidence Precision",
            options=[1_000, 5_000, 10_000],
            value=10_000,
            format_func=lambda x: f"{x:,} Scenarios",
        )

    monthly_expense = snapshot.get("monthly_expense", 0)
    fire_number = monthly_expense * 12 * config.FIRE_MULTIPLE if monthly_expense > 0 else 0

    # ── Run simulation ─────────────────────────────────────────────────────
    with st.spinner("Analyzing simulation paths..."):
        engine = MonteCarloEngine(n_simulations=n_sims)
        result = engine.run(
            assets=assets,
            years=years,
            monthly_contribution=monthly_contrib,
            fire_number=fire_number,
            inflation_adjust=inflation_adjust,
        )

    # ── Key metrics ────────────────────────────────────────────────────────
    adj_label = "(Adjusted for Inflation)" if inflation_adjust else "(Nominal)"
    st.subheader(f"Projection Summary - {years} Year Horizon {adj_label}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(get_text("median_outcome_label"), f"RM {result.final_p50:,.0f}")
    m2.metric(get_text("optimistic_95th_label"), f"RM {result.final_p95:,.0f}")
    m3.metric(get_text("pessimistic_5th_label"), f"RM {result.final_p5:,.0f}")
    m4.metric(get_text("prob_doubling_label"), f"{result.prob_double*100:.1f}%")

    if fire_number > 0:
        st.info(
            f"**{get_text('fire_number_label')}:** RM {fire_number:,.0f}  |  "
            f"{get_text('prob_fire_label')} ({years}y): **{result.prob_fire*100:.1f}%**"
        )

    # ── Fan chart ─────────────────────────────────────────────────────────
    title = f"{get_text('projections_title')} — {years} Years"
    fig = monte_carlo_fan_chart(result, title=title)
    st.plotly_chart(fig, width="stretch")

    # ── Milestones ────────────────────────────────────────────────────────
    st.subheader(get_text("milestone_tracker_label"))
    milestone_cols = st.columns(len(result.milestones))
    for col, (label, yr) in zip(milestone_cols, result.milestones.items()):
        if yr == 0.0:
            col.metric(label, get_text("milestone_already_reached"))
        elif yr is None:
            col.metric(label, get_text("milestone_not_reached"))
        else:
            col.metric(label, f"{yr:.1f} Years")

    st.divider()

    # ── Sensitivity Analysis ──────────────────────────────────────────────
    st.subheader(get_text("what_if_save_more_label"))
    st.caption(get_text("sensitivity_analysis_desc"))

    with st.spinner("Calculating sensitivity matrix..."):
        df = engine.sensitivity_analysis(
            assets=assets,
            years=years,
            monthly_contributions=[0, 200, 500, 1000, 2000, 3000],
        )

    fig_sens = sensitivity_bar_chart(df)
    st.plotly_chart(fig_sens, width="stretch")

    with st.expander("Detailed Sensitivity Data"):
        st.dataframe(df, width="stretch", hide_index=True)

    st.divider()

    # ── Scenario Comparison ───────────────────────────────────────────────
    st.subheader(get_text("scenario_comparison_label"))
    scenarios = [
        {"name": get_text("current_pace_scenario"),    "monthly_contribution": monthly_contrib,       "years": years},
        {"name": "+RM 500/month",   "monthly_contribution": monthly_contrib + 500,  "years": years},
        {"name": "+RM 1,000/month", "monthly_contribution": monthly_contrib + 1000, "years": years},
    ]
    with st.spinner("Processing comparative scenarios..."):
        scenario_results = engine.run_scenario_comparison(assets, scenarios)

    import pandas as pd
    scen_df = pd.DataFrame(scenario_results)
    scen_df = scen_df.rename(columns={
        "scenario": "Scenario Strategy",
        "monthly_contribution": "Monthly Savings (RM)",
        "median_final": "Median Outcome (RM)",
        "p5_final": "Pessimistic (RM)",
        "p95_final": "Optimistic (RM)",
        "prob_double": "Prob. Capital Doubling",
    })
    for col in ["Median Outcome (RM)", "Pessimistic (RM)", "Optimistic (RM)"]:
        scen_df[col] = scen_df[col].apply(lambda x: f"RM {x:,.0f}")
    scen_df["Prob. Capital Doubling"] = scen_df["Prob. Capital Doubling"].apply(lambda x: f"{x*100:.1f}%")
    st.dataframe(scen_df[["Scenario Strategy", "Monthly Savings (RM)", "Median Outcome (RM)",
                            "Pessimistic (RM)", "Optimistic (RM)", "Prob. Capital Doubling"]],
                 width="stretch", hide_index=True)
