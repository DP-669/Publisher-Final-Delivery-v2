# PFD_RULES.md
version: 0.4 (draft, 2026-09-16)
status: DRAFT — becomes v1.0 when Claude Code merges the M2 build and Damir runs the first real track.

This file is the only place PFD rules live. The app reads it at startup and injects the LOCKED section plus the active catalog's block into every model call. Editing this file changes the app's behavior on the next deploy. Nothing in prompts.py may contradict it; if it does, prompts.py is wrong.

To change a rule: edit this file, bump the version line, push to main. Git history is the changelog.

---

## LOCKED
The improvement loop may not edit this section. Only Damir edits it.

### Mission
Every word describes a specific piece of music for a professional who has 90 seconds to decide whether to use it. Editors and music supervisors. Not fans. Not the composer. Write for the moment of truth: a stressed human scanning a list under deadline.

### One catalog per run
A run is rC, SSC or EPP. Never mixed. The active catalog's DNA block is injected; the other two are not.

### The analysis must be real
- The audio-analysis prompt never receives the track title, album name, composer, or filename. It receives audio and mix type only. The title is joined to the result afterwards, in code.
- Every analysis must return: duration_seconds, ending_type, 3–6 timestamped events, and hard facts (drums present, vocals present, choir present, tempo band, energy arc).
- Duration is checked against the real file. Timestamps past the real duration fail the track.
- Every present claim carries timestamped evidence. Python verifies timing, ending, loudness shape and section ordering against the decoded waveform (librosa). Contradiction with the waveform or with itself blocks the track; uncertainty never does.
- BLOCKED is a real state. It is shown in the app and carried into the export. It is never silently converted to a result.
- No silent failure anywhere on the analysis or export path. If it failed, the user sees it.

### Hemingway
Short sentences. Concrete nouns. Physics over feeling: what the sound does, not what the listener should feel. No adjective that could describe half the catalog.

### Hard banned list (validator enforces)
epic, huge, massive, awesome, badass, relentless, evocative, perfectly engineered, designed specifically for, engineered specifically for, tailored specifically for, builds tension before exploding into, proud to announce, excited to share, masterfully, seamlessly, sonic short stories.

### Cliché Test (model enforces)
Before keeping any phrase, ask: could a competitor paste this sentence under a different track and no one would notice? If yes, cut it.

### "Cinematic"
Legal. At most once per album description. Never in a track description's first sentence. Never as a keyword.

### Council
Internal. The user sees consensus only. Never expose voices, personas, or deliberation.

### Fits
Every track description ends with a Fits line: `Fits: <tag>, <tag>, <tag>` — two or three tags, from the active catalog's placement list only.

### Human anatomy in cover art
Cover-art prompts never request hands, faces, full human figures, or crowds. Objects, places, weather, materials, macro detail, architecture and light carry the story.

---

## CATALOG DNA

### rC — redCola
Identity: cinematic trailer music and sound design. Theatrical marketing, TV and broadcast promos, film, TV drama. Dark is common, not required — the album leads; bright, uplifting and documentary-leaning albums exist and are described on their own terms.
Allowed placement words: trailer, teaser, theatrical, TV promo, broadcast promo, film, feature, TV drama, prestige TV, documentary, streaming series, sizzle, network promo.
Forbidden placement words: advertising, commercial, brand campaign, corporate, reality TV, unscripted, social, YouTube, lifestyle, esports.
Mix vocabulary: full mix, sparse mix, sound design element (SDE). Sparse and SDE are described as independent listens, never as "the full minus X".
Placement list for Fits: Trailer, Teaser, TV Promo, Film, TV Drama, Documentary, Sizzle Reel, Network Promo.

### SSC — Short Story Collective
Identity: traditionally recorded orchestral cinematic music. Film score register. Prestige TV, documentary, arthouse, drama, period. Elegant, emotionally honest, never trailer-loud.
Allowed placement words: film, score, prestige TV, documentary, drama, period, arthouse, streaming series, TV drama, ballet, concert.
Forbidden placement words: trailer (as a lead placement), promo, advertising, commercial, brand, corporate, reality TV, social, sports.
Forbidden jargon: underscore, bed, stinger, cue-sheet language of any kind.
Placement list for Fits: Film, Prestige TV, Documentary, Drama, Period, Arthouse, Streaming Series.

