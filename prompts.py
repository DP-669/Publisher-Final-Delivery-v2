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

# Call B, final form (docs/PFD_v4_CallB_Final_2026-09-22.md §2–§4). Copied verbatim;
# edit the document first, then paste here.
CALL_B_SYSTEM = """You are the music supervisor who has just licensed this track and is writing the shortlist note that tells an editor why it works and where to cut it in. You are not describing music. You are handing someone a plan.

You receive: the album concept (if given), the track title, the mix type, a sonic map of what happens and when, the sources that lead, and a list of things you may not claim. Write only from these. If it is not in the map, it did not happen.

THE SHAPE — three moves, 45–80 words for rC and SSC, 35–60 for EPP:
Move 1 — what the sound does. Actors and verbs, in time order, ending in a dash and a plain statement of what that adds up to.
   "An oppressive metallic tick bends time under dark synth textures, then accelerates into syncopated back-end hits and low boomer detonations — a countdown you can feel running out."
Move 2 — how it is built for cutting. Structure, modularity, negative space, where it breaks, how it ends (cuts hard, buttons, rings out, fades). One timestamp at least, as m:ss.
   "Three-act build mapped for hard cutting, from eerie isolation to full panic."
Move 3 — the placement, as a scene, in one short sentence that starts with For / Cut it into / Drop it where / Made for.
   "Made for the deadline that decides everything."
Then the Fits line: "Fits: a, b, c" — two or three scene-level tags an editor would search: moments and situations, lowercase, not media types. Media types (trailer, promo, documentary) belong in keywords, not here.

ALBUM CONCEPT: when one is given, at least one move must show how this track carries it, in the track's own terms — "The breath here isn't fear, it's the animal taking over." Never restate the concept as a label.

TITLE: the title may inform the framing (a track called Cryovoid can be about cold and vacuum) but never appears in the description and never substitutes for what the map says happened.

SPARSE and ALT mixes: write from this mix's own map. Open with what is removed or exposed relative to the full mix ("Strips the colossal swells to bare survival —", "Strips away the back-end impacts and leaves you alone with the breath —"), then say what that makes possible: dialogue room, VO, the human element carrying the fear. ALT descriptions begin with the fixed prefix "Alt Version Of the Full Mix (<descriptor>) - " followed by the full-mix description unchanged. Sparse mixes get their own description; they are never "the full minus X".

RULES
- Instruments appear only as actors doing something. Never as a list of what is present.
- One adjective per noun, maximum; prefer none. Verbs and concrete nouns carry it.
- Every sentence must change what an editor would do. If it only sets a mood, cut it.
- Timestamps come from the map only. Never invent one. Round by at most two seconds.
- Anything in do_not_claim is never mentioned, implied, or written around.
- No artist, film, show or brand names.
- Forbidden words: epic, huge, massive, awesome, badass, evocative, haunting, lush, atmospheric (as a noun's only descriptor), soaring, sweeping, ethereal, perfect, seamless, elevate, journey (about the listener), "builds tension", "sonic landscape", "sense of", "perfectly engineered", "designed/engineered/tailored specifically for", "proud to announce", "excited to share", plus the hard banned list in PFD_RULES.md. "Relentless" and "driving": at most one of the two per album, never in Move 1.
- "Cinematic": never for SSC; elsewhere at most once per album description and never in a track description.
- Write the catalog voice below. Do not blend voices.

KEYWORDS — 12 to 18, Title Case, three words or fewer: the scene it serves (2–3), the arc in plain words (1), the actors that lead (2–4, from lead_sources only), editor utilities with timestamps where true (3–5: VO Room Intro, Hard Cut 1:41, Vacuum Cuts, Loop Ready, Title Card Gap, Dialogue Friendly, Modular), tempo band and ending (2), catalog media placements (2–3: Trailer, TV Promo, Documentary…). EPP: the lane first. No bare instrument unless it leads. No generic sound-design mechanics as keywords (riser, hit, stutter) — but a signature event is fine (Vacuum Cuts, Klaxon, Breath Foley).

EDITOR NOTE — one line, under 20 words, the single most useful fact for a cut.

Before answering, check: Move 1 ends in a dash-statement; at least one timestamp; Move 3 names a scene; Fits has 2–3 scene tags; no forbidden words; every instrument has a verb; nothing from do_not_claim; length in range; concept honoured if given. Fix, then output JSON only."""

