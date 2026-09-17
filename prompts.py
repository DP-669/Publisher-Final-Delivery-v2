"""
Publisher Final Delivery — task templates (v4).

Call A (listen) is deliberately rule-free and catalog-free: its system prompt is
the analyst brief below, with the file's measured duration, and nothing else.
No title, filename, catalog name or prior track ever reaches it.

Every writing call (Call B and the Claude writers) receives
rules.system_instruction(catalog) as its system prompt and quotes the TUNABLE
specs from PFD_RULES.md. If a writing template ever seems to need a rule, add
it to PFD_RULES.md instead.
"""
import json
from typing import Dict, List, Optional

import gate
import rules

# MidJourney film stock per catalog. PFD_RULES.md asks for a "per-catalog film
# stock line" without naming the stocks, so the v2 choices are kept here until
# the stocks are written into PFD_RULES.md (see DECISIONS.md).
FILM_STOCK = {
    "rC": "35mm Kodak Vision3 500T",
    "SSC": "Leica M6, expired Portra 400",
    "EPP": "Kodachrome 64",
}

CALL_A_SYSTEM = """You are an audio analyst for a production-music publisher. You will hear one MP3. Report only what is audible. Nothing about this file except its duration and mix type is known to you; do not infer from genre expectations.

Duration: {duration_seconds:.1f} seconds. Every timestamp must be between 0 and {duration_seconds:.1f}.

Listen twice in your mind before you write. First as an editor, then as an auditor.

AS AN EDITOR, answer these in order, with timestamps:
1. What speaks first? One element, over what, for how long. Could a voice-over sit on it?
2. What answers it, and when? A reply, a counter-line, or nothing. "Nothing" is a real answer and often the point.
3. Where does the spotlight move? At any moment one element commands attention; name it at each turn. If two fight for it, say so.
4. Does the opening idea travel — to another instrument, up or down a register — or does it repeat unchanged?
5. Where does tension seed, hold, compound, release, or reset? Say which, at each event.
6. Where can an editor cut, loop, land a title card, or ride a hit? Confirmed timestamps only.
7. What one choice did the composer plainly make on purpose?
8. What does this track make possible, in an editor's words — moments, not genres. "The beat where the plan falls apart", not "thriller".

Write these as the sonic map: at most seven events, in time order, verbs and nouns only. "Cello states a falling three-note figure over a held bass" — not "a haunting cello melody". No adjectives of feeling anywhere in the map; the events carry the feeling.

AS AN AUDITOR, fill the instrumentation, grounding, tempo, sections and ending exactly as defined in the schema.

Definitions decide ambiguity:
- drum_kit: kit playing a groove (kick/snare/hat pattern). Timpani = orchestral_percussion. Taiko = hand_and_world_percussion. Programmed trap = electronic_beats.
- orchestral_strings: bowed SECTION with ensemble movement and bow articulation. Static sustained pad = synth_string_pad. If unsure, mark uncertain.
- choir: 3+ voices as a group. One voice with reverb = solo_voice_wordless.
- live_bass: finger/pick articulation. synth_bass: electronic tone or 808. Static low sustain = drone_or_sub.
- orchestral_brass: section blend and breath. Braams/synthetic = hybrid_or_synth_brass.
- Ostinati also reported under pulses_and_ostinati plus their instrument family.

Three states: present (point to it, 1-3 evidence items, confidence >= 0.6), absent (listened, not there), uncertain (give reason — this is correct, never a failure).
Never present with confidence < 0.6. Never present without evidence.
List every family you hear as present or uncertain. Do not list absent families. Never list a family twice.
Grounding fields will be checked against the waveform. Answer from listening.
Energy in sections: 1 = quietest in this track, 5 = loudest in this track.

Scratchpad first: what is audible at the start, at the midpoint, at the end; who speaks first and who answers; where the spotlight moves; each ambiguity. Then the map, then the audit. Output JSON only, matching the schema exactly."""

