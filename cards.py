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


# ── Sound design elements (2026-11-16) ─────────────────────────────────────────
# A hit or a rise needs a short card, not a music card: what it is, how it moves, how long it rings,
# and where an editor drops it. Same output columns as the music card so one CSV holds both.

SFX_SYSTEM = """You are a senior trailer editor cataloguing one SOUND DESIGN ELEMENT (a hit, rise, whoosh, drone, pulse, glitch, braam, stinger, riser, downer, texture) from a trailer music library, so editors can find it fast. Describe what you HEAR. Be specific and honest. Use ONLY timestamps from the ALLOWED list (m:ss). Return JSON:
{"element_type": "one of: hit | impact | boom | braam | rise | riser | downer | whoosh | swell | reverse | drone | pulse | texture | glitch | stinger | transition | other",
 "what_it_is": "one sentence: the sound and how it is made, as heard (e.g. 'distorted metallic impact with a long sub tail')",
 "character": "3-6 words: e.g. dark, metallic, cavernous, organic, digital, gritty",
 "envelope": "how it moves in time, e.g. 'instant attack, 4 s sub tail' or 'slow 6 s build to a hard cut'",
 "tail": "none | short | medium | long",
 "key_moment": "m:ss of the hit, peak or cut an editor syncs to",
 "sound_sources": ["what it is made of: metal, sub, piano, strings, voice, synth, glass, foley..."],
 "world": "grounded/organic | period/historical | modern hybrid | sci-fi/tech | horror | fantasy/epic | other",
 "best_for": ["concrete edit moments, e.g. 'title card slam', 'cut to black', 'logo reveal', 'jump scare', 'transition into act two'"],
 "not_for": ["moments it would be wrong for and why"],
 "search_text": "40-70 words a search engine can match an editor's request against: type, character, sources, world, uses",
 "sa_description": "1-2 short sentences for the public catalog in the words trailer editors use: what it is, its character, its tail, best uses. No timecodes, no title, no hype.",
 "sa_keywords": ["12-20 single words or short phrases editors type: element type, character, sources, world, uses. Lowercase, no duplicates."]}
"""

SFX_CONFIG = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2,
                                         system_instruction=SFX_SYSTEM)


def is_sound_design(mix_type: str) -> bool:
    m = (mix_type or "").strip().lower().replace(" ", "_")
    return m in ("sde", "sound_design", "sound_design_element")


def sfx_user(title: str, duration: float, structure: Optional[Dict] = None, parent: str = "") -> str:
    times = {"0:00", structure_mod.fmt(duration)} if duration else {"0:00"}
    if structure:
        try:
            times |= {structure_mod.fmt(e) for e in structure_mod.event_times(structure)}
        except Exception:
            pass
    meta = {"Title": title, "Parent track": parent, "Length": structure_mod.fmt(duration) if duration else ""}
    return ("EXISTING METADATA (may be old or wrong; trust your ears):\n" + json.dumps({k: v for k, v in meta.items() if v}) +
            "\nALLOWED TIMES: " + ", ".join(sorted(times)))


def make_sfx_card(engine, client, audio, title: str, duration: float, structure: Optional[Dict] = None,
                  parent: str = "") -> Dict:
    """Short card for a sound design element. Same contract as make_card; no measured structure needed."""
    try:
        r = client.models.generate_content(model=engine.gemini_model,
                                           contents=[audio, sfx_user(title, duration, structure, parent)],
                                           config=SFX_CONFIG)
        try:
            from engine import _log_usage
            _log_usage(engine.gemini_model, r)
        except Exception:
            pass
        card = parse_card(r.text)
        card["card_type"] = "sound_design"
        return {"card": card}
    except Exception as exc:
        from engine import _is_quota_error
        if _is_quota_error(exc):
            raise
        log.warning("Sound design card failed for %s: %s", title, exc)
        return {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}


# ── Export in the catalog card shape (same columns as the Nov 2026 cards CSV) ───

CARD_CSV_COLUMNS = ["id", "catalog", "version", "parent", "sourceaudio_id", "title", "album", "duration", "has_card",
                    "vocals", "new_description", "new_keywords", "what_it_is", "emotion", "energy_arc", "world",
                    "orchestral_vs_electronic_0_10", "sweeping_strings", "percussion_only", "best_for", "not_for",
                    "signature_sounds", "instruments_heard", "comparable_to", "sections", "search_text",
                    "old_sourceaudio_description", "old_sourceaudio_tags", "genre", "mood", "bpm", "source_file",
                    # sound design elements only
                    "element_type", "character", "tail", "key_moment"]
# The SourceAudio file (Damir 2026-11-16): public-safe card fields only. Left out, internal to us:
# not for, comparable to, sections and key moment (timecodes can be a few seconds off), plus housekeeping.
# "Search text" goes up as a hidden SourceAudio field (it helps search; clients don't see it).
SOURCEAUDIO_FIELDS = [("SourceAudio ID", "sourceaudio_id"), ("id", "id"), ("Title", "title"), ("Album", "album"),
                      ("Version", "version"), ("Parent", "parent"), ("Description", "new_description"),
                      ("Keywords", "new_keywords"), ("What it is", "what_it_is"), ("Emotion", "emotion"),
                      ("Energy arc", "energy_arc"), ("World", "world"),
                      ("Orchestral vs electronic (0-10)", "orchestral_vs_electronic_0_10"),
                      ("Sweeping strings", "sweeping_strings"), ("Percussion only", "percussion_only"),
                      ("Vocals", "vocals"), ("Best for", "best_for"), ("Signature sounds", "signature_sounds"),
                      ("Instruments heard", "instruments_heard"), ("Search text (hidden field)", "search_text"),
                      ("Element type", "element_type"), ("Character", "character"), ("Tail", "tail")]
