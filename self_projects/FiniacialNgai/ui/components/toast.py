"""Animated toast notification component."""
import streamlit as st
import streamlit.components.v1 as components

_TOAST_COLORS = {
    "success": "rgba(52,199,89,0.95)",
    "error":   "rgba(255,59,48,0.95)",
    "info":    "rgba(0,122,255,0.95)",
}

_TOAST_SHADOW = {
    "success": "rgba(52,199,89,0.35)",
    "error":   "rgba(255,59,48,0.35)",
    "info":    "rgba(0,122,255,0.35)",
}

_TOAST_ICONS = {
    "success": "\u2705",
    "error":   "\u274c",
    "info":    "\u2139\ufe0f",
}


def show_toast(message: str, type: str = "success") -> None:
    """Display an animated toast notification that slides up and fades out."""
    bg = _TOAST_COLORS.get(type, _TOAST_COLORS["success"])
    shadow = _TOAST_SHADOW.get(type, _TOAST_SHADOW["success"])
    icon = _TOAST_ICONS.get(type, _TOAST_ICONS["success"])
    html = (
        f'<div id="fn-toast" style="'
        f'position:fixed;bottom:32px;right:32px;z-index:9999;'
        f'background:{bg};'
        f'backdrop-filter:blur(16px);'
        f'color:white;font-weight:600;font-size:0.9rem;'
        f'padding:14px 22px;border-radius:16px;'
        f'box-shadow:0 8px 32px {shadow};'
        f'animation:slideInToast 0.3s ease,fadeOutToast 0.4s ease 2.8s forwards;'
        f'">'
        f'{icon} {message}</div>'
        f'<style>'
        f'@keyframes slideInToast{{'
        f'from{{transform:translateY(80px);opacity:0;}}'
        f'to{{transform:translateY(0);opacity:1;}}}}'
        f'@keyframes fadeOutToast{{'
        f'from{{opacity:1;}}to{{opacity:0;}}}}'
        f'</style>'
    )
    components.html(html, height=0)
