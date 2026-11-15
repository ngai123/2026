"""
AI Financial Advisor Chat
--------------------------
Provider priority (first available key wins):
  1. Xiaomi MiMo   — XIAOMI_API_KEY   (OpenAI-compatible, streaming, tool calling)
  2. Gemini         — GEMINI_API_KEY   (google-genai, streaming, tool calling)
  3. Ollama         — local server     (fallback, requires ollama serve)
"""
from __future__ import annotations

import html as _html
import streamlit as st
import uuid

import config
from database import repository as repo

# ─ CSS — bubbles, reasoning blockquote, wave animation ───────────────────────
_CHAT_CSS = """
<style>
[data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
    background: #ffffff !important;
    border-radius: 0 !important;
    padding: 4px 0 !important;
    box-shadow: none !important;
    border: none !important;
    text-align: left !important;
}
[data-testid="stChatMessageAvatarAssistant"] { display: none !important; }

[data-testid="stChatMessage"] blockquote {
    border-left: 3px solid #d2d2d7 !important;
    background: transparent !important;
    color: #86868b !important;
    font-size: 0.8rem !important;
    line-height: 1.5 !important;
    margin: 0 0 12px 0 !important;
    padding: 2px 12px !important;
}
[data-testid="stChatMessage"] blockquote p,
[data-testid="stChatMessage"] blockquote strong {
    color: #86868b !important;
    font-size: 0.8rem !important;
}

@keyframes ngai-wave {
    0%,  100% { transform: translateY(0px);  }
    50%        { transform: translateY(-7px); }
}
.ngai-wave-char {
    display: inline-block;
    animation: ngai-wave 2.2s ease-in-out infinite;
    color: #86868b;
    font-size: 0.92rem;
}
</style>
"""

# Provider badge colours
_BADGE_STYLE = {
    "mimo":   ("🧠 Xiaomi MiMo",  "#ff6900", "#fff"),
    "gemini": ("✨ Gemini",        "#4285f4", "#fff"),
    "ollama": ("🦩 Ollama (local)", "#444",   "#fff"),
}


def _detect_provider() -> str:
    """Return 'mimo' | 'gemini' | 'ollama' based on available keys."""
    if config.XIAOMI_API_KEY:
        return "mimo"
    if config.GOOGLE_API_KEY or config.GEMINI_API_KEY:
        return "gemini"
    return "ollama"


def _provider_badge(provider: str) -> str:
    label, bg, fg = _BADGE_STYLE.get(provider, ("?", "#ccc", "#000"))
    return (
        f'<span style="background:{bg};color:{fg};border-radius:12px;'
        f'padding:2px 10px;font-size:0.78rem;font-weight:600;">{label}</span>'
    )


def _wave_thinking() -> str:
    text = "Thinking..."
    spans = "".join(
        f'<span class="ngai-wave-char" style="animation-delay:{i * 0.13:.2f}s">'
        f'{"&nbsp;" if c == " " else _html.escape(c)}</span>'
        for i, c in enumerate(text)
    )
    return f'<div style="padding:4px 0; line-height:1.8;">{spans}</div>'


