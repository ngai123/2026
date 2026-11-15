"""Settings page — API key, data refresh, snapshot management, CSV export."""
import streamlit as st
import pandas as pd
from database import repository as repo
from config import ANTHROPIC_API_KEY


from ui.i18n import get_text


def render():
    st.markdown(f"# {get_text('settings_title')}")

    # ── API Key ────────────────────────────────────────────────────────────
    st.subheader(get_text("api_configuration_header"))
    current_key = st.session_state.get("api_key", ANTHROPIC_API_KEY)
    masked = f"sk-ant-...{current_key[-8:]}" if current_key and len(current_key) > 12 else "Not set"

    st.info(f"Active Key: `{masked}`")
    new_key = st.text_input(
        get_text("api_key_label"),
        type="password",
        placeholder="sk-ant-api03-...",
        help=get_text("api_key_help"),
    )
    if st.button(get_text("save_settings_btn")) and new_key:
        st.session_state["api_key"] = new_key
        # Also write to .env for persistence
        try:
            env_path = __import__("pathlib").Path(__file__).parent.parent.parent / ".env"
            env_path.write_text(f"ANTHROPIC_API_KEY={new_key}\n")
            st.success(get_text("save_settings_success"))
        except Exception:
            st.success(get_text("save_settings_success"))

    st.divider()

    # ── Data Refresh ──────────────────────────────────────────────────────
    st.subheader(get_text("market_data_refresh_header"))
    st.caption(get_text("market_data_refresh_desc"))

    col1, col2 = st.columns(2)
    with col1:
        if st.button(get_text("refresh_bnm_btn")):
            with st.spinner("Synchronizing BNM OPR..."):
                try:
                    from scrapers.bnm_scraper import BNMScraper
                    bnm = BNMScraper()
                    series = bnm.fetch_opr_history()
                    st.success(f"BNM OPR: {len(series)} records synchronized. Current rate: {bnm.get_current_opr()}%")
                except Exception as e:
                    st.error(f"Error: {e}")

    with col2:
        if st.button(get_text("refresh_kwsp_btn")):
            with st.spinner("Synchronizing EPF data..."):
                try:
                    from scrapers.kwsp_scraper import KWSPScraper
                    kwsp = KWSPScraper()
                    series = kwsp.fetch_dividend_history()
                    st.success(f"EPF: {len(series)} records synchronized. Latest yield: {kwsp.get_current_dividend()}%")
                except Exception as e:
                    st.error(f"Error: {e}")

    col3, col4 = st.columns(2)
    with col3:
        if st.button(get_text("refresh_gold_btn")):
            with st.spinner("Fetching gold valuation..."):
                try:
                    from scrapers.market_scraper import MarketScraper
                    m = MarketScraper()
                    price = m.get_gold_price_myr_per_gram()
                    st.success(f"Valuation: RM {price:.2f}/gram")
                except Exception as e:
                    st.error(f"Error: {e}")

    with col4:
        if st.button(get_text("check_klci_btn")):
            with st.spinner("Synchronizing KLCI indices..."):
                try:
                    from scrapers.market_scraper import MarketScraper
                    m = MarketScraper()
                    cagr = m.get_index_cagr("^KLSE", years=10)
                    st.success(f"KLCI 10yr CAGR: {cagr:.2f}%")
                except Exception as e:
                    st.error(f"Error: {e}")

    st.divider()

    # ── Snapshot Management ───────────────────────────────────────────────
    st.subheader(get_text("snapshot_management_header"))
    snapshots = repo.list_snapshots()

    if not snapshots:
        st.info(get_text("no_snapshots_info"))
    else:
        snap_df = pd.DataFrame([
            {
                "Snapshot ID": s["id"],
                "Designation": s["label"],
                "Timestamp": s["created_at"][:10],
                "Portfolio Value": f"RM {s['net_worth']:,.2f}",
                "Health Index": f"{s['health_score']:.1f}" if s["health_score"] else "N/A",
                "Strategic Profile": s.get("risk_profile", "moderate"),
            }
            for s in snapshots
        ])
        st.dataframe(snap_df, width="stretch", hide_index=True)

        # Export
        st.markdown("**System Export**")
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            latest_id = repo.get_latest_snapshot_id()
            if latest_id:
                assets = repo.get_snapshot_assets(latest_id)
                asset_df = pd.DataFrame(assets)
                csv = asset_df.to_csv(index=False)
                st.download_button(
                    get_text("export_assets_btn"),
                    data=csv,
                    file_name="financial_ngai_assets.csv",
                    mime="text/csv",
                )
        with exp_col2:
            snapshots_csv = snap_df.to_csv(index=False)
            st.download_button(
                get_text("export_snapshots_btn"),
                data=snapshots_csv,
                file_name="financial_ngai_snapshots.csv",
                mime="text/csv",
            )

        # Maintenance
        with st.expander(get_text("delete_snapshots_expander")):
            del_id = st.selectbox(
                get_text("select_snapshot_to_delete_label"),
                options=[s["id"] for s in snapshots],
                format_func=lambda i: next(
                    f"{s['label']} — {s['created_at'][:10]}" for s in snapshots if s["id"] == i
                ),
            )
            if st.button(get_text("delete_selected_snapshot_btn"), type="secondary"):
                repo.delete_snapshot(del_id)
                st.success("Record purged.")
                st.rerun()

    st.divider()

    # ── About ─────────────────────────────────────────────────────────────
    st.subheader(get_text("about_header"))
    st.markdown(get_text("about_content"))