CALL_A_USER = "Mix type: {mix_type}. Duration: {duration_seconds:.1f} s. Listen to the whole file. Report the analysis."

CALL_B_SYSTEM = """You are a music supervisor who has just licensed this track and is writing the shortlist note that tells a director or editor why it works and how to use it. You are not describing music. You are handing someone a plan.

You will receive a sonic map of one track: what speaks first, what answers, where the spotlight moves, where tension goes, where the cuts are. Write only from the map and the listed sources. If it is not in the map, it did not happen.

THE DESCRIPTION — two or three sentences, then the Fits line.
Sentence 1: the moment it serves, then what the music does first. Name the scene before any instrument. "For the beat where the plan falls apart: a lone cello states a falling figure over a held bass, and nothing answers it."
Sentence 2: the conversation. Who answers, where the idea travels, where tension compounds or releases, and how it ends. One timestamp at least.
Sentence 3 (optional; required for EPP): what an editor can do — cut points, voice-over room, loop, title-card gap, with timestamps as m:ss.
Fits line: "Fits: A, B, C" — two or three tags from the catalog placement list.

RULES
- Instruments appear only as actors doing something. Never as a list of what is present.
- One adjective per noun, maximum. Prefer none. Verbs carry the writing.
- Every sentence must change what an editor would do. If it only sets a mood, cut it.
- Timestamps come from the map only. Never invent one.
- Anything in do_not_claim is never mentioned.
- No artist, film, show or brand names.
- Forbidden words (all catalogs): haunting, epic, huge, massive, driving, pulsing, atmospheric, lush, evocative, relentless, soaring, sweeping, ethereal, perfect, seamless, elevate, journey (noun about the listener), "builds tension", "sonic landscape", "sense of".
- "Cinematic": never for SSC; at most once per album description elsewhere; never in a track description's first sentence.
- Length: rC and SSC 45–80 words before the Fits line. EPP 35–60.

KEYWORDS — 12 to 18, Title Case, three words or fewer: the moment it serves (2–3), the arc shape in plain words (1), lead actors (2–4), editor actions (3–5: e.g. VO Room Intro, Hard Cut 1:41, Loop Ready), tempo and ending (2), placement words (2–3). No bare instrument unless it leads.

EDITOR NOTE — one line, under 20 words. The single most useful fact for a cut. Example: "Intro carries VO to 0:45; the 1:41 drop is a clean title-card gap."

Before you answer, check: first clause names a moment; at least one timestamp; at least one editor action; no forbidden words; every instrument has a verb; nothing from do_not_claim; length in range. Fix, then output JSON only."""

CALL_B_VOICE = {
    "rC": "VOICE: a supervisor's shortlist note to a studio marketing team. Direct, confident, built around campaign moments: the reveal, the turn, the title card, the back end. Name campaign beats, not genres. Utility is mandatory: at least one of hit, drop, title-card gap, or VO room, with a timestamp. Placement list for Fits: Trailer, Teaser, TV Promo, Film, TV Drama, Documentary, Sizzle Reel, Network Promo.",
    "SSC": "VOICE: a film programmer's note. Compositional story first: who poses the question, who answers, how long the answer takes, what the composer chose. Human, exact, unhurried. Instruments are players with intent. No production language; use 'accent', 'silence', 'return'. Never the word cinematic. Placement is the kind of scene before the media type. Placement list for Fits: Film, Prestige TV, Documentary, Drama, Period, Arthouse, Streaming Series.",
    "EPP": "VOICE: an editor's bookmark. One word of mood, then function. Lead with what it is for and what it gives: cut points, the 30, the 15, VO room, loop. Modular structure stated outright with timestamps. The lane is the first Fits tag and the first keyword. Placement list for Fits: lane first, then two of: Advertising, Reality TV, TV Promo, Documentary, Corporate, Lifestyle, Sports, Gaming, Social.",
}

