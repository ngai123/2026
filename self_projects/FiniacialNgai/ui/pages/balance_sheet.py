"""
Balance Sheet — pure spreadsheet.
Only shows Asset name + month balances. Metadata (category, etc.) stored silently.
4 colour-coded month columns: blue (current), green, amber, rose (past).
"""
from __future__ import annotations
from datetime import datetime
import streamlit as st
import pandas as pd
from models.balance_sheet import AssetCategory
from database import repository as repo
from ui.export import export_button
from ui.i18n import get_text

_COMPARE_LABELS = ["Compare 1", "Compare 2", "Compare 3"]

# ── Internal metadata columns (stored but NOT displayed) ────────────────────
META_COLS = ["Category", "Institution", "Ticker", "Is Debt?", "Custom Return % p.a."]
CATEGORIES = [c.value for c in AssetCategory]

DEFAULT_ROWS = [
    ("Ryt Bank Savings Account", "Savings & Fixed Deposits",   3274.00, "Ryt Bank",  "",      False, 0.0),
    ("Cash",                     "Liquid / Cash",                 86.00, "",          "",      False, 0.0),
    ("PTPTN Simpanan",           "Education Savings",             21.00, "PTPTN",     "",      False, 0.0),
    ("TNG",                      "Liquid / Cash",               2166.00, "TNG",       "",      False, 0.0),
    ("Gold",                     "Gold & Precious Metals",       901.00, "",          "GC=F",  False, 0.0),
    ("MooMoo",                   "Stocks & Equities",           4282.00, "MooMoo",    "",      False, 0.0),
    ("Maybank Fixed Deposit",    "Savings & Fixed Deposits",       0.00, "Maybank",   "",      False, 0.0),
    ("Maybank Saving",           "Savings & Fixed Deposits",   11534.00, "Maybank",   "",      False, 0.0),
    ("RHB",                      "Savings & Fixed Deposits",       1.00, "RHB",       "",      False, 0.0),
    ("ASNB Ria",                 "Unit Trusts & Mutual Funds",  2480.00, "ASNB",      "",      False, 0.0),
    ("ASNB Mutual Funds",        "Unit Trusts & Mutual Funds",  2709.00, "ASNB",      "",      False, 0.0),
    ("KWSP",                     "Retirement (EPF/KWSP)",       4696.00, "KWSP",      "",      False, 0.0),
    ("LUNO",                     "Cryptocurrency",              1896.00, "LUNO",      "BTC",   False, 0.0),
    ("Principal Retire",         "Unit Trusts & Mutual Funds",   105.00, "Principal", "",      False, 0.0),
    ("Principal Save",           "Unit Trusts & Mutual Funds",   654.00, "Principal", "",      False, 0.0),
    ("PTPTN Loan",               "Liabilities / Loans",         9979.00, "PTPTN",     "",      True,  0.0),
    ("姨姨 (Personal Loan)",      "Liabilities / Loans",        15550.00, "",          "",      True,  0.0),
]


def _period_label(p: str) -> str:
    try:
        return datetime.strptime(p, "%Y-%m").strftime("%b %Y")
    except Exception:
        return p


def _default_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "Asset / Investment":   name,
        "Category":             cat,
        "Balance (RM)":         bal,
        "Institution":          inst,
        "Ticker":               ticker,
        "Is Debt?":             is_debt,
        "Custom Return % p.a.": ret,
    } for name, cat, bal, inst, ticker, is_debt, ret in DEFAULT_ROWS])


def _load_from_db() -> pd.DataFrame:
    latest_id = repo.get_latest_snapshot_id()
    if not latest_id:
        return _default_df()
    assets = repo.get_snapshot_assets(latest_id)
    return pd.DataFrame([{
        "Asset / Investment":   a["name"],
        "Category":             a["category"],
        "Balance (RM)":         float(a["balance"]),
        "Institution":          a.get("institution", ""),
        "Ticker":               a.get("ticker", ""),
        "Is Debt?":             bool(a["is_liability"]),
        "Custom Return % p.a.": float(a.get("annual_return_pct") or 0.0),
    } for a in assets])


