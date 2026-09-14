"""
Visible failure reporting.

The v2 app swallowed errors with `except Exception: pass` on the analysis,
generation, export and logging paths, so a failed step looked like an empty
result. Every one of those sites now calls report(): the error is logged, shown
with st.error when a Streamlit page is rendering, and kept in the session so the
sidebar can list it. The app keeps running; the failure is never hidden.
"""
import logging

log = logging.getLogger("pfd")
MAX_KEPT = 20


def _page_is_rendering() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx(suppress_warning=True) is not None
    except Exception as exc:  # streamlit missing or internal API moved
        log.debug("Streamlit context unavailable: %s", exc)
        return False


def report(context: str, exc: BaseException = None, show: bool = True) -> str:
    """Log a failure and surface it in the UI. Returns the message."""
    msg = f"{context}: {type(exc).__name__}: {exc}" if exc is not None else context
    log.error(msg)
    print(f"[PFD] {msg}")
    if show and _page_is_rendering():
        import streamlit as st
        kept = st.session_state.setdefault("pfd_errors", [])
        kept.append(msg)
        del kept[:-MAX_KEPT]
        st.error(msg)
    return msg