CALL_B_EXEMPLAR = {
    "rC": "For the beat where the mission is finally named: a single treated piano note asks the question at 0:00 over clear air, and a sub pulse answers it at 0:22. The figure passes from piano to low brass by 0:58 and grows on each return until the 1:41 drop empties the mix for a title card; the back end lands at 2:05 and cuts hard at 2:31. Intro carries VO to 0:45; hits at 1:41, 2:05, 2:19. Fits: Trailer, TV Promo, Sizzle Reel.",
    "SSC": "For the scene where the threat is real and the outcome isn't: a low string drone holds while a plucked figure marks time beneath it, and nothing answers for nearly a minute. The harp enters at 1:05 not to reply but to add a second line, so the tension compounds instead of peaking; the figure thins to a single voice and rings out from 2:58. The opening minute alone carries dialogue; the accent at 1:51 makes a cold reveal. Fits: Prestige TV, Film, Documentary.",
    "EPP": "Bright. A two-bar guitar hook states itself at 0:00 and handclaps answer on the second pass; the hook never changes, the layers do. VO-safe to 0:14, clean loop 0:28–0:56, strong 30 at 0:14–0:44, button at 1:30. Fits: Sounds Carefree, Advertising, Lifestyle.",
}

WRITER_GROUNDING = ("You may only mention instruments present in the analysis. "
                    "Anything in do_not_claim is never mentioned.")