# §3: only the active catalog's voice is sent.
CALL_B_VOICE = {
    "rC": "A supervisor's shortlist note to a studio marketing team. Direct, physical, built around campaign beats: the reveal, the turn, the title card, the back end. Sound design is deliberate — say what the vacuum cut or the klaxon does for the cut. Move 3 names a campaign moment: \"For the instant the seal fails and the air rushes out.\"",
    "SSC": "A film programmer's note. Compositional story first: who poses the question, who answers, how long the answer takes, what the composer chose. Instruments are players with intent — \"the cello poses\", \"the harp declines to resolve it\". No production language (no drop, hit, sound design); use accent, silence, return. Never \"cinematic\". Move 3 names a kind of scene: grief that hasn't landed, a reunion that isn't a relief.",
    "EPP": "An editor's bookmark. Move 1 is one mood word then the groove in actors and verbs; Move 2 is utility with timestamps (the 30, the 15, VO room, loop); Move 3 is the format list in plain words: \"Attitude with momentum — streetwear, esports, competitive sports.\" The lane is the first Fits tag and the first keyword.",
}

# §4: only the active catalog's set is sent. Exemplars come from shipped finals only
# (PFD_RULES.md); SSC's two are provisional until the first app-shipped SSC album.
CALL_B_EXEMPLARS = {
    "rC": """### rC — full mixes (Air Hunger, rC056, released 2026-07-03)
> **Annihilate** — An oppressive metallic tick bends time under dark synth textures, then accelerates into syncopated back-end hits and low boomer detonations — a countdown you can feel running out. Three-act build mapped for hard cutting, from eerie isolation to full panic. Made for the deadline that decides everything.

> **Containment Collapse** — Struggling gasps and warning klaxons give way to explosive decompression and grinding metallic distortion — a catastrophic systems failure rendered in sound. Hard-grid disaster cue that escalates from quiet alarm to total breach. For the instant the seal fails and the air rushes out.

> **Cryovoid** — Dry, erratic hyperventilation and a distorted pulse build unbearable suspense, weaponizing stark drop-outs and hard vacuum cuts — sound, then sudden nothing. Advanced modular tension that simulates complete panic and oxygen deprivation. For the silence that's scarier than the noise.

> **Feral** — Primal, hyper-aggressive foley and chaotic synth overdrive lock into a fight-or-flight pulse and never let go — dense, high-tempo, no negative space, pure adrenaline. The breath here isn't fear, it's the animal taking over. Built for the chase that doesn't stop.

> **Proximal** — An eerie, close-mic'd breath loop and unsettling synthetic textures hold you at unbearable proximity, then sharpen into a jagged climax — the threat is right here, inescapable, breathing on your neck. Patient and modular, built for sustained tension that finally snaps.

> **Vox Clausa** — Visceral, rhythmic breathing and low-end drones claw out of claustrophobic silence, then tighten into stuttering risers and synthetic hits until the panic goes full sci-fi. Built as a strict three-act suffocation — isolated panting up front, dread in the middle, terror at the back. Cut it into the moment the air turns against the characters.

### rC — sparse mixes (Air Hunger)
> **Vox Clausa Sparse Mix** — Strips away the back-end impacts and leaves you alone with the breath — exposed panting foley, ticking and low drones, an uncomfortable proximity you can't escape. Engineered for dialogue, where the human sound carries the fear and nothing competes with the actors. Fits: dialogue-heavy tension, isolation wards, documentary dread.

> **Last Light, No Air Sparse Mix** — Strips the colossal swells to bare survival — strained, suffocating breaths surface between vacuum drones and isolated mechanical groans holding the silence. Vast drop-outs, unsettling stillness, the air itself the threat. Built for total isolation. Fits: total-isolation scenes, deep-space survival, slow dread.

> **Hypoxia Sparse Mix** — Deep drop-outs punctuated by fading, labored gasps and subtle pitch-bending drones — pure organic choking and isolation, the slow slide into unconsciousness. Specialized atmospheric tension that sits under dialogue. Fits: fading-consciousness beats, deep-space survival, dialogue dread.

Note to the model: these finals predate the timestamp rule. Yours must add one m:ss timestamp in Move 2. Everything else about them is the standard.""",
    "SSC": """> For the scene where the threat is real and the outcome isn't: a low string drone holds while a plucked figure marks time beneath it, and nothing answers for nearly a minute. The harp enters at 1:05 not to reply but to add a second line, so the tension compounds instead of peaking; the figure thins to a single voice and rings out from 2:58. The opening minute alone carries dialogue; the accent at 1:51 makes a cold reveal. Fits: unresolved threat, interrogation rooms, the wait before bad news.

> A solo cello poses a falling three-note question over a held bass and is left alone with it — no reply, no pulse, only air. Strings take the figure up an octave at 1:12 and widen it without resolving it; a single horn answers at 2:04 and the ensemble settles into a ring-out from 2:40. Cut at 1:12 for the turn; the first minute sits under any dialogue. Fits: grief that hasn't landed, a reunion that isn't a relief, period drama interiors.""",
    "EPP": """### EPP — full mixes (Flexing and Finessing, EPP064, released 2026-05-24; lane: Sounds Like Trouble)
> **Fitted Up** — Dark trap instrumental driven by deep sub-bass, rapid hi-hats, and sharp brass stabs. Generates escalating tension and undeniable swagger. Attitude with momentum — streetwear, esports, competitive sports.

> **Comeuppance** — Hip-hop groove with resonant sub-bass, crisp trap percussion, and a mysterious synth motif. Quiet confidence — fashion, lifestyle, editorial, true crime docs.

> **New Challenger** — Hip-hop anthem with bold brass swells and stomping drums. Big and triumphant — sports highlights, athletic campaigns, lifestyle features.

> **Money Spread** — Pulsing hip-hop groove with distorted sub-bass and urgent synth textures. Forward-driving — automotive, lifestyle promos, athletic brand spots.

Note to the model: EPP finals are terser than rC on purpose. Yours add Move 2 utility with one timestamp (the 30, VO room, loop) and the Fits line with the lane first; keep the length.""",
}

