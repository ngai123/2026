"""Reusable Plotly chart builders."""
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import pandas as pd
from analysis.monte_carlo import MonteCarloResult


def monte_carlo_fan_chart(result: MonteCarloResult, title: str = "Wealth Projection") -> go.Figure:
    """Render a Monte Carlo fan chart with percentile bands."""
    x = result.years_array()

    fig = go.Figure()

    # 5th–95th shaded band
    fig.add_trace(go.Scatter(
        x=np.concatenate([x, x[::-1]]),
        y=np.concatenate([result.p95, result.p5[::-1]]),
        fill="toself",
        fillcolor="rgba(52, 199, 89, 0.05)",
        line=dict(color="rgba(255,255,255,0)"),
        name="5th–95th percentile",
        showlegend=True,
    ))

    # 25th–75th shaded band
    fig.add_trace(go.Scatter(
        x=np.concatenate([x, x[::-1]]),
        y=np.concatenate([result.p75, result.p25[::-1]]),
        fill="toself",
        fillcolor="rgba(52, 199, 89, 0.15)",
        line=dict(color="rgba(255,255,255,0)"),
        name="25th–75th percentile",
        showlegend=True,
    ))

    # Median line
    fig.add_trace(go.Scatter(
        x=x, y=result.p50,
        mode="lines",
        line=dict(color="#34c759", width=3),
        name="Median (50th percentile)",
    ))

    # Pessimistic line
    fig.add_trace(go.Scatter(
        x=x, y=result.p5,
        mode="lines",
        line=dict(color="#ff3b30", width=1.5, dash="dot"),
        name="Pessimistic (5th percentile)",
    ))

    # Optimistic line
    fig.add_trace(go.Scatter(
        x=x, y=result.p95,
        mode="lines",
        line=dict(color="#007aff", width=1.5, dash="dot"),
        name="Optimistic (95th percentile)",
    ))

    fig.update_layout(
        title=title,
        xaxis_title="Years from now",
        yaxis_title="Net Worth (RM)",
        yaxis_tickformat=",.0f",
        yaxis_tickprefix="RM ",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=480,
        margin=dict(l=60, r=20, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )
    return fig


def allocation_donut(categories: dict[str, float], title: str = "Asset Allocation") -> go.Figure:
    """Pie/donut chart for asset allocation by category."""
    labels = list(categories.keys())
    values = list(categories.values())

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.6,
        textinfo="percent", # Cleaner for iOS
        hovertemplate="<b>%{label}</b><br>RM %{value:,.2f}<br>%{percent}<extra></extra>",
        marker=dict(colors=["#007aff", "#34c759", "#ff9500", "#ff3b30", "#af52de", "#5856d6", "#ff2d55"])
    ))

    fig.update_layout(
        title=title,
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=400,
        showlegend=True,
        legend=dict(orientation="v", x=1.0, y=0.5),
        margin=dict(l=10, r=10, t=50, b=10),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )
    return fig


def net_worth_timeline(snapshots: list[dict]) -> go.Figure:
    """Line chart of net worth across historical snapshots."""
    if not snapshots:
        fig = go.Figure()
        fig.update_layout(title="No historical data yet", template="plotly_white", height=300)
        return fig

    dates = [s["created_at"][:10] for s in snapshots]
    values = [s["net_worth"] for s in snapshots]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=values,
        mode="lines+markers",
        line=dict(color="#007aff", width=3),
        marker=dict(size=12, color="#007aff", line=dict(width=3, color="white")),
        fill="tozeroy",
        fillcolor="rgba(0, 122, 255, 0.05)",
        name="Net Worth",
        hovertemplate="<b>%{x}</b><br>RM %{y:,.2f}<extra></extra>",
    ))

    fig.update_layout(
        title="Historical Net Worth Performance",
        xaxis_title="Timeline",
        yaxis_title="Net Worth (RM)",
        yaxis_tickformat=",.0f",
        yaxis_tickprefix="RM ",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=320,
        margin=dict(l=60, r=20, t=50, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )
    return fig


def backtest_comparison_chart(results: list, yearly_key: str = "yearly_values") -> go.Figure:
    """Compare multiple backtest strategies on one chart."""
    fig = go.Figure()
    # iOS Colors
    colors = ["#007aff", "#34c759", "#ff3b30", "#ff9500", "#af52de"]

    for i, r in enumerate(results):
        yv = r.yearly_values if hasattr(r, "yearly_values") else r.get("yearly_values", {})
        years = sorted(yv.keys())
        values = [yv[y] for y in years]
        color = colors[i % len(colors)]

        fig.add_trace(go.Scatter(
            x=years, y=values,
            mode="lines+markers",
            name=r.strategy_name if hasattr(r, "strategy_name") else r.get("strategy", f"Strategy {i+1}"),
            line=dict(color=color, width=3),
            marker=dict(size=8),
            hovertemplate="<b>%{fullData.name}</b><br>Year: %{x}<br>RM %{y:,.2f}<extra></extra>",
        ))

    fig.update_layout(
        title="Strategic Backtest Comparison",
        xaxis_title="Yearly Benchmark",
        yaxis_title="Portfolio Valuation (RM)",
        yaxis_tickformat=",.0f",
        yaxis_tickprefix="RM ",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=450,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )
    return fig


def health_score_gauge(score: float, grade: str, color: str) -> go.Figure:
    """Gauge chart for the financial health score."""
    color_map = {"green": "#34c759", "blue": "#007aff", "orange": "#ff9500", "red": "#ff3b30"}
    gauge_color = color_map.get(color, "#34c759")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": f"Grade: {grade}", "font": {"size": 20, "color": "#1c1c1e", "weight": "bold"}},
        number={"suffix": "/100", "font": {"size": 42, "color": "#1c1c1e", "weight": "bold"}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#8e8e93"},
            "bar": {"color": gauge_color, "thickness": 0.4},
            "bgcolor": "rgba(0,0,0,0.05)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 40],  "color": "rgba(255,59,48,0.05)"},
                {"range": [40, 60], "color": "rgba(255,149,0,0.05)"},
                {"range": [60, 80], "color": "rgba(0,122,255,0.05)"},
                {"range": [80, 100],"color": "rgba(52,199,89,0.05)"},
            ],
        },
    ))

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin=dict(l=40, r=40, t=60, b=40),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )
    return fig


def sensitivity_bar_chart(df: pd.DataFrame) -> go.Figure:
    """Bar chart comparing different monthly savings scenarios."""
    fig = go.Figure()

    cols = [c for c in df.columns if "Median" in c or "median" in c.lower()]
    if not cols:
        cols = [df.columns[1]]

    med_col = cols[0]
    savings_col = df.columns[0]

    fig.add_trace(go.Bar(
        x=df[savings_col].astype(str) + " RM/mo",
        y=df[med_col],
        marker_color="#007aff",
        text=["RM {:,.0f}".format(v) for v in df[med_col]],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Median outcome: RM %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title=f"Savings Impact Analysis ({med_col})",
        xaxis_title="Monthly Contributions",
        yaxis_title="Portfolio Projection (RM)",
        yaxis_tickformat=",.0f",
        yaxis_tickprefix="RM ",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=400,
        margin=dict(l=60, r=20, t=50, b=60),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )
    return fig