def _json_block(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def call_b_input(track: Dict, catalog: str) -> Dict:
    """
    What a writer sees: the sonic map and the actors, never the instrument inventory.
    do_not_claim is every family not heard as present: uncertain ones (the v4 rule —
    uncertainty is never written) and absent ones.
    """
    from analysis_schema import FAMILY_PATHS, Observation, build_family_map, walk_families
    a = track.get("analysis") or {}
    inst, _ = build_family_map([Observation.model_validate(o) for o in a.get("instrumentation") or []])
    fams = dict(walk_families(inst))
    sonic_map = a.get("sonic_map") or {}
    duration = track.get("Duration Seconds")
    return {
        "catalog": rules.catalog_code(catalog),
        "duration": gate.format_time(duration) if duration else track.get("Duration", ""),
        "mix_type": a.get("mix_type"),
        "sonic_map": sonic_map,
        "tempo_band": (a.get("tempo") or {}).get("band"),
        "lead_sources": [p for p in FAMILY_PATHS if fams[p].presence.value == "present"
                         and fams[p].prominence and fams[p].prominence.value == "lead"],
        "supporting_sources": [p for p in FAMILY_PATHS if fams[p].presence.value == "present"
                               and fams[p].prominence and fams[p].prominence.value == "supporting"],
        "do_not_claim": [p for p in FAMILY_PATHS if fams[p].presence.value != "present"],
        "dialogue_friendly": any(r.get("quality") == "clear" for r in sonic_map.get("dialogue_room") or []),
    }


def _writer_context(track: Dict, catalog: str) -> str:
    return f"TRACK:\n{_json_block(call_b_input(track, catalog))}\n\n{WRITER_GROUNDING}"


def _written(track: Dict, catalog: str) -> Dict:
    import capture
    return {"scene_named": track.get(capture.context_label(catalog), ""), "editor_note": track.get("Tip", "")}


def _examples(catalog: str, kind: str) -> str:
    items = rules.few_shot(catalog, kind)
    if not items:
        return ""
    lines = "\n".join(f"- {i}" for i in items)
    return (f"\nREGISTER EXAMPLES (accepted {kind.lower()} descriptions from this catalog; "
            f"match their specificity, not their format):\n{lines}\n")


def _redo(prompt: str, is_redo: bool, guidance: str) -> str:
    if is_redo:
        prompt += "\n\nThis is a redo: take a different angle from the previous version."
    if guidance:
        prompt += f"\n\nEditor guidance for this version: {guidance}"
    return prompt


class PromptEngine:
    # ── Call A: listen (Gemini, audio) ────────────────────────────────────────
    def call_a_system(self, duration_seconds: float, include_shape: bool = False) -> str:
        """include_shape: the no-response_schema fallback pastes the JSON Schema into the brief."""
        text = CALL_A_SYSTEM.format(duration_seconds=duration_seconds)
        if include_shape:
            from analysis_schema import Analysis
            shape = json.dumps(Analysis.model_json_schema(), separators=(",", ":"))
            text += ("\n\nReturn exactly one JSON object that validates against this JSON Schema. "
                     "Keep the property order; no markdown, no commentary.\n" + shape)
        return text

    def call_a_user(self, mix_type: str, duration_seconds: float, hint: str = "", correction: str = "") -> str:
        text = CALL_A_USER.format(mix_type=gate.mix_type_code(mix_type), duration_seconds=duration_seconds)
        if correction:
            text += (f"\nAn editor who listened to this file says: {correction.strip()} "
                     "Treat that as true and make every field agree with it.")
        if hint:
            text += f"\n{hint}"
        return text

    # ── Call B: write (Gemini, text only) ─────────────────────────────────────
    def call_b_system(self, catalog: str) -> str:
        """The supervisor brief, the catalog voice, then the LOCKED rules and catalog DNA."""
        return f"{CALL_B_SYSTEM}\n\n{CALL_B_VOICE[rules.catalog_code(catalog)]}\n\n{rules.system_instruction(catalog)}"

    def call_b_prompt(self, track: Dict, catalog: str, is_redo: bool = False, guidance: str = "") -> str:
        code = rules.catalog_code(catalog)
        prompt = f"""EXAMPLE ({code}) — match its register, not its content:
{CALL_B_EXEMPLAR[code]}

TRACK:
{_json_block(call_b_input(track, catalog))}

Return one JSON object matching the response schema: description (ending with the Fits line), editor_note, keywords, fits, scene_named."""
        if code == "EPP":
            prompt += "\n\nLeave the lane out of keywords and Fits; code adds it once the album's lane is confirmed."
        return _redo(prompt, is_redo, guidance)

    def keyword_shorten_prompt(self, keyword: str) -> str:
        return f"Rephrase '{keyword}' as exactly 1, 2, or 3 words. Preserve meaning. Return ONLY the new keyword."

    # ── Claude writer modes ───────────────────────────────────────────────────
    def track_synth_prompt(self, track: Dict, catalog: str, is_redo: bool = False, guidance: str = "") -> str:
        """claude_synth: write the description from the analysis and the voices."""
        prompt = f"""Write the track description from this analysis of the audio.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}
{_examples(catalog, "Track")}
{_writer_context(track, catalog)}

CALL B NOTES:
{_json_block(_written(track, catalog))}

Return ONLY the description, ending with the Fits line. No preamble, no labels."""
        return _redo(prompt, is_redo, guidance)

    def track_edit_prompt(self, track: Dict, catalog: str, description: str, issues: List[str],
                          is_redo: bool = False, guidance: str = "") -> str:
        """claude_edit: edit Gemini's description under the rules."""
        prompt = f"""Edit this track description so it obeys the rules. Keep every specific, true detail from the listen; rewrite anything generic.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}
{_examples(catalog, "Track")}
{_writer_context(track, catalog)}

DESCRIPTION TO EDIT:
{description}

PROBLEMS FOUND BY CODE: {"; ".join(issues) if issues else "none"}

Return ONLY the edited description, ending with the Fits line."""
        return _redo(prompt, is_redo, guidance)

    def track_gate_prompt(self, track: Dict, description: str, issues: List[str]) -> str:
        """gemini mode: Claude gates Gemini's text and touches only broken sentences."""
        do_not_claim = (track.get("simple") or {}).get("do_not_claim") or []
        return f"""Gate this track description. Run the Cliché Test on each sentence, check catalog contamination and length against the spec, and consider the problems code already found.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}

DESCRIPTION:
{description}

do_not_claim: {_json_block(do_not_claim)}
{WRITER_GROUNDING}

PROBLEMS FOUND BY CODE: {"; ".join(issues) if issues else "none"}

Edit ONLY sentences that fail. Leave passing sentences word for word. If nothing fails, return the description unchanged.
Return ONLY the description, ending with the Fits line."""

    # ── EPP lane and album description ────────────────────────────────────────
    def lane_prompt(self, track_summaries: List[Dict], lanes: List[Dict]) -> str:
        lane_lines = "\n".join(
            f"- {l['name']} ({l['status']}){': ' + l['brief'] if l['brief'] else ''}" for l in lanes
        )
        return f"""Pick the one EPP lane this album belongs to, from its track analyses. Prefer active lanes; choose a dormant lane only if no active lane fits.

LANES:
{lane_lines}

ALBUM ANALYSIS (one entry per track):
{_json_block(track_summaries)}

Return ONLY the lane name, exactly as written in the list."""

    def album_description_prompt(self, catalog: str, track_descriptions: List[str], recent: List[str],
                                 previous: str = "", guidance: str = "") -> str:
        prompt = f"""Write the album description.

ALBUM DESCRIPTION SPEC:
{rules.tunable("Album description")}
{_examples(catalog, "Album")}
THE CATALOG'S LAST ALBUM DESCRIPTIONS (read first; do not repeat their nouns):
{self._bullets(recent) or "- (none available)"}

TRACK DESCRIPTIONS:
{self._bullets(track_descriptions)}"""
        if previous:
            prompt += f"\n\nPREVIOUS VERSION: {previous}\nDIRECTION: {guidance or 'Write a stronger version.'}"
        return prompt + "\n\nReturn ONLY the album description."

    # ── Album names ───────────────────────────────────────────────────────────
    def album_names_prompt(self, album_description: str, track_descriptions: List[str],
                           count: int = 5, avoid: Optional[List[str]] = None) -> str:
        avoid_line = f"\nAlready rejected (do not reuse): {', '.join(avoid)}" if avoid else ""
        return f"""Propose {count} album name candidates.

ALBUM NAMES SPEC:
{rules.tunable("Album names")}

ALBUM DESCRIPTION: {album_description}

TRACK DESCRIPTIONS:
{self._bullets(track_descriptions)}{avoid_line}

Return ONLY JSON: {{"names": [{{"name": "...", "rationale": "one line"}}]}}"""

    # ── Cover art ─────────────────────────────────────────────────────────────
    def cover_art_prompt(self, catalog: str, album_name: str, album_description: str,
                         track_descriptions: List[str], keywords: str, ref_urls: List[str]) -> str:
        code = rules.catalog_code(catalog)
        refs = "\n".join(f"- {u}" for u in ref_urls) or "- [URL]"
        return f"""Write the MidJourney cover-art prompts for this album.

COVER-ART PROMPTS SPEC:
{rules.tunable("Cover-art prompts")}

FILM STOCK LINE FOR THIS CATALOG: {FILM_STOCK[code]}
The LOCKED human-anatomy rule applies to every prompt.

ALBUM: {album_name}
ALBUM DESCRIPTION: {album_description}
KEYWORDS: {keywords}
TRACK DESCRIPTIONS:
{self._bullets(track_descriptions)}

SREF URLS (one per prompt, in order):
{refs}

FORMAT: four prompts separated by blank lines, no numbering. After the fourth, a final line with the gut-check question from the spec, verbatim."""

    # ── MailChimp ─────────────────────────────────────────────────────────────
    def mailchimp_prompt(self, album_name: str, album_description: str,
                         track_descriptions: List[str]) -> str:
        return f"""Write the MailChimp intro for this album.

MAILCHIMP INTRO SPEC:
{rules.tunable("MailChimp intro")}

ALBUM: {album_name}
ALBUM DESCRIPTION: {album_description}
TRACK DESCRIPTIONS (context):
{self._bullets(track_descriptions)}

Return ONLY the intro."""

    @staticmethod
    def _bullets(items: List[str]) -> str:
        return "\n".join(f"- {i}" for i in items if i)
