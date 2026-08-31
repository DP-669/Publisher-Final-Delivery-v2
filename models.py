"""
Model registry check for Publisher Final Delivery.

The problem this solves: the model IDs the app runs on are pinned as constants
in engine.py. Providers ship new models constantly, and a pinned constant plus
a hand-written doc drifts out of date silently — nobody notices until someone
reads the doc and finds it wrong.

Both providers publish a live list-models endpoint. This module asks them what
exists right now, compares that against what the app is pinned to, and reports
anything newer in the same family.

It never switches a model on its own. A newer ID is not automatically a better
one — it may be a preview, it may not accept audio, it may price differently.
So this reports, and a human pins. Pinning is done without a code edit, via the
GEMINI_AUDIO_MODEL / CLAUDE_WRITING_MODEL keys in Streamlit secrets, which
engine.py reads at import.

No new dependencies: both calls go through SDKs the app already installs.
"""
import re
from typing import Dict, List, Optional

# Gemini families that can take audio and produce text. Anything outside this
# set (embeddings, image and video generation, TTS, AQA) is not a candidate for
# the audio-analysis slot no matter how new it is.
GEMINI_CHAT_FAMILIES = ("pro", "flash", "flash-lite", "ultra")
GEMINI_EXCLUDE = (
    "embedding", "embed", "aqa", "imagen", "veo", "tts", "image-generation",
    "learnlm", "gemma",
)

CLAUDE_TIERS = ("opus", "sonnet", "haiku")


# ── Version parsing ────────────────────────────────────────────────────────────

def _strip_prefix(model_id: str) -> str:
    """The Gemini list endpoint returns 'models/gemini-3.1-pro'; drop the prefix."""
    return model_id.split("/", 1)[1] if model_id.startswith("models/") else model_id


def gemini_parts(model_id: str) -> Optional[Dict]:
    """
    Split a Gemini ID into the pieces that decide whether one supersedes another.

    gemini-3.1-pro-preview -> version (3, 1), family 'pro', preview True
    gemini-3.6-flash       -> version (3, 6), family 'flash', preview False

    Returns None for anything that is not a versioned chat model.
    """
    mid = _strip_prefix(model_id).lower()
    if any(bad in mid for bad in GEMINI_EXCLUDE):
        return None
    m = re.match(r"^gemini-(\d+)(?:\.(\d+))?-(flash-lite|flash|pro|ultra)\b", mid)
    if not m:
        return None
    major, minor, family = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if family not in GEMINI_CHAT_FAMILIES:
        return None
    return {
        "id": mid,
        "version": (major, minor),
        "family": family,
        "preview": bool(re.search(r"preview|exp\b|experimental", mid)),
    }


def claude_parts(model_id: str) -> Optional[Dict]:
    """
    Split a Claude ID into tier and version, across both naming schemes.

    claude-sonnet-5           -> tier 'sonnet', version (5, 0)
    claude-opus-4-1-20250805  -> tier 'opus',   version (4, 1)
    claude-3-5-sonnet-...     -> tier 'sonnet', version (3, 5)
    """
    mid = model_id.lower()
    tier = next((t for t in CLAUDE_TIERS if t in mid), None)
    if not tier:
        return None

    # Newer scheme: the version follows the tier (claude-sonnet-5, claude-opus-4-1).
    # Major is bounded to two digits and must not run into a build datestamp,
    # otherwise claude-3-5-sonnet-20241022 parses its date as the version.
    m = re.search(rf"{tier}-(\d{{1,2}})(?:[-.](\d+))?(?!\d)", mid)
    if not m:
        # Older scheme: the version precedes the tier (claude-3-5-sonnet).
        m = re.search(rf"claude-(\d{{1,2}})(?:[-.](\d+))?-{tier}", mid)
    if not m:
        return None

    # A trailing 8-digit date is a build stamp, not a minor version.
    minor_raw = m.group(2)
    minor = int(minor_raw) if minor_raw and len(minor_raw) < 8 else 0
    return {
        "id": model_id,
        "version": (int(m.group(1)), minor),
        "tier": tier,
        "preview": bool(re.search(r"preview|latest|exp\b", mid)),
    }


