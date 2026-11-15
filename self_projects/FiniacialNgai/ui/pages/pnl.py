"""P&L Statement — spreadsheet with current month editing + past months as read-only columns."""
from __future__ import annotations
from datetime import datetime
import streamlit as st
import pandas as pd
from database import repository as repo
from ui.export import export_button

_COMPARE_LABELS = ["Compare 1", "Compare 2", "Compare 3"]


# ── Categories ──────────────────────────────────────────────────────────────


DEFAULT_INCOME = [
    {"Detail": "Salary / Employment",   "Monthly Amount (RM)": 0.0},
    {"Detail": "Part-time / Freelance", "Monthly Amount (RM)": 0.0},
    {"Detail": "Investment Returns",    "Monthly Amount (RM)": 0.0},
    {"Detail": "Allowance / Gift",      "Monthly Amount (RM)": 0.0},
]

DEFAULT_EXPENSE = [
    {"Detail": "Housing / Rent",      "Monthly Amount (RM)": 0.0},
    {"Detail": "Food & Groceries",    "Monthly Amount (RM)": 0.0},
    {"Detail": "Transport",           "Monthly Amount (RM)": 0.0},
    {"Detail": "Utilities & Phone",   "Monthly Amount (RM)": 0.0},
    {"Detail": "Entertainment",       "Monthly Amount (RM)": 0.0},
    {"Detail": "Education",           "Monthly Amount (RM)": 0.0},
    {"Detail": "Insurance / Takaful", "Monthly Amount (RM)": 0.0},
    {"Detail": "Loan Repayment",      "Monthly Amount (RM)": 0.0},
]


def _period_label(p: str) -> str:
    try:
        return datetime.strptime(p, "%Y-%m").strftime("%b %Y")
    except Exception:
        return p


def _items_to_income_df(items: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Detail":              r.get("description") or r.get("category", ""),
        "Monthly Amount (RM)": float(r["amount"]),
    } for r in items])


def _items_to_expense_df(items: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Detail":              r.get("description") or r.get("category", ""),
        "Monthly Amount (RM)": float(r["amount"]),
    } for r in items])


def _load_latest() -> tuple[pd.DataFrame, pd.DataFrame]:
    pnl_id = repo.get_latest_pnl_id()
    if not pnl_id:
        return pd.DataFrame(DEFAULT_INCOME), pd.DataFrame(DEFAULT_EXPENSE)
    data = repo.get_pnl(pnl_id)
    inc = _items_to_income_df(data["income_items"])  if data["income_items"]  else pd.DataFrame(DEFAULT_INCOME)
    exp = _items_to_expense_df(data["expense_items"]) if data["expense_items"] else pd.DataFrame(DEFAULT_EXPENSE)
    return inc, exp



def _build_merged(main_df: pd.DataFrame, past_periods: list[str], item_type: str) -> tuple[pd.DataFrame, list[str]]:
    """Merge ALL items from main month + all comparison months into one table.
    Each unique Detail becomes a row; each month is a column."""
    # Main month items
    main_items: dict[str, float] = {}
    for _, row in main_df.iterrows():
        key = str(row.get("Detail", "") or "").strip()
        if key:
            main_items[key] = float(row.get("Monthly Amount (RM)", 0) or 0)

    # Past months items
    past_labels: list[str] = []
    past_items: dict[str, dict[str, float]] = {}
    for p in past_periods:
        pnl = repo.get_pnl_by_period(p)
        if not pnl:
            continue
        lbl = _period_label(p)
        past_labels.append(lbl)
        totals: dict[str, float] = {}
        for item in pnl.get(f"{item_type}_items", []):
            k = item.get("description") or item.get("category", "")
            if k:
                totals[k] = totals.get(k, 0.0) + float(item.get("amount", 0))
        past_items[lbl] = totals

    # Union of all Detail names (main first, then past)
    all_details: list[str] = list(main_items.keys())
    for lbl in past_labels:
        for d in past_items[lbl]:
            if d not in all_details:
                all_details.append(d)

    rows = []
    for detail in all_details:
        row: dict = {
            "Detail": detail,
            "Monthly Amount (RM)": main_items.get(detail, 0.0),
        }
        for lbl in past_labels:
            row[lbl] = past_items[lbl].get(detail, 0.0)
        rows.append(row)

    if not rows:
        df = pd.DataFrame({"Detail": pd.Series(dtype=str), "Monthly Amount (RM)": pd.Series(dtype=float)})
        for lbl in past_labels:
            df[lbl] = pd.Series(dtype=float)
        return df, past_labels

    return pd.DataFrame(rows), past_labels


def _load_period(period: str) -> None:
    data = repo.get_pnl_by_period(period)
    if not data:
        return
    inc_rows = data.get("income_items", [])
    exp_rows = data.get("expense_items", [])
    st.session_state["pnl_income_df"]  = _items_to_income_df(inc_rows)  if inc_rows  else pd.DataFrame(DEFAULT_INCOME)
    st.session_state["pnl_expense_df"] = _items_to_expense_df(exp_rows) if exp_rows  else pd.DataFrame(DEFAULT_EXPENSE)
    st.session_state["pnl_period"]     = period
    # Bump counter so data_editor always gets a fresh key (avoids stale cached state)
    st.session_state["_pnl_v"] = st.session_state.get("_pnl_v", 0) + 1


