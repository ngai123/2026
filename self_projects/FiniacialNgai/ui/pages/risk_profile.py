"""Risk appetite questionnaire page."""
import streamlit as st
from models.balance_sheet import RISK_QUESTIONS, RISK_PROFILE_LABELS, RISK_PROFILE_PARAMS, score_to_profile
from database import repository as repo


from ui.i18n import get_text


def render():
    st.markdown(f"# {get_text('risk_profile_title')}")
    st.caption(get_text('risk_profile_desc'))

    # Show current profile if exists
    current = repo.get_latest_risk_profile()
    if current:
        profile = current["profile"]
        params = RISK_PROFILE_PARAMS.get(profile, {})
        label = RISK_PROFILE_LABELS.get(profile, profile)
        st.info(f"**{get_text('current_profile_label')}:** {label}  |  {params.get('description', '')}")

    st.divider()

    answers = {}
    total_score = 0

    for q in RISK_QUESTIONS:
        st.subheader(q["question"])
        options = [opt[0] for opt in q["options"]]
        selected = st.radio(
            q["question"],
            options=options,
            key=f"rq_{q['id']}",
            label_visibility="collapsed",
        )
        # Find score for selected answer
        for opt_label, opt_score in q["options"]:
            if opt_label == selected:
                answers[q["id"]] = {"answer": selected, "score": opt_score}
                total_score += opt_score
                break
        st.markdown("")

    st.divider()

    # Preview result
    preview_profile = score_to_profile(total_score)
    preview_label = RISK_PROFILE_LABELS[preview_profile]
    preview_params = RISK_PROFILE_PARAMS[preview_profile]

    col1, col2 = st.columns(2)
    with col1:
        st.metric(get_text("your_score_label"), f"{total_score} / 25")
        st.metric(get_text("risk_profile_score_label"), preview_label.split("(")[0].strip())

    with col2:
        st.markdown(f"**{get_text('profile_details_label')}:**")
        st.markdown(f"- {get_text('max_equity_label')}: **{preview_params['max_equity_pct']}%**")
        st.markdown(f"- {get_text('max_crypto_label')}: **{preview_params['max_crypto_pct']}%**")
        st.markdown(f"- {get_text('min_bond_label')}: **{preview_params['min_bond_pct']}%**")
        st.info(preview_params["description"])

    st.markdown("")
    if st.button(get_text("save_risk_profile_btn"), type="primary", width="stretch"):
        profile_id = repo.save_risk_profile(
            profile=preview_profile.value,
            score=total_score,
            answers=answers,
        )
        # Also update the latest snapshot with this risk profile
        latest_id = repo.get_latest_snapshot_id()
        if latest_id:
            with repo._connect() as conn:
                conn.execute(
                    "UPDATE snapshots SET risk_profile=? WHERE id=?",
                    (preview_profile.value, latest_id)
                )
        st.session_state["risk_profile"] = preview_profile.value
        st.success(get_text("risk_profile_saved_success"))
