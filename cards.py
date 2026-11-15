"""Catalog listening card (Nov 2026 method, ~/rmg-ops/sourceaudio/card_listen.py).
One Gemini call per track, after the file's structure is measured: a supervisor card with a
catalog description (sa_description), 20-30 search keywords (sa_keywords), emotion and arc with
measured timecodes only, best/not for, signature sounds. Damir 2026-11-15: "head and shoulders
above SourceAudio". Used for 1,255 rC/SSC tracks; same prompt here so new albums match the catalog.
Best-effort: a card failure never blocks a track."""
import json, re, logging
from typing import Dict, Optional
from google.genai import types
import structure as structure_mod

log = logging.getLogger(__name__)

CARD_SYSTEM = """You are a senior trailer music editor and music supervisor cataloguing a library track so it can be matched to future supervisor briefs. Describe what you HEAR, not what a title or tag suggests. Be specific and honest. Use ONLY timestamps from the ALLOWED list (m:ss). Return JSON:
{"what_it_is": "one sentence: style and instruments as heard",
 "instruments_heard": ["..."], "signature_sounds": ["distinctive elements an editor could hang a trailer on, with m:ss"],
 "world": "grounded/organic | period/historical | modern hybrid | sci-fi/tech | horror | fantasy/epic | other",
 "orchestral_vs_electronic": "0-10 (0 fully organic orchestral, 10 fully electronic/sound design)",
 "sweeping_strings": "none | some | dominant", "percussion_only": true/false, "vocals": "none | choir | solo | vocal fx",
 "emotion": "what feelings it carries and WHERE (m:ss); does the back end turn emotional, stay aggressive, or wind down?",
 "energy_arc": "short description of the build, e.g. sparse open -> stop-down 1:02 -> wall 1:40 -> button",
 "sections": [{"start": "m:ss", "end": "m:ss", "role": "intro / dread / tension / action / emotion / climax / button / dialogue bed", "what_happens": "short"}],
 "best_for": ["film/trailer types and moments it fits, concrete (e.g. 'war film final-act sacrifice', 'spy thriller chase')"],
 "not_for": ["briefs it would be wrong for and why"],
 "comparable_to": "the kind of trailer or score it resembles, in plain words (no claims about real licensed music)",
 "search_text": "80-120 words a search engine can match briefs against: style, instruments, world, emotion, structure, best uses",
 "sa_description": "2-3 sentences for the public catalog, in the language music supervisors and trailer editors use today: style, feel, key instruments, build, best uses. No timecodes, no track title, no hype words like 'epic masterpiece'.",
 "sa_keywords": ["20-30 single words or short phrases supervisors type into a search box: genre, mood, instruments, energy, world, uses. Lowercase, no duplicates."]}
"""

CARD_CONFIG = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2,
                                          system_instruction=CARD_SYSTEM)


def parse_card(text: str) -> Dict:
    try:
        card = json.loads(text or "")
    except json.JSONDecodeError:   # Gemini sometimes leaves a trailing comma
        card = json.loads(re.sub(r",\s*([\]}])", r"\1", text or ""))
    card = card[0] if isinstance(card, list) else card
    if not isinstance(card, dict):
        raise ValueError("card is not a JSON object")
    return card


def card_user(title: str, structure: Dict, metadata: Optional[Dict] = None) -> str:
    allowed = sorted({structure_mod.fmt(e) for e in structure_mod.event_times(structure)})
    meta = {k: v for k, v in (metadata or {}).items() if v}
    meta.setdefault("Title", title)
    return ("EXISTING METADATA (may be old or wrong; trust your ears):\n" + json.dumps(meta)[:2500] +
            "\nMEASURED FACTS (ground truth):\n" + structure_mod.brief(structure) +
            "\nALLOWED TIMES: " + ", ".join(allowed))


def make_card(engine, client, audio, title: str, structure: Optional[Dict], metadata: Optional[Dict] = None) -> Dict:
    """Returns {"card": {...}} or {"error": "..."}; never raises except quota errors (the run must stop)."""
    if not structure:
        return {"error": "no measured structure"}
    try:
        r = client.models.generate_content(model=engine.gemini_model, contents=[audio, card_user(title, structure, metadata)],
                                           config=CARD_CONFIG)
        try:
            from engine import _log_usage
            _log_usage(engine.gemini_model, r)
        except Exception:
            pass
        return {"card": parse_card(r.text)}
    except Exception as exc:
        from engine import _is_quota_error
        if _is_quota_error(exc):
            raise
        log.warning("Catalog card failed for %s: %s", title, exc)
        return {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def card_keywords(card: Dict) -> str:
    seen, out = set(), []
    for k in card.get("sa_keywords") or []:
        k = str(k).strip().lower()
        if k and k not in seen:
            seen.add(k); out.append(k)
    return ", ".join(out)
