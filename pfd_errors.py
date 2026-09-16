"""
Visible failure reporting, in words the team can act on.

Nothing swallows an error: every failure is logged, kept in the session and
shown on the page. What the user sees is a plain sentence — what failed and
whether to try again or call Craig — with the technical detail folded away
underneath. Raw exception text never lands in front of a user on its own.
"""
import logging

log = logging.getLogger("pfd")
MAX_KEPT = 20

RETRY = "Try it again. If it keeps happening, send Craig this message."
CHECK_SETUP = "Check the app's settings, then try again. If it keeps happening, send Craig this message."

# (fragment in the error, what it means, what to do). First match wins.
PATTERNS = [
    ("quota", "The analysis service has run out of credit for now.",
     "Top up the Gemini credits, then press Run again. Nothing is lost."),
    ("resource_exhausted", "The analysis service has run out of credit for now.",
     "Top up the Gemini credits, then press Run again. Nothing is lost."),
    ("rate limit", "The analysis service is asking us to slow down.",
     "Wait a minute, then press Run again."),
    ("429", "The analysis service is asking us to slow down.", "Wait a minute, then press Run again."),
    ("api key", "The service refused our key.", CHECK_SETUP),
    ("unauthorized", "The service refused our key.", CHECK_SETUP),
    ("401", "The service refused our key.", CHECK_SETUP),
    ("expired_access_token", "Dropbox needs signing in again.", CHECK_SETUP),
    ("invalid_access_token", "Dropbox needs signing in again.", CHECK_SETUP),
    ("shared_link_not_found", "That Dropbox link doesn't open anything.",
     "Check the link is still shared, then paste it again."),
    ("not_found", "Dropbox couldn't find that file or folder.",
     "Check the link still works and that the file hasn't moved, then try again."),
    ("timeout", "The service took too long to answer.", RETRY),
    ("timed out", "The service took too long to answer.", RETRY),
    ("connection", "We couldn't reach the service.", "Check the internet connection, then try again."),
    ("could not decode", "That audio file couldn't be opened.",
     "Check it plays in a music player. If it does, upload it again."),
]


def explain(context: str, exc: BaseException = None) -> dict:
    """{what, action, detail} — what failed, what to do, and the technical line."""
    detail = f"{type(exc).__name__}: {exc}" if exc is not None else ""
    haystack = f"{context} {detail}".lower()
    for fragment, what, action in PATTERNS:
        if fragment in haystack:
            return {"what": f"{context}. {what}", "action": action, "detail": detail}
    return {"what": f"{context}.", "action": RETRY, "detail": detail}


def _page_is_rendering() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx(suppress_warning=True) is not None
    except Exception as exc:  # streamlit missing or internal API moved
        log.debug("Streamlit context unavailable: %s", exc)
        return False


def report(context: str, exc: BaseException = None, show: bool = True) -> str:
    """Log a failure and surface it in plain words. Returns the logged message."""
    msg = f"{context}: {type(exc).__name__}: {exc}" if exc is not None else context
    log.error(msg)
    print(f"[PFD] {msg}")
    if show and _page_is_rendering():
        import streamlit as st
        said = explain(context, exc)
        kept = st.session_state.setdefault("pfd_errors", [])
        kept.append(msg)
        del kept[:-MAX_KEPT]
        st.error(f"{said['what']} {said['action']}")
        if said["detail"]:
            with st.expander("Technical detail"):
                st.code(said["detail"], language=None, wrap_lines=True)
    return msg