def _load_snap_into_editor(snap: dict) -> None:
    assets_data = repo.get_snapshot_assets(snap["id"])
    st.session_state["sheet_df"] = pd.DataFrame([{
        "Asset / Investment":   a["name"],
        "Category":             a["category"],
        "Balance (RM)":         float(a["balance"]),
        "Institution":          a.get("institution", ""),
        "Ticker":               a.get("ticker", ""),
        "Is Debt?":             bool(a["is_liability"]),
        "Custom Return % p.a.": float(a.get("annual_return_pct") or 0.0),
    } for a in assets_data])
    st.session_state["bs_period"]       = snap["period"]
    st.session_state["bs_period_input"] = snap["period"]   # sync the text-input widget
    st.session_state["snap_label"]      = snap.get("label", "Portfolio")


def _category_to_key(cat: str) -> str:
    return {
        "Liquid / Cash":              "CASH",
        "Savings & Fixed Deposits":   "MAYBANK_SAVINGS",
        "Retirement (EPF/KWSP)":      "KWSP_EPF",
        "Unit Trusts & Mutual Funds": "UNIT_TRUST",
        "Stocks & Equities":          "MOOMOO_STOCKS",
        "Cryptocurrency":             "LUNO_CRYPTO",
        "Gold & Precious Metals":     "GOLD",
        "Real Estate / Property":     "CUSTOM",
        "Bonds & Fixed Income":       "MAYBANK_FD",
        "Education Savings":          "PTPTN_SAVINGS",
        "Insurance / Takaful":        "CUSTOM",
        "Investments":                "CUSTOM",
        "Other Assets":               "CUSTOM",
        "Liabilities / Loans":        "PTPTN_LOAN",
    }.get(cat, "CUSTOM")


def _df_to_asset_list(df: pd.DataFrame) -> list[dict]:
    assets = []
    for _, row in df.iterrows():
        name = str(row.get("Asset / Investment", "") or "").strip()
        if not name:
            continue
        category = str(row.get("Category", "") or "Other Assets") or "Other Assets"
        ret = float(row.get("Custom Return % p.a.", 0) or 0)
        assets.append({
            "name":              name,
            "category":          category,
            "asset_key":         _category_to_key(category),
            "institution":       str(row.get("Institution", "") or ""),
            "balance":           float(row.get("Balance (RM)", 0) or 0),
            "currency":          "MYR",
            "is_liability":      bool(row.get("Is Debt?", False) or False),
            "annual_return_pct": ret if ret > 0 else None,
            "quantity":          None,
            "ticker":            str(row.get("Ticker", "") or ""),
            "notes":             "",
        })
    return assets


# ── CSS: inject column-header colours via nth-child selectors ────────────────
# data_editor thead th cells: col 1 = asset name, col 2 = current (blue),
# col 3 = green, col 4 = amber, col 5 = rose
_HEADER_CSS = """
<style>
/* ── Circular save-indicator button ────────────────────────────────── */
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
    color: white !important;
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

/* Balance-sheet column colour bands — header + all data cells */

/* Col 2 — current month — blue */
[role="columnheader"][aria-colindex="2"],
[role="gridcell"][aria-colindex="2"] {
    background: #dbeafe !important;
    color: #1e40af !important;
}
/* Col 3 — most recent past — green */
[role="columnheader"][aria-colindex="3"],
[role="gridcell"][aria-colindex="3"] {
    background: #dcfce7 !important;
    color: #166534 !important;
}
/* Col 4 — older — amber */
[role="columnheader"][aria-colindex="4"],
[role="gridcell"][aria-colindex="4"] {
    background: #fef9c3 !important;
    color: #854d0e !important;
}
/* Col 5 — oldest — rose */
[role="columnheader"][aria-colindex="5"],
[role="gridcell"][aria-colindex="5"] {
    background: #ffe4e6 !important;
    color: #9f1239 !important;
}
</style>
"""