def _user_bubble(text: str) -> None:
    safe = _html.escape(text).replace("\n", "<br>")
    st.markdown(
        f"""
        <div style="display:flex;justify-content:flex-end;width:100%;margin:6px 0;">
          <div style="
            background:#e9e9e980;color:#1d1d1f;border-radius:22px;
            padding:10px 16px;max-width:70%;width:fit-content;
            font-size:0.95rem;line-height:1.5rem;word-break:break-word;
          ">{safe}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─ Consultant factory (cached per session) ───────────────────────────────────

def _get_consultant(provider: str):
    """Create (or retrieve from cache) a unified ``Consultant`` instance."""
    from ai.chat import Consultant
    from ai.registry import SYSTEM_PROMPT

    cache_key = f"consultant_{provider}"
    if cache_key not in st.session_state:
        if provider == "mimo":
            from ai.adapters import OpenAIAdapter
            adapter = OpenAIAdapter(
                api_key=config.XIAOMI_API_KEY,
                base_url=config.XIAOMI_BASE_URL,
                model=config.XIAOMI_MODEL,
            )
            st.session_state[cache_key] = Consultant(adapter=adapter)

        elif provider == "gemini":
            from ai.adapters import GeminiAdapter
            gemini_key = config.GOOGLE_API_KEY or config.GEMINI_API_KEY
            adapter = GeminiAdapter(
                api_key=gemini_key,
                model=config.GEMINI_MODEL,
            )
            st.session_state[cache_key] = Consultant(adapter=adapter)

        else:  # ollama
            from ai.adapters import OpenAIAdapter
            adapter = OpenAIAdapter(
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                model="qwen3.5:9b",
            )
            st.session_state[cache_key] = Consultant(
                adapter=adapter,
                system_prompt="/no_think\n" + SYSTEM_PROMPT,
            )

    return st.session_state[cache_key]


def _reason_sep(provider: str) -> str:
    """Separator between reasoning block and response content."""
    if provider == "gemini":
        # Gemini never emits  blocks → separator never appears
        return "<<NEVER>>"
    from ai.chat import _REASON_SEP
    return _REASON_SEP


# ─ Page ──────────────────────────────────────────────────────────────────────

def render():
    st.markdown(_CHAT_CSS, unsafe_allow_html=True)

    provider = _detect_provider()
    label, _, _ = _BADGE_STYLE[provider]
    model_name = {
        "mimo":   config.XIAOMI_MODEL,
        "gemini": config.GEMINI_MODEL,
        "ollama": "qwen3.5:9b",
    }[provider]

    st.markdown("# AI Advisor")
    st.markdown(
        f"{_provider_badge(provider)}"
        f'&nbsp;<span style="color:#86868b;font-size:0.82rem;">{model_name} · '
        f'Ask anything, record expenses, run projections.</span>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    # ─ Session setup ──────────────────────────────────────────────────
    if "chat_session_id" not in st.session_state:
        st.session_state["chat_session_id"] = str(uuid.uuid4())
    session_id = st.session_state["chat_session_id"]
    latest_id  = repo.get_latest_snapshot_id()

    _, col_btn = st.columns([5, 1])
    with col_btn:
        if st.button("Clear Chat", use_container_width=True):
            repo.clear_conversation(session_id)
            st.session_state.pop("chat_messages", None)
            st.session_state["chat_session_id"] = str(uuid.uuid4())
            st.rerun()

    if "chat_messages" not in st.session_state:
        history = repo.get_conversation(session_id, limit=50)
        st.session_state["chat_messages"] = [
            {"role": m["role"], "content": m["content"]} for m in history
        ]

    messages: list[dict] = st.session_state["chat_messages"]

    # ─ Starter prompts (shown when chat is empty) ─────────────────────
    if not messages:
        st.markdown("**Try asking:**")
        starters = [
            "Analyse my current portfolio",
            "How does my KWSP compare to peers?",
            "Run a 20-year Monte Carlo projection",
            "Record lunch RM15",
            "When can I pay off my PTPTN?",
        ]
        cols = st.columns(len(starters))
        for col, prompt in zip(cols, starters):
            if col.button(prompt, use_container_width=True):
                messages.append({"role": "user", "content": prompt})
                repo.save_message(session_id, "user", prompt, latest_id)
                st.rerun()

    # ─ Render existing history ────────────────────────────────────────
    for msg in messages:
        if msg["role"] == "user":
            _user_bubble(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(msg["content"])

    # ─ New user message ───────────────────────────────────────────────
    user_input = st.chat_input("Ask anything, or say 'record lunch RM12'…")
    if not user_input:
        return

    messages.append({"role": "user", "content": user_input})
    repo.save_message(session_id, "user", user_input, latest_id)
    _user_bubble(user_input)

    # ─ Stream assistant response ──────────────────────────────────────
    consultant  = _get_consultant(provider)
    reason_sep  = _reason_sep(provider)

    with st.chat_message("assistant"):
        think_ph    = st.empty()
        response_ph = st.empty()

        think_ph.markdown(_wave_thinking(), unsafe_allow_html=True)

        reason_buf    = ""
        response_text = ""
        found_sep     = False

        try:
            for chunk in consultant.stream_chat(messages, snapshot_id=latest_id):
                if not found_sep:
                    reason_buf += chunk
                    if reason_sep in reason_buf:
                        found_sep = True
                        reasoning, _, response_start = reason_buf.partition(reason_sep)
                        exp = think_ph.expander("Thinking...", expanded=False)
                        exp.markdown(reasoning.strip() or "…")
                        response_text = response_start
                        if response_text.strip():
                            response_ph.markdown(response_text + "▌")
                    else:
                        think_ph.markdown(reason_buf + "▌")
                else:
                    response_text += chunk
                    response_ph.markdown(response_text + "▌")

        except Exception as e:
            think_ph.empty()
            response_text = f"**Error:** {e}"
            if provider == "ollama":
                response_text += "\n\nMake sure Ollama is running (`ollama serve`) and the model is pulled."
            response_ph.markdown(response_text)

        # Finalise display
        if found_sep:
            response_ph.markdown(response_text)
        else:
            think_ph.empty()
            response_ph.markdown(reason_buf)
            response_text = reason_buf

    if response_text:
        messages.append({"role": "assistant", "content": response_text.strip()})
        repo.save_message(session_id, "assistant", response_text.strip(), latest_id)

    st.rerun()