### EPP — Ekonomic Propaganda
Identity: broad production music with a fixed set of lanes. Advertising and brand, unscripted and reality TV, scripted TV, TV promos, documentary, corporate, educational, lifestyle, cooking, gaming, YouTube, social.
Allowed placement words: advertising, commercial, brand, campaign, reality TV, unscripted, TV promo, scripted TV, documentary, corporate, educational, lifestyle, cooking, gaming, YouTube, social, sports highlights, streetwear.
Forbidden placement words: trailer, teaser, theatrical, blockbuster, feature-film campaign, studio marketing, Hollywood.
Lanes: every EPP album belongs to exactly one lane from EPP_LANES.md. The lane is the first keyword on every track and the first Fits tag. The lane is NOT part of the album title.
Placement list for Fits: the album's lane first, then two of: Advertising, Reality TV, TV Promo, Documentary, Corporate, Lifestyle, Sports, Gaming, Social.

---

## TUNABLE
The improvement loop may propose edits here, one at a time, after five albums have DRAFT/FINAL pairs. Damir approves by merging.

### Analysis schema (Gemini Call A, one JSON object per track; the Pydantic model in analysis_schema.py is authoritative)
```
analysis_scratchpad: string                  # filled first: start/middle/end, 3 most prominent sources, each ambiguity
mix_type: FULL | SPARSE | SDE
grounding: {first_sound_t, loudest_moment_t, quietest_stretch_t, ends_with_silence_seconds}   # checked against the waveform
sonic_map: {opening_statement, events [{t, kind, spotlight, what_happens, tension}] 3–7, motif {exists, first_heard_t, described, travels ≤5, behaviour}, arc_shape, dialogue_room ≤5, edit_points 1–7, what_it_makes_possible 2–4, composer_intent}   # timestamps warn, never block
tempo: {band: rubato|slow|mid|fast|very_fast, bpm_estimate, pulse_confidence}
energy_arc: static | build | build_drop_build | crest_then_decay | waves
sections: [{t_start, t_end, label, energy 1–5, what_changes}]   # 2–10, ordered, covering ≥90% of the file
ending: {type: hard_cut|button|ring_out|fade_out, final_accent_t, tail_seconds}
instrumentation: [{family, presence: present|uncertain, prominence, confidence, evidence ≤2, note}]   # ≤20; only families heard; unlisted of the 31 = absent
lyrics: {has_intelligible_words, language, sample_phrase}
hybridity_electronic_pct: 0–100
dialogue_friendly: bool
modular_edit_points_t: [seconds]             # ≤8
the_job: string                              # what this track is FOR (the engine)
narrative_map: string                        # A → B → C, with timestamps
genre_tags: [string]                         # 2–6
sounds_like_no_names: string                 # never an artist, composer or film name
```
Call B (Gemini, text only) writes from the sonic map and the actors only — catalog, duration, mix type, sonic_map, tempo band, lead and supporting sources, do_not_claim (every family not heard as present), dialogue_friendly — never the instrument inventory: description, editor_note, keywords (12–18), fits (2–3), scene_named.

### Track description
- A music supervisor's shortlist note: why it works and how to use it. 2–3 sentences, then the Fits line.
- Sentence 1: the moment it serves, then what the music does first — the scene before any instrument. Sentence 2: the conversation — who answers, where the idea travels, where tension compounds or releases, how it ends; at least one timestamp. Sentence 3 (optional; required for EPP): what an editor can do — cut points, VO room, loop, title-card gap, timestamps as m:ss.
- Instruments appear only as actors doing something, never as a list. One adjective per noun at most. Timestamps come from the sonic map only.
- Length before the Fits line: rC and SSC 45–80 words, EPP 35–60.
- No track title in the description. No composer name. No "this track".
- Writer: set by `track_writer` below.

### track_writer
`gemini` — Gemini writes the description from the analysis (Call B, no audio); Claude gates and lightly edits.
Other legal values: `claude_synth`, `claude_edit`. Set by the blind test (M3). Do not change without a recorded test.

### Keywords
- 12–18 per track, Title Case, ≤3 words each, delivered flat.
- Generated from the sonic map, in internal buckets: the moment it serves (2–3), the arc shape in plain words (1), lead actors (2–4), editor actions (3–5, e.g. VO Room Intro, Hard Cut 1:41, Loop Ready), tempo and ending (2), placement words (2–3) — buckets are scaffolding, not output.
- No bare instrument unless it is the soul of the track. No generic sound-design mechanics (riser, hit, boomer, stutter, whoosh).
- Ending type and dialogue-friendliness are keywords when true: Hard Cut Ending, Button Ending, Ring-Out Tail, Dialogue Friendly, Modular.
- EPP: lane first.