def render():
    st.markdown(_HEADER_CSS, unsafe_allow_html=True)

    unit = get_text("unit")

    # ── Init ──────────────────────────────────────────────────────────────
    if "sheet_df" not in st.session_state:
        st.session_state["sheet_df"] = _load_from_db()

    # ── Process pending period load BEFORE any widgets are created ────────
    from datetime import datetime as _dt
    _pending = st.session_state.pop("_bs_pending_load", None)
    if _pending:
        snap = repo.get_snapshot_by_period(_pending)
        if snap:
            _load_snap_into_editor(snap)

    # Keep period and label in session state with defaults
    period = st.session_state.get("bs_period", _dt.now().strftime("%Y-%m"))
    label  = st.session_state.get("snap_label", "Portfolio")

    # ── Title + save dot ──────────────────────────────────────────────────
    _is_saved = repo.get_snapshot_by_period(period) is not None
    _title_col, _dot_col = st.columns([25, 2])
    with _title_col:
        st.markdown(f"# {get_text('balance_sheet_title')}")
    with _dot_col:
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        if st.button("●", key="bs_save_dot",
                     type="primary" if _is_saved else "secondary",
                     help="Saved — click to re-save" if _is_saved else "Not saved — click to save"):
            st.session_state["_bs_pending_save"] = True
    st.divider()

    # ── Build wide dataframe: current + past month balance columns ─────────
    current_period = st.session_state.get("bs_period", _dt.now().strftime("%Y-%m"))
    all_saved = repo.list_snapshot_periods()
    other_saved = ["—"] + [p for p in all_saved if p != current_period]

    _auto = [p for p in all_saved if p != current_period]

    # ── Column month pickers ──────────────────────────────────────────────
    st.markdown("**Comparison columns**")
    cp1, cp2, cp3 = st.columns(3)
    _SEL_KEYS = ["_bs_sel_c1", "_bs_sel_c2", "_bs_sel_c3"]

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
            st.session_state[store] = val
            return val
    sel1 = _mk_col_picker(cp1, 0)
    sel2 = _mk_col_picker(cp2, 1)
    sel3 = _mk_col_picker(cp3, 2)
    chosen_past = [s for s in [sel1, sel2, sel3] if s and s != "—"]

    # ── Build past-month lookup once ──────────────────────────────────────
    past_data: list[tuple[str, dict]] = []
    for p in chosen_past:
        snap = repo.get_snapshot_by_period(p)
        if snap:
            lbl = _period_label(p)
            if any(l == lbl for l, _ in past_data):
                continue
            bals = {a["name"]: float(a["balance"]) for a in repo.get_snapshot_assets(snap["id"])}
            past_data.append((lbl, bals))
    past_col_labels = [lbl for lbl, _ in past_data]

    # ── Shared column config ──────────────────────────────────────────────
    col_cfg: dict = {
        "Asset / Investment": st.column_config.TextColumn("Asset / Investment", width="medium"),
        "Balance (RM)": st.column_config.NumberColumn(
            label=_period_label(current_period),
            min_value=0.0, format="RM %.2f", width="medium",
        ),
    }
    for lbl, _ in past_data:
        col_cfg[lbl] = st.column_config.NumberColumn(
            label=lbl, format="RM %.0f", width="medium",
        )
    visible_cols = ["Asset / Investment", "Balance (RM)"] + past_col_labels

    def _build_wide(base: pd.DataFrame) -> pd.DataFrame:
        wide = base.copy()
        for lbl, bals in past_data:
            wide[lbl] = wide["Asset / Investment"].apply(
                lambda n, b=bals: b.get(str(n).strip(), 0.0)
            )
        return wide

    all_df    = st.session_state["sheet_df"].copy()
    debt_mask = all_df["Is Debt?"].fillna(False).astype(bool)
    assets_base = all_df[~debt_mask].reset_index(drop=True)
    liab_base   = all_df[debt_mask].reset_index(drop=True)

    # ── ASSETS ───────────────────────────────────────────────────────────
    st.subheader("Assets")

    wide_assets_df = _build_wide(assets_base)
    edited_assets_wide = st.data_editor(
        wide_assets_df,
        use_container_width=True, num_rows="dynamic", hide_index=True,
        column_config=col_cfg, column_order=visible_cols, disabled=past_col_labels,
        key=f"bs_assets_{current_period}", height=300,
    )
    edited_assets = edited_assets_wide.drop(columns=past_col_labels, errors="ignore")
    edited_assets["Is Debt?"] = False

    assets_total = float(edited_assets["Balance (RM)"].fillna(0).sum())
    _period_headers = [_period_label(current_period)] + list(past_col_labels)
    _assets_vals = [assets_total] + [
        float(wide_assets_df[lbl].fillna(0).sum()) for lbl in past_col_labels
    ]

    st.divider()

    # ── LIABILITIES ───────────────────────────────────────────────────────
    st.subheader("Liabilities")

    wide_liab_df = _build_wide(liab_base)
    edited_liab_wide = st.data_editor(
        wide_liab_df,
        use_container_width=True, num_rows="dynamic", hide_index=True,
        column_config=col_cfg, column_order=visible_cols, disabled=past_col_labels,
        key=f"bs_liab_{current_period}", height=200,
    )
    edited_liab = edited_liab_wide.drop(columns=past_col_labels, errors="ignore")
    edited_liab["Is Debt?"] = True

    liab_total = float(edited_liab["Balance (RM)"].fillna(0).sum())
    _liab_vals = [liab_total] + [
        float(wide_liab_df[lbl].fillna(0).sum()) for lbl in past_col_labels
    ]
    _equity_vals = [a - l for a, l in zip(_assets_vals, _liab_vals)]
    net_worth = _equity_vals[0]

    st.divider()

    # ── SUMMARY TABLE ─────────────────────────────────────────────────────
    st.subheader("Summary")
    summary_df = pd.DataFrame(
        {
            "": ["Total Assets", "Total Liabilities", "Net Worth"],
            **{
                hdr: [f"RM {a:,.2f}", f"RM {l:,.2f}", f"RM {e:,.2f}"]
                for hdr, a, l, e in zip(_period_headers, _assets_vals, _liab_vals, _equity_vals)
            },
        }
    ).set_index("")
    st.dataframe(summary_df, use_container_width=True)

    # Merge back into session state
    combined_df = pd.concat([edited_assets, edited_liab], ignore_index=True)
    st.session_state["sheet_df"] = combined_df

    # ── Execute pending save (deferred until combined_df is ready) ────────
    if st.session_state.pop("_bs_pending_save", False):
        repo.save_snapshot(label=label, assets=_df_to_asset_list(combined_df), period=period)
        st.rerun()

    # ── Export ────────────────────────────────────────────────────────────────
    export_button(
        data={
            "page":       "balance_sheet",
            "period":     current_period,
            "label":      label,
            "assets": [
                {
                    "name":       row["Asset / Investment"],
                    "category":   row.get("Category", ""),
                    "balance":    float(row["Balance (RM)"] or 0),
                    "institution":row.get("Institution", ""),
                    "is_debt":    bool(row.get("Is Debt?", False)),
                }
                for _, row in combined_df.iterrows()
            ],
            "summary": {
                "total_assets":      round(_assets_vals[0], 2),
                "total_liabilities": round(_liab_vals[0], 2),
                "net_worth":         round(_equity_vals[0], 2),
            },
        },
        prefix="balance_sheet",
    )

