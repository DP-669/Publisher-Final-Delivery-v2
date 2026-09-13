"""
Publisher Final Delivery — task templates.

This file holds task wording only: what to do with which inputs, and what shape
to return. Every rule (banned words, catalog DNA, placement lists, Fits, lanes,
format specs) lives in PFD_RULES.md and reaches the model two ways:

  - rules.system_instruction(catalog): the system prompt on every call
  - rules.tunable("<section>"): the TUNABLE spec a template quotes verbatim

If a template ever seems to need a rule, add it to PFD_RULES.md instead.
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


def _json_block(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _voices(track: Dict) -> Dict:
    """The analysis fields a writer may use. Never the title."""
    a = track.get("analysis") or {}
    return {k: a.get(k) for k in ("mix_type", "duration_seconds", "ending_type", "events", "facts",
                                   "job", "narrative_map", "trailer_or_campaign_voice",
                                   "editor_voice", "supervisor_voice", "keywords", "tip")}


def _examples(catalog: str, kind: str) -> str:
    items = rules.few_shot(catalog, kind)
    if not items:
        return ""
    lines = "\n".join(f"- {i}" for i in items)
    return (f"\nREGISTER EXAMPLES (accepted {kind.lower()} descriptions from this catalog; "
            f"match their specificity, not their format):\n{lines}\n")


class PromptEngine:
    # ── Tab 01: analysis (Gemini). Audio + mix type only. ─────────────────────
    def analysis_prompt(self, mix_type: str, catalog: str) -> str:
        mix = gate.mix_type_code(mix_type)
        return f"""Listen to the attached audio. It is a {mix} mix ({'full mix' if mix == 'FULL' else 'sparse mix' if mix == 'SPARSE' else 'sound design element'}).
You are given no title, album or composer. Describe only what you hear.

Return one JSON object matching the response schema:
- mix_type: "{mix}"
- duration_seconds: the length of the audio as you hear it
- ending_type, events (3–6, each with t in seconds from the start), facts: hard facts only
- job, narrative_map, trailer_or_campaign_voice, editor_voice, supervisor_voice, keywords, tip: as specified below
- description: the finished track description, written to the spec below

ANALYSIS SCHEMA SPEC:
{rules.tunable("Analysis schema")}

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}

KEYWORDS SPEC:
{rules.tunable("Keywords")}
{_examples(catalog, "Track")}
For EPP, leave the lane out of keywords and Fits; code adds it once the album's lane is confirmed."""

    def verification_prompt(self, claims: Dict[str, str]) -> str:
        lines = "\n".join(f"- {key}: {text}" for key, text in claims.items())
        return f"""Here are claims about this audio. Answer each TRUE or FALSE. Also state the duration in seconds.

{lines}"""

    def keyword_shorten_prompt(self, keyword: str) -> str:
        return f"Rephrase '{keyword}' as exactly 1, 2, or 3 words. Preserve meaning. Return ONLY the new keyword."

    # ── Tab 02: track descriptions (writer modes) ─────────────────────────────
    def track_synth_prompt(self, track: Dict, catalog: str, is_redo: bool = False, guidance: str = "") -> str:
        """claude_synth: write the description from the analysis voices."""
        prompt = f"""Write the track description from this analysis of the audio.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}
{_examples(catalog, "Track")}
ANALYSIS:
{_json_block(_voices(track))}

Return ONLY the description, ending with the Fits line. No preamble, no labels."""
        if is_redo:
            prompt += "\n\nThis is a redo: take a different angle from the previous version."
        if guidance:
            prompt += f"\n\nEditor guidance for this version: {guidance}"
        return prompt

    def track_edit_prompt(self, track: Dict, catalog: str, description: str, issues: List[str],
                          is_redo: bool = False, guidance: str = "") -> str:
        """claude_edit: edit Gemini's description under the rules."""
        prompt = f"""Edit this track description so it obeys the rules. Keep every specific, true detail from the listen; rewrite anything generic.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}
{_examples(catalog, "Track")}
ANALYSIS (ground truth for facts):
{_json_block(_voices(track))}

DESCRIPTION TO EDIT:
{description}

PROBLEMS FOUND BY CODE: {"; ".join(issues) if issues else "none"}

Return ONLY the edited description, ending with the Fits line."""
        if is_redo:
            prompt += "\n\nThis is a redo: take a different angle from the previous version."
        if guidance:
            prompt += f"\n\nEditor guidance for this version: {guidance}"
        return prompt

    def track_gate_prompt(self, description: str, issues: List[str]) -> str:
        """gemini mode: Claude gates Gemini's text and touches only broken sentences."""
        return f"""Gate this track description. Run the Cliché Test on each sentence, check catalog contamination and length against the spec, and consider the problems code already found.

TRACK DESCRIPTION SPEC:
{rules.tunable("Track description")}

DESCRIPTION:
{description}

PROBLEMS FOUND BY CODE: {"; ".join(issues) if issues else "none"}

Edit ONLY sentences that fail. Leave passing sentences word for word. If nothing fails, return the description unchanged.
Return ONLY the description, ending with the Fits line."""

    # ── Tab 03: EPP lane and album description ────────────────────────────────
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

    def album_description_prompt(self, catalog: str, track_descriptions: List[str], recent: List[str]) -> str:
        return f"""Write the album description.

ALBUM DESCRIPTION SPEC:
{rules.tunable("Album description")}
{_examples(catalog, "Album")}
THE CATALOG'S LAST ALBUM DESCRIPTIONS (read first; do not repeat their nouns):
{self._bullets(recent) or "- (none available)"}

TRACK DESCRIPTIONS:
{self._bullets(track_descriptions)}

Return ONLY the album description."""

    def album_description_iteration_prompt(self, catalog: str, track_descriptions: List[str], recent: List[str],
                                           history: List[Dict], guidance: str) -> str:
        past = "\n".join(
            f"- v{i}: {h['description']}" + (f"  (direction: {h['guidance']})" if h.get("guidance") else "")
            for i, h in enumerate(history, 1)
        )
        return f"""Revise the album description. Build on the previous versions; apply the direction precisely.

ALBUM DESCRIPTION SPEC:
{rules.tunable("Album description")}

THE CATALOG'S LAST ALBUM DESCRIPTIONS (do not repeat their nouns):
{self._bullets(recent) or "- (none available)"}

TRACK DESCRIPTIONS:
{self._bullets(track_descriptions)}

PREVIOUS VERSIONS:
{past or "- (none)"}

DIRECTION: {guidance or "Write the strongest version."}

Return ONLY the album description."""

    # ── Tab 04: album names ───────────────────────────────────────────────────
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

    # ── Tab 05: cover art ─────────────────────────────────────────────────────
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

    # ── Tab 06: MailChimp ─────────────────────────────────────────────────────
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

    # ── Tab 07: fix existing copy ─────────────────────────────────────────────
    def manual_refinement_prompt(self, content: str, content_type: str) -> str:
        spec_section = {
            "Track Description": "Track description",
            "Album Description": "Album description",
            "MailChimp Intro": "MailChimp intro",
            "Album Name": "Album names",
        }.get(content_type)
        spec = f"\n\nSPEC:\n{rules.tunable(spec_section)}" if spec_section else ""
        return f"""Rewrite this {content_type} so it obeys the rules. Keep what is specific and true; cut what is generic.{spec}

ORIGINAL:
{content}

Return ONLY the rewritten content."""

    @staticmethod
    def _bullets(items: List[str]) -> str:
        return "\n".join(f"- {i}" for i in items if i)
