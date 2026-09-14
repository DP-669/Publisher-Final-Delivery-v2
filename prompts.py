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

CALL_A_SYSTEM = """You are an audio analyst for a production-music publisher. You will hear one MP3.
Report only what is audible. Nothing about this file except its duration is known to you.

Duration of this file: {duration_seconds:.1f} seconds. Every timestamp must be between 0 and {duration_seconds:.1f}.

Definitions decide ambiguity:
- drum_kit: kit playing a groove (kick/snare/hat pattern). Timpani = orchestral_percussion. Taiko = hand_and_world_percussion. Programmed trap = electronic_beats.
- orchestral_strings: bowed SECTION with ensemble movement and bow articulation. Static sustained pad = synth_string_pad. If unsure, mark uncertain.
- choir: 3+ voices as a group. One voice with reverb = solo_voice_wordless.
- live_bass: finger/pick articulation. synth_bass: electronic tone or 808. Static low sustain = drone_or_sub.
- orchestral_brass: section blend and breath. Braams/synthetic = hybrid_or_synth_brass.
- Ostinati also reported under pulses_and_ostinati plus their instrument family.

Three states: present (point to it, 1-3 evidence items, confidence >= 0.6), absent (listened, not there), uncertain (give reason — this is correct, never a failure).
Never present with confidence < 0.6. Never present without evidence.
Grounding fields will be checked against the waveform. Answer from listening.
Energy in sections: 1 = quietest in this track, 5 = loudest in this track.
Fill scratchpad first (start/middle/end, 3 most prominent sources, each ambiguity and which definition resolves it). Then fill every field. JSON only."""

CALL_A_USER = "Mix type: {mix_type}. Duration: {duration_seconds:.1f} s. Listen to the whole file. Report the analysis."

WRITER_GROUNDING = ("You may only mention instruments present in the analysis. "
                    "Anything in do_not_claim is never mentioned.")


def _json_block(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def writer_analysis(analysis: Dict) -> Dict:
    """The analysis a writer sees: everything except the scratchpad."""
    return {k: v for k, v in (analysis or {}).items() if k != "analysis_scratchpad"}


def _writer_context(track: Dict) -> str:
    simple = track.get("simple") or {}
    return (f"ANALYSIS:\n{_json_block(writer_analysis(track.get('analysis')))}\n\n"
            f"do_not_claim: {_json_block(simple.get('do_not_claim') or [])}\n\n{WRITER_GROUNDING}")


def _voices(track: Dict, catalog: str) -> Dict:
    import capture
    return {
        "trailer_or_campaign_voice": track.get(capture.context_label(catalog), ""),
        "editor_voice": track.get("Editor Description", ""),
        "supervisor_voice": track.get("Supervisor Description", ""),
        "tip": track.get("Tip", ""),
    }


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
    def call_a_system(self, duration_seconds: float) -> str:
        return CALL_A_SYSTEM.format(duration_seconds=duration_seconds)

    def call_a_user(self, mix_type: str, duration_seconds: float, hint: str = "", correction: str = "") -> str:
        text = CALL_A_USER.format(mix_type=gate.mix_type_code(mix_type), duration_seconds=duration_seconds)
        if correction:
            text += (f"\nAn editor who listened to this file says: {correction.strip()} "
                     "Treat that as true and make every field agree with it.")
        if hint:
            text += f"\n{hint}"
        return text

    # ── Call B: write (Gemini, text only) ─────────────────────────────────────
    def call_b_prompt(self, track: Dict, catalog: str, is_redo: bool = False, guidance: str = "") -> str:
        prompt = f"""Write the metadata for one track from this analysis of its audio. Return one JSON object matching the response schema.
- trailer_or_campaign_voice, editor_voice, supervisor_voice: 1–2 sentences each, catalog-specific.
- description: the finished track description, fusing the three voices, written to the spec below.
- keywords: written to the spec below.
- tip: one line for the editor.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}

KEYWORDS SPEC:
{rules.tunable("Keywords")}
{_examples(catalog, "Track")}
{_writer_context(track)}

For EPP, leave the lane out of keywords and Fits; code adds it once the album's lane is confirmed."""
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
{_writer_context(track)}

VOICES:
{_json_block(_voices(track, catalog))}

Return ONLY the description, ending with the Fits line. No preamble, no labels."""
        return _redo(prompt, is_redo, guidance)

    def track_edit_prompt(self, track: Dict, catalog: str, description: str, issues: List[str],
                          is_redo: bool = False, guidance: str = "") -> str:
        """claude_edit: edit Gemini's description under the rules."""
        prompt = f"""Edit this track description so it obeys the rules. Keep every specific, true detail from the listen; rewrite anything generic.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}
{_examples(catalog, "Track")}
{_writer_context(track)}

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