# ── Live listing ───────────────────────────────────────────────────────────────

def list_gemini_models(api_key: str) -> List[str]:
    """Every model ID the Gemini API currently exposes to this key."""
    from google import genai
    client = genai.Client(api_key=api_key)
    out = []
    for m in client.models.list():
        name = getattr(m, "name", "") or ""
        if not name:
            continue
        # Only models that can actually be called for generation.
        actions = getattr(m, "supported_actions", None) or getattr(
            m, "supported_generation_methods", None
        )
        if actions and "generateContent" not in actions:
            continue
        out.append(_strip_prefix(name))
    return out


def list_claude_models(api_key: str) -> List[str]:
    """Every model ID the Anthropic API currently exposes to this key."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    return [m.id for m in client.models.list(limit=100)]


# ── Comparison ─────────────────────────────────────────────────────────────────

def _compare(pinned: str, available: List[str], parser, group_key: str) -> Dict:
    """
    Shared comparison: is the pinned model still offered, and is anything in the
    same family newer? A stable build of a pinned preview counts as newer.
    """
    result = {
        "pinned": pinned,
        "pinned_available": _strip_prefix(pinned) in [_strip_prefix(a) for a in available],
        "newer": [],
        "stable_of_pinned": None,
        "available_count": len(available),
        "error": None,
    }

    pin = parser(pinned)
    if not pin:
        return result

    for mid in available:
        cand = parser(mid)
        if not cand or cand[group_key] != pin[group_key]:
            continue
        if cand["id"] == pin["id"]:
            continue
        if cand["version"] > pin["version"]:
            result["newer"].append(cand)
        elif (
            cand["version"] == pin["version"]
            and pin["preview"]
            and not cand["preview"]
        ):
            # Same version, but the stable build has shipped. Prefer it.
            result["stable_of_pinned"] = cand["id"]

    result["newer"].sort(key=lambda c: (c["version"], not c["preview"]), reverse=True)
    return result


def check_gemini(pinned: str, api_key: str) -> Dict:
    """Compare the pinned Gemini audio model against what the API offers."""
    if not api_key:
        return {"pinned": pinned, "error": "No Gemini API key configured.",
                "newer": [], "stable_of_pinned": None, "pinned_available": None,
                "available_count": 0}
    try:
        available = list_gemini_models(api_key)
    except Exception as exc:
        return {"pinned": pinned, "error": f"{type(exc).__name__}: {exc}",
                "newer": [], "stable_of_pinned": None, "pinned_available": None,
                "available_count": 0}
    return _compare(pinned, available, gemini_parts, "family")


def check_claude(pinned: str, api_key: str) -> Dict:
    """Compare the pinned Claude writing model against what the API offers."""
    if not api_key:
        return {"pinned": pinned, "error": "No Claude API key configured.",
                "newer": [], "stable_of_pinned": None, "pinned_available": None,
                "available_count": 0}
    try:
        available = list_claude_models(api_key)
    except Exception as exc:
        return {"pinned": pinned, "error": f"{type(exc).__name__}: {exc}",
                "newer": [], "stable_of_pinned": None, "pinned_available": None,
                "available_count": 0}
    return _compare(pinned, available, claude_parts, "tier")


def summarize(report: Dict, label: str) -> str:
    """One-line human summary of a check result, for the sidebar."""
    if report.get("error"):
        return f"{label}: could not check — {report['error']}"
    if report.get("pinned_available") is False:
        return (f"{label}: pinned `{report['pinned']}` is NOT in the provider's "
                f"current list — it may be retired. Check this now.")
    if report.get("stable_of_pinned"):
        return (f"{label}: `{report['stable_of_pinned']}` is the stable build of "
                f"the preview you are pinned to.")
    if report.get("newer"):
        ids = ", ".join(c["id"] for c in report["newer"][:3])
        return f"{label}: newer available — {ids}"
    return f"{label}: `{report['pinned']}` is the newest in its family."
