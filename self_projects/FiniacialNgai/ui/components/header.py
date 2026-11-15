"""Reusable page-header component for FinancialNgai."""
import streamlit as st


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    """Render a styled page header.

    Parameters
    ----------
    title : str
        The large heading text.
    subtitle : str, optional
        Muted secondary line beneath the title.
    icon : str, optional
        Emoji (or short text) shown inside a pill badge to the left of the title.
    """
    icon_html = ""
    if icon:
        icon_html = (
            f'<span style="'
            f"display:inline-flex;align-items:center;justify-content:center;"
            f"width:36px;height:36px;min-width:36px;"
            f"background:linear-gradient(135deg,#007aff,#5856d6);"
            f"border-radius:10px;font-size:1.1rem;margin-right:14px;"
            f'">{icon}</span>'
        )

    subtitle_html = ""
    if subtitle:
        subtitle_html = (
            f'<div style="font-size:.875rem;color:#6b7280;margin-top:2px;'
            f'padding-left:{("50px" if icon else "0")};">{subtitle}</div>'
        )

    st.markdown(
        f"""
        <div style="animation:fadeInUp .4s ease both;margin-bottom:0;">
            <div style="display:flex;align-items:center;">
                {icon_html}
                <span style="font-size:1.75rem;font-weight:800;letter-spacing:-.025em;color:#1d1d1f;">
                    {title}
                </span>
            </div>
            {subtitle_html}
        </div>
        <hr style="border:none;height:1px;background:rgba(0,0,0,.06);margin:16px 0 24px 0;">
        """,
        unsafe_allow_html=True,
    )