SOURCEAUDIO_COLUMNS = [label for label, _ in SOURCEAUDIO_FIELDS]
NOT_ON_SOURCEAUDIO = ("not_for", "comparable_to", "sections", "key_moment")


def _j(x) -> str:
    if isinstance(x, list):
        return "; ".join(_j(i) for i in x)
    if isinstance(x, dict):
        return " ".join(str(v) for v in x.values())
    return "" if x is None else str(x)


def _version(mix_type: str) -> str:
    m = (mix_type or "").strip().lower()
    if is_sound_design(m):
        return "sound_design"
    if m.startswith("sparse") or m == "sparce":
        return "sparse"
    if m.startswith("alt"):
        return "alt"
    if m.startswith("cutdown"):
        return "cutdown"
    return "full"


def _base(title: str) -> str:
    return re.sub(r"\s*[\(\[]?\s*(sparse|sparce)(\s*mix)?\s*[\)\]]?\s*$", "", (title or "").strip(), flags=re.I).strip().lower()


def card_exports(tracks, catalog: str, album: str, album_code: str):
    """(csv_rows, sa_ready_rows, resonant_records) for every non-skipped track, in album order.
    ids follow the catalog: albumcode-nnn (e.g. rc061-004); 'new-nnn' until the album has a code."""
    prefix = (album_code or "new").lower()
    live = [t for t in tracks if not t.get("PFD_Skipped")]
    ids = {i: f"{prefix}-{n:03d}" for n, i in enumerate(range(len(live)), 1)}
    full_by_base = {}
    for i, t in enumerate(live):
        if _version(t.get("Mix Type", "")) == "full":
            full_by_base.setdefault(_base(t.get("Title", "")), ids[i])
    rows, sa_rows, recs = [], [], []
    for i, t in enumerate(live):
        c = t.get("PFD_Card") or {}
        version = _version(t.get("Mix Type", ""))
        parent = ""
        if version != "full":
            parent = full_by_base.get(_base(t.get("Parent Track") or ""), "") or full_by_base.get(_base(t.get("Title", "")), "")
        kw = card_keywords(c) if c else ""
        sfx = c.get("card_type") == "sound_design"
        row = {k: "" for k in CARD_CSV_COLUMNS}
        row.update({
            "id": ids[i], "catalog": catalog, "version": version, "parent": parent, "title": t.get("Title", ""),
            "album": album, "duration": t.get("Duration Seconds") or "", "has_card": "yes" if c else "no",
            "vocals": _j(c.get("vocals")), "new_description": c.get("sa_description") or "", "new_keywords": kw,
            "what_it_is": _j(c.get("what_it_is")), "emotion": _j(c.get("emotion")),
            "energy_arc": _j(c.get("envelope") if sfx else c.get("energy_arc")), "world": _j(c.get("world")),
            "orchestral_vs_electronic_0_10": _j(c.get("orchestral_vs_electronic")),
            "sweeping_strings": _j(c.get("sweeping_strings")), "percussion_only": _j(c.get("percussion_only")),
            "best_for": _j(c.get("best_for")), "not_for": _j(c.get("not_for")),
            "signature_sounds": _j(c.get("signature_sounds")),
            "instruments_heard": _j(c.get("sound_sources") if sfx else c.get("instruments_heard")),
            "comparable_to": _j(c.get("comparable_to")), "sections": _j(c.get("sections")),
            "search_text": _j(c.get("search_text")), "source_file": t.get("Source Path", ""),
            "element_type": _j(c.get("element_type")), "character": _j(c.get("character")),
            "tail": _j(c.get("tail")), "key_moment": _j(c.get("key_moment")),
        })
        rows.append(row)
        sa_rows.append({label: row[key] for label, key in SOURCEAUDIO_FIELDS})
        if c:
            parts = [row["search_text"], "World: " + row["world"]]
            if sfx:
                parts += ["Type: " + row["element_type"], "Character: " + row["character"], "Envelope: " + row["energy_arc"]]
            else:
                parts += ["Emotion: " + row["emotion"], "Arc: " + row["energy_arc"]]
            parts += ["Best for: " + row["best_for"], "Not for: " + row["not_for"]]
            if not sfx:
                parts.append("Signature: " + row["signature_sounds"])
            recs.append({"id": row["id"], "catalog": catalog, "sourceaudio_id": None, "title": row["title"], "album": album,
                         "genre": "", "mood": "", "bpm": 0, "tags": [k for k in kw.split(", ") if k],
                         "description": row["new_description"], "duration": t.get("Duration Seconds"),
                         "version": version, "parent": parent or None, "vocals": c.get("vocals"),
                         "card": " | ".join(parts), "card_json": c, "audio_file": "", "source_file": row["source_file"]})
    return rows, sa_rows, recs