_SAVE_DOT_CSS = """
<style>
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2):last-child button {
    border-radius: 50% !important;
    width: 26px !important;
    height: 26px !important;
    min-height: 26px !important;
    min-width: 26px !important;
    padding: 0 !important;
    line-height: 1 !important;
    font-size: 11px !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2):last-child button[data-testid*="secondary"] {
    background: #c7c7cc !important;
    border-color: #c7c7cc !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2):last-child button[data-testid*="secondary"] p {
    color: white !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2):last-child button[data-testid*="primary"] {
    background: #34c759 !important;
    border-color: #34c759 !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2):last-child button[data-testid*="primary"] p {
    color: white !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2):last-child p.save-dot-label {
    font-size: 0.65rem !important;
    color: #86868b !important;
    text-align: center !important;
    margin-top: 2px !important;
    line-height: 1 !important;
}
</style>
"""


def render():
    st.markdown(_SAVE_DOT_CSS, unsafe_allow_html=True)

    all_saved = repo.list_pnl_periods()

    # ── Process pending load BEFORE any widgets ──────────────────────────────
    _pending = st.session_state.pop("_pnl_pending_load", None)
    if _pending:
        _load_period(_pending)

    # ── Init: load latest saved month if nothing loaded yet ──────────────────
    if "pnl_income_df" not in st.session_state or "pnl_expense_df" not in st.session_state:
        if all_saved:
            _load_period(all_saved[0])
        else:
            inc, exp = _load_latest()
            st.session_state["pnl_income_df"]  = inc
            st.session_state["pnl_expense_df"] = exp

    period = st.session_state.get("pnl_period", all_saved[0] if all_saved else datetime.now().strftime("%Y-%m"))

    # ── Title + save dot ──────────────────────────────────────────────────
    _pnl_is_saved = repo.get_pnl_by_period(period) is not None
    _ptitle_col, _pdot_col = st.columns([25, 2])
    with _ptitle_col:
        st.markdown("# P&L Statement")
    with _pdot_col:
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        if st.button("●", key="pnl_save_dot",
                     type="primary" if _pnl_is_saved else "secondary",
                     help="Saved — click to re-save" if _pnl_is_saved else "Not saved — click to save"):
            st.session_state["_pnl_pending_save"] = True
    st.divider()
    other_saved = ["—"] + [p for p in all_saved if p != period]
    _auto       = [p for p in all_saved if p != period]

    # ── 4 column pickers (main + 3 comparison) ───────────────────────────────
    st.markdown("**Select months**")
    cp0, cp1, cp2, cp3 = st.columns(4)

    with cp0:
        main_opts = all_saved if all_saved else [period]
        main_default = period if period in main_opts else main_opts[0]
        main_sel = st.selectbox(
            "Main Month",
            options=main_opts,
            index=main_opts.index(main_default),
            format_func=_period_label,
            label_visibility="visible",
        )
        if main_sel and main_sel != period:
            st.session_state["_pnl_pending_load"] = main_sel
            st.rerun()

    # Use plain session_state keys (never deleted by Streamlit, unlike widget keys)
    _SEL_KEYS = ["_pnl_sel_c1", "_pnl_sel_c2", "_pnl_sel_c3"]

    def _mk_col_picker(col, slot_idx):
        store = _SEL_KEYS[slot_idx]
        with col:
            saved = st.session_state.get(store)
            if saved in other_saved:
                default = saved
            else:
                default = _auto[slot_idx] if slot_idx < len(_auto) else "—"
                if default not in other_saved:
                    default = "—"
            val = st.selectbox(
                _COMPARE_LABELS[slot_idx],
                options=other_saved,
                index=other_saved.index(default),
                format_func=lambda p: "None" if p == "—" else _period_label(p),
                label_visibility="visible",
            )
            st.session_state[store] = val  # non-widget key — survives page navigation
            return val

    sel1 = _mk_col_picker(cp1, 0)
    sel2 = _mk_col_picker(cp2, 1)
    sel3 = _mk_col_picker(cp3, 2)
    chosen_past = [s for s in [sel1, sel2, sel3] if s and s != "—"]

    # Fetch actual totals from DB for each comparison period (correct, not row-matched)
    def _db_totals(p: str) -> tuple[float, float]:
        data = repo.get_pnl_by_period(p)
        if not data:
            return 0.0, 0.0
        return float(data.get("total_income", 0) or 0), float(data.get("total_expense", 0) or 0)

    past_db_totals = [_db_totals(p) for p in chosen_past]

    _v = st.session_state.get("_pnl_v", 0)

    # ── INCOME spreadsheet ───────────────────────────────────────────────────
    st.subheader("Income")
    wide_inc, inc_past_labels = _build_merged(
        st.session_state["pnl_income_df"], chosen_past, "income"
    )
    inc_cfg: dict = {
        "Detail": st.column_config.TextColumn("Detail", width="large"),
        "Monthly Amount (RM)": st.column_config.NumberColumn(
            label=_period_label(period),
            min_value=0.0, format="RM %.2f", width="small",
        ),
    }
    for i, lbl in enumerate(inc_past_labels):
        inc_cfg[lbl] = st.column_config.NumberColumn(
            label=lbl, format="RM %.0f",
        )
    inc_edited_wide = st.data_editor(
        wide_inc, use_container_width=True, num_rows="dynamic", hide_index=True,
        column_config=inc_cfg, disabled=inc_past_labels,
        key=f"pnl_income_editor_{_v}",
    )
    income_df = inc_edited_wide.drop(columns=inc_past_labels, errors="ignore")
    st.session_state["pnl_income_df"] = income_df

    total_income = float(income_df["Monthly Amount (RM)"].fillna(0).sum())
    _months  = [period] + chosen_past
    _inc_vals = [total_income] + [t[0] for t in past_db_totals]

    st.divider()

    # ── EXPENSE spreadsheet ──────────────────────────────────────────────────
    st.subheader("Expenses")
    wide_exp, exp_past_labels = _build_merged(
        st.session_state["pnl_expense_df"], chosen_past, "expense"
    )
    exp_cfg: dict = {
        "Detail": st.column_config.TextColumn("Detail", width="large"),
        "Monthly Amount (RM)": st.column_config.NumberColumn(
            label=_period_label(period),
            min_value=0.0, format="RM %.2f", width="small",
        ),
    }
    for i, lbl in enumerate(exp_past_labels):
        exp_cfg[lbl] = st.column_config.NumberColumn(
            label=lbl, format="RM %.0f",
        )
    exp_edited_wide = st.data_editor(
        wide_exp, use_container_width=True, num_rows="dynamic", hide_index=True,
        column_config=exp_cfg, disabled=exp_past_labels,
        key=f"pnl_expense_editor_{_v}",
    )
    expense_df = exp_edited_wide.drop(columns=exp_past_labels, errors="ignore")
    st.session_state["pnl_expense_df"] = expense_df

    total_expense = float(expense_df["Monthly Amount (RM)"].fillna(0).sum())
    _exp_vals = [total_expense] + [t[1] for t in past_db_totals]

    # ── Summary table ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Summary")
    _period_headers = [_period_label(p) for p in _months]
    _net_vals  = [i - e for i, e in zip(_inc_vals, _exp_vals)]
    _rate_vals = [
        f"{(n / i * 100):.1f}%" if i else "—"
        for n, i in zip(_net_vals, _inc_vals)
    ]
    summary_df = pd.DataFrame(
        {
            "": ["Income", "Expenses", "Net Savings", "Savings Rate"],
            **{
                hdr: [
                    f"RM {inc:,.2f}",
                    f"RM {exp:,.2f}",
                    f"RM {net:,.2f}",
                    rate,
                ]
                for hdr, inc, exp, net, rate in zip(
                    _period_headers, _inc_vals, _exp_vals, _net_vals, _rate_vals
                )
            },
        }
    ).set_index("")
    st.dataframe(summary_df, use_container_width=True)

    # ── Execute pending save (deferred until income_df / expense_df are ready) ──
    if st.session_state.pop("_pnl_pending_save", False):
        income_items = [
            {"description": str(r.get("Detail", "") or ""), "category": "Other",
             "amount": float(r.get("Monthly Amount (RM)", 0) or 0)}
            for _, r in income_df.iterrows()
            if str(r.get("Detail", "") or "").strip()
        ]
        expense_items = [
            {"description": str(r.get("Detail", "") or ""), "category": "Other",
             "amount": float(r.get("Monthly Amount (RM)", 0) or 0)}
            for _, r in expense_df.iterrows()
            if str(r.get("Detail", "") or "").strip()
        ]
        repo.save_pnl(label="P&L", income_items=income_items,
                      expense_items=expense_items, period=period)
        st.rerun()

    # ── Export ────────────────────────────────────────────────────────────────
    export_button(
        data={
            "page":   "pnl",
            "period": period,
            "income": [
                {"detail": str(r.get("Detail", "")),
                 "amount": float(r.get("Monthly Amount (RM)", 0) or 0)}
                for _, r in income_df.iterrows()
            ],
            "expenses": [
                {"detail": str(r.get("Detail", "")),
                 "amount": float(r.get("Monthly Amount (RM)", 0) or 0)}
                for _, r in expense_df.iterrows()
            ],
            "summary": {
                "total_income":   round(_inc_vals[0], 2),
                "total_expenses": round(_exp_vals[0], 2),
                "net_savings":    round(_net_vals[0], 2),
                "savings_rate":   _rate_vals[0],
            },
        },
        prefix="pnl",
    )