### Album description
- One sentence, 6–20 words. No sell. No second person. No list of placements.
- Reference register: "Air Hunger", "Vessel". Read the catalog's last ten album descriptions first; do not repeat their nouns.

### Album names
- Five candidates. Two words preferred, three maximum. No lane words in EPP titles. No "Vol." No colons, dashes or subtitles.
- Reject any candidate that is a song title, a film title, or a phrase already in the catalog.

### MailChimp intro
- 40–70 words, company voice ("we"), one idea, no exclamation marks, no "excited".

### Cover-art prompts (MidJourney, manual)
- Four prompts per album. Narrative-first: a single frame from a story, not a mood board.
- Per-catalog film stock line, then `--v 7.0 --ar 1:1 --sref [URL]` — verify the current MidJourney version flag before use.
- Obey the LOCKED anatomy rule.
- Last line of every prompt set is the DNA gut-check: "Would a poster designer at a studio we work with put this in a portfolio?"

### Few-shot examples
(Claude Code populates from Damir's locked finals: Air Hunger, Vessel, Flexing and Finessing. Three track descriptions and three album descriptions per catalog. No examples from any file older than 2026-06-01.)
Populated 2026-09-12 from the per-album SourceAudio exports saved with the CWR registrations. These show register and specificity, not format: they predate the Fits line, so format always follows "Track description" above. Examples containing a hard-banned word were left out. Only the active catalog's examples are sent.

#### rC
Track: Visceral, rhythmic breathing and low-end drones claw out of claustrophobic silence, then tighten into stuttering risers and synthetic hits until the panic goes full sci-fi. Built as a strict three-act suffocation — isolated panting up front, dread in the middle, terror at the back. Cut it into the moment the air turns against the characters.
Track: Metallic atmosphere establishes isolation and impending dread. This uneasy calm fractures into a rhythmic pursuit, culminating in absolute, crushing panic.
Album: Cinematic trailer cues built on voice and breath for sci-fi and thriller campaigns: contagion, deep space, quarantine, the gasp for air.
Album: High-octane, conceptual, sound design based cues for theatrical marketing in science fiction, thriller, action and suspense genres.
(Sources: rC056_Metadata.csv 2026-07-22, rC055_Metadata Vessel.csv 2026-07-06. A third rC track example was excluded for a banned word.)

#### SSC
(None yet. No locked SSC final dated 2026-06-01 or later exists; the SSC master sheet is dated 2026-03-15.)

#### EPP
Track: Sub-bass-driven trap beat with metallic hits and tight hi-hats. Confident, attitude-forward energy - sports promos, streetwear, esports.
Track: Dark trap instrumental driven by deep sub-bass, rapid hi-hats, and sharp brass stabs. Generates escalating tension and undeniable swagger. Attitude with momentum - streetwear, esports, competitive sports.
Track: Pulsing hip-hop groove with distorted sub-bass and urgent synth textures. Forward-driving - automotive, lifestyle promos, athletic brand spots.
Album: Dark sub-bass hip-hop with swagger - built for sports promos, reality TV, and streetwear spots.
(Source: EPP064_Metadata.csv 2026-07-06.)

---

## Change log
- 0.4 — 2026-09-16 — Prompt redesign (Fable): sonic_map added to the Analysis schema; Call B writes from the sonic map and actors only; Track description and Keywords specs rewritten to the shortlist-note brief.
- 0.3 — 2026-09-14 — Analysis schema: instrumentation is a flat list of observed families (Damir's schema decision); unlisted families are absent.
- 0.2 — 2026-09-14 — v4 gate: the second listen is replaced by waveform verification (LOCKED bullet, by Damir's instruction); Analysis schema block rewritten for the v4 Call A schema; track_writer wording follows Call B.
- 0.1 — 2026-09-12 — first draft, from the Fable planning session. Supersedes Drive pfd-skill v1.0, Dropbox pfd-delivery, RULES.md, EDIT-LOG.md, CHANGELOG.md, the Gemini GEM, GEMINI.md and Council_Personas.json.