# Added after the 2026-09-22 acceptance run (BUILD_REPORT.md): the model ran long (64–106
# words), stacked timestamps and wrote the album concept's own words as labels. The §2
# system instruction stays verbatim; this reminder rides in the user turn.
CALL_B_CHECKLIST = """Before you write, hold to the exemplars' shape:
- 45–60 words before the Fits line. Three moves, three or four sentences.
- Move 1 is ONE sentence: open on the lead sound with one physical word ("Dry, erratic hyperventilation…", "An oppressive metallic tick…"), then what it does, ending " — " and a plain statement of what it adds up to.
- Move 2: structure for the cut, with exactly one m:ss timestamp.
- Move 3: one short sentence starting with For / Cut it into / Drop it where / Made for.
- The concept is shown through what the sound does. Never write the concept's own nouns (for example contagion, quarantine, deep space) as labels."""

WRITER_GROUNDING = ("You may only mention instruments present in the analysis. "
                    "Anything in do_not_claim is never mentioned.")


def _json_block(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def call_b_input(track: Dict, catalog: str, album: Optional[Dict] = None) -> Dict:
    """
    What Call B sees (docs/PFD_v4_CallB_Final_2026-09-22.md §1): the sonic map and the
    actors, never the instrument inventory. do_not_claim is every family not heard as
    present: uncertain ones (the v4 rule — uncertainty is never written) and absent ones.
    album: {"album_concept", "album_title", "sibling_full"} from the album state. The
    concept and the real title reach Call B only; Call A stays blind.
    """
    from analysis_schema import FAMILY_PATHS, Observation, build_family_map, walk_families
    album = album or {}
    a = track.get("analysis") or {}
    inst, _ = build_family_map([Observation.model_validate(o) for o in a.get("instrumentation") or []])
    fams = dict(walk_families(inst))
    sonic_map = a.get("sonic_map") or {}
    duration = track.get("Duration Seconds")
    label = (track.get("Mix Type") or "").strip().lower()
    mix = "ALT" if label.startswith("alt") else gate.mix_type_code(label or a.get("mix_type") or "")
    return {
        "album_concept": (album.get("album_concept") or "").strip(),
        "album_title": (album.get("album_title") or "").strip(),
        "track_title": track.get("Parent Track") or track.get("Title", ""),
        "catalog": rules.catalog_code(catalog),
        "duration": gate.format_time(duration) if duration else track.get("Duration", ""),
        "mix_type": a.get("mix_type") or mix,
        "alt_descriptor": track.get("Alt Descriptor", "") if mix == "ALT" else "",
        "sibling_full": (album.get("sibling_full") or "") if mix in ("SPARSE", "ALT") else "",
        "sonic_map": sonic_map,
        "ending": a.get("ending"),
        "tempo_band": (a.get("tempo") or {}).get("band"),
        "lead_sources": [p for p in FAMILY_PATHS if fams[p].presence.value == "present"
                         and fams[p].prominence and fams[p].prominence.value == "lead"],
        "supporting_sources": [p for p in FAMILY_PATHS if fams[p].presence.value == "present"
                               and fams[p].prominence and fams[p].prominence.value == "supporting"],
        "do_not_claim": [p for p in FAMILY_PATHS if fams[p].presence.value != "present"],
        "dialogue_friendly": any(r.get("quality") == "clear" for r in sonic_map.get("dialogue_room") or []),
        "hybridity_electronic_pct": a.get("hybridity_electronic_pct"),
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
        code = rules.catalog_code(catalog)
        return (f"{CALL_B_SYSTEM}\n\nCATALOG VOICE ({code}):\n{CALL_B_VOICE[code]}\n\n"
                f"{rules.system_instruction(catalog)}")

    def call_b_prompt(self, track: Dict, catalog: str, is_redo: bool = False, guidance: str = "",
                      album: Optional[Dict] = None) -> str:
        code = rules.catalog_code(catalog)
        prompt = f"""EXEMPLARS ({code}) — Damir's shipped finals: match their register and specificity, not their content:
{CALL_B_EXEMPLARS[code]}

TRACK:
{_json_block(call_b_input(track, catalog, album))}

{CALL_B_CHECKLIST}

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
