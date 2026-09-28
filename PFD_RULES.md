# PFD_RULES.md
version: 0.7 (draft, 2026-09-28)
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
- The audio-analysis prompt never receives the track title, album name, composer, filename or album concept. It receives audio, mix type and the catalog's one-line "Listen note" (catalog-level, never track-level). The title is joined to the result afterwards, in code.
- The album concept (one optional line typed on the Start screen), the album title and the track title go to the writing call (Call B) only. The listen stays blind.
- Every analysis must return: duration_seconds, ending_type, 3–6 timestamped events, and hard facts (drums present, vocals present, choir present, tempo band, energy arc).
- Duration is checked against the real file. Timestamps past the real duration fail the track.
- Every present claim carries timestamped evidence. Python verifies timing, ending, loudness shape and section ordering against the decoded waveform (librosa). Contradiction with the waveform or with itself blocks the track; uncertainty never does. Exception (Damir, 2026-09-23): G5–G8 (first sound, loudest moment, end silence, ending type) warn instead of block — "Ready with note", with the measured and claimed values — until five albums have DIFF files.
- Measure first (Damir, 2026-09-28): before any model listens, Python measures the file's shape (structure.py: sections, stop-downs, hits, ending and tail, dialogue room, tempo per section, harmonic/percussive weight). The listener receives these facts with the audio and places its events on them; the writer may quote only measured timestamps; the referee (referee.py) checks every written timestamp against them. Timings come from arithmetic, words come from the model.
- Instrument naming follows the listener's confidence (Damir, 2026-09-28): a family is written with its plain name at confidence 0.9 or above, as "<name>-like" between 0.6 and 0.9, and never below 0.6 (uncertain). Altered, processed and hybrid sounds are the norm in these catalogs; "-like" is the honest default, not a weakness.
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
Every track description ends with a Fits line: `Fits: <tag>, <tag>, <tag>` — two or three scene-level tags, lowercase: the moments and situations an editor would search for ("dialogue-heavy tension, isolation wards, documentary dread"). A Fits tag is never a media type (trailer, TV promo, documentary…); media placements go in keywords, from the catalog's "Placement keywords". EPP: the album's lane is the first tag.

### Mixes
- FULL and SPARSE mixes each get their own listen and their own description. A sparse description opens with what is removed or exposed, then what that makes possible; it is never "the full minus X".
- ALT mixes get no listen of their own. They inherit the FULL mix's analysis and gate result, and their description is the fixed prefix `Alt Version Of the Full Mix (<descriptor>) - ` followed by the FULL mix's description unchanged. <descriptor> is the parenthetical from the filename.

### Voice
One consensus voice per track. The three-voice output (editor, supervisor, context) stays retired: the perspectives live inside the listen's map questions and fuse in the description's three moves.

### Human anatomy in cover art
Cover-art prompts never request hands, faces, full human figures, or crowds. Objects, places, weather, materials, macro detail, architecture and light carry the story.

---

## CATALOG DNA

### rC — redCola
Identity: cinematic trailer music and sound design. Theatrical marketing, TV and broadcast promos, film, TV drama. Dark is common, not required — the album leads; bright, uplifting and documentary-leaning albums exist and are described on their own terms.
Allowed placement words: trailer, teaser, theatrical, TV promo, broadcast promo, film, feature, TV drama, prestige TV, documentary, streaming series, sizzle, network promo.
Forbidden placement words: advertising, commercial, brand campaign, corporate, reality TV, unscripted, social, YouTube, lifestyle, esports.
Mix vocabulary: full mix, sparse mix, sound design element (SDE). Sparse and SDE are described as independent listens, never as "the full minus X".
Listen note: This catalog routinely uses processed human breath and voice as instruments.
Placement keywords: Trailer, Teaser, TV Promo, Film, TV Drama, Documentary, Sizzle Reel, Network Promo.

### SSC — Short Story Collective
Identity: traditionally recorded orchestral cinematic music. Film score register. Prestige TV, documentary, arthouse, drama, period. Elegant, emotionally honest, never trailer-loud.
Allowed placement words: film, score, prestige TV, documentary, drama, period, arthouse, streaming series, TV drama, ballet, concert.
Forbidden placement words: trailer (as a lead placement), promo, advertising, commercial, brand, corporate, reality TV, social, sports, thriller, chase, countdown, pursuit, esports, cyberpunk.
Forbidden jargon: underscore, bed, stinger, cue-sheet language of any kind.
Listen note: Orchestral players here use extended techniques (col legno, sul ponticello, harmonics, scratch tone) and sounds are often processed; a struck or scraped string is still a string, not a drum. Human breath and voice occur as instruments.
Placement keywords: Film, Prestige TV, Documentary, Drama, Period, Arthouse, Streaming Series.

### EPP — Ekonomic Propaganda
Identity: broad production music with a fixed set of lanes. Advertising and brand, unscripted and reality TV, scripted TV, TV promos, documentary, corporate, educational, lifestyle, cooking, gaming, YouTube, social.
Allowed placement words: advertising, commercial, brand, campaign, reality TV, unscripted, TV promo, scripted TV, documentary, corporate, educational, lifestyle, cooking, gaming, YouTube, social, sports highlights, streetwear.
Forbidden placement words: trailer, teaser, theatrical, blockbuster, feature-film campaign, studio marketing, Hollywood.
Lanes: every EPP album belongs to exactly one lane from EPP_LANES.md. The lane is the first keyword on every track and the first Fits tag. The lane is NOT part of the album title.
Placement keywords: Advertising, Reality TV, TV Promo, Documentary, Corporate, Lifestyle, Sports, Gaming, Social.

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
instrumentation: [{family, presence: present|uncertain, prominence, confidence, evidence ≤2, note}]   # ≤20; only families heard; unlisted of the 32 = absent
lyrics: {has_intelligible_words, language, sample_phrase}
hybridity_electronic_pct: 0–100
dialogue_friendly: bool
modular_edit_points_t: [seconds]             # ≤8
the_job: string                              # what this track is FOR (the engine)
narrative_map: string                        # A → B → C, with timestamps
genre_tags: [string]                         # 2–6
sounds_like_no_names: string                 # never an artist, composer or film name
```
Call B (Gemini, text only) writes from the sonic map and the actors only — album_concept, album_title, track_title, catalog, duration, mix type, alt_descriptor, sibling_full (a sparse mix's FULL description), sonic_map, ending, tempo band, lead and supporting sources, do_not_claim (every family not heard as present), dialogue_friendly, hybridity_electronic_pct — never the instrument inventory: description, editor_note, keywords (12–18), fits (2–3), scene_named.

### Track description
- A music supervisor's shortlist note: why it works and where to cut it in. Three moves, then the Fits line.
- Move 1 — what the sound does: actors and verbs in time order, ending in a dash and a plain statement of what that adds up to. Move 2 — how it is built for cutting: structure, modularity, negative space, where it breaks, how it ends; at least one timestamp as m:ss. Move 3 — the placement as a scene, one short sentence starting with For / Cut it into / Drop it where / Made for.
- When an album concept is given, at least one move shows how this track carries it, in the track's own terms. Never restate the concept as a label.
- Instruments appear only as actors doing something, never as a list. One adjective per noun at most. Timestamps come from the measured structure only, and there is exactly one: the edit point that matters. Loudness peaks are not events.
- Lead with what the track feels like and what it does, not with numbers; more than one timestamp reads like a manual (Damir, 2026-09-27).
- Never "drums" when the measured weight carrier is harmonic; write hits, strikes or accents. Never "full orchestra" unless confirmed; "thicker arrangement". "Distorted" only for a sound that is actually distorted (amp, crusher), never for a mood.
- No sentence, and no phrase of four words or more, may appear in two descriptions on the same album. The album concept is shown through what the sound does; it is never written as the same line twice.
- SSC: no thriller, chase, countdown, pursuit, trailer, promo, stinger, underscore, bed. The listener's tone words are proposals, never copied.
- Length before the Fits line: rC and SSC 45–80 words, EPP 35–60.
- No track title in the description. No composer name. No "this track".
- Writer: set by `track_writer` below.

### track_writer
`gemini` — Gemini writes the description from the analysis (Call B, no audio); Claude gates and lightly edits.
Other legal values: `claude_synth`, `claude_edit`. Set by the blind test (M3). Do not change without a recorded test.

### Keywords
- 12–18 per track, Title Case, ≤3 words each, delivered flat.
- Generated from the sonic map, in internal buckets: the scene it serves (2–3), the arc in plain words (1), lead actors (2–4), editor utilities (3–5, e.g. VO Room Intro, Hard Cut 1:41, Vacuum Cuts, Loop Ready), tempo and ending (2), media placements from the catalog's Placement keywords (2–3) — buckets are scaffolding, not output.
- No bare instrument unless it is the soul of the track. No generic sound-design mechanics (riser, hit, boomer, stutter, whoosh) — a signature event is fine (Vacuum Cuts, Klaxon, Breath Foley).
- Ending type and dialogue-friendliness are keywords when true: Hard Cut Ending, Button Ending, Ring-Out Tail, Dialogue Friendly, Modular.
- EPP: lane first.

### Album order of work
Track descriptions and keywords → album title → album description → track titles revised to the album's concept → MailChimp intro → cover-art prompts → CSV to Vesna. The album concept is derived from the chosen title and description, then fed back into a second pass on any track whose description or title no longer fits. The same order on the Mac driver and in the app (Damir, 2026-09-28: results must be comparable whichever path runs).

### Album description
- One sentence, 6–20 words. No sell. No second person. No list of placements.
- Reference register: "Air Hunger", "Vessel", "Nervous Habits" (Clockwork strings, held breath and waltzes that lose their footing: elegant music for minds coming apart.). Read the catalog's last ten album descriptions first; do not repeat their nouns.

### Album names
- Ten candidates, each with a one-line rationale. Sound like a movie title everyone relates to at once: simple, real-life, cinematic, original, non-pretentious (Poor Things, Kinds of Kindness register). Plain words with weight; never a dictionary word the reader has to look up; never bombast (Damir, 2026-09-27).
- Two words preferred, three maximum. No lane words in EPP titles. No "Vol." No colons, dashes or subtitles.
- Think from the Fits lines: which high-end film campaigns (Oscar-class, prestige) would these scenes belong to; then name the album as that studio's head of marketing would.
- Reject any candidate that is a song title, a film title, a TV series or a phrase already in the catalog; web-check before locking.

### Track titles
- After the album title and description are chosen, propose a new title for every track whose composer title does not carry the album's concept. Middle path (Damir, 2026-09-27): keep the composer's gravity, lose the abstraction — plain nouns with weight, no jokes (The Verdict, Resting Heart Rate, Clockmaker, Breathing Exercise). Keep an original when it already fits.
- Always deliver original title → new title side by side; nothing goes live until the composer has agreed. Sparse mixes keep the track's name plus "(Sparse)".

### MailChimp intro
- Poster copy, not marketing copy (Damir's locked "RedCola Album Intro Prompt", Apple Notes, 2026-09-28). One to three declarative lines of four to ten words each, one idea, state over action, no track talk, no instrumentation, no genre words, no exclamation marks, no "excited", no "cinematic". Lines read like truths discovered too late; ambiguous scale; inevitable. Then a blank line, "Introducing", and the album title on its own line.
- Exemplars: "Containment was the mistake." / "It does not arrive. It spreads." / "Intelligence was never the danger." (Vessel); "We all have them. / Nobody admits it. / Some end badly. // Introducing / Nervous Habits" (SSC022).

### Cover-art prompts (MidJourney, manual)
- Four prompts per album. Narrative-first: a single frame from a story, not a mood board.
- Per-catalog film stock line, then `--v 7.0 --ar 1:1 --sref [URL]` — verify the current MidJourney version flag before use.
- Obey the LOCKED anatomy rule.
- Last line of every prompt set is the DNA gut-check: "Would a poster designer at a studio we work with put this in a portfolio?"

### Few-shot examples
Exemplars come only from Damir's shipped finals: rC = Air Hunger (rC056); EPP = Flexing and Finessing (EPP064); SSC = provisional (prompts.py) until the first app-shipped SSC album, then replaced by its finals. Vessel (rC055) finals are the older two-sentence style and are not used. Call B's exemplar sets live in prompts.py (docs/PFD_v4_CallB_Final_2026-09-22.md §4); the lines below feed the Claude writers. They predate the timestamp rule and the Fits line, so format always follows "Track description" above. Examples containing a hard-banned word are left out. Only the active catalog's examples are sent.

#### rC
Track: Visceral, rhythmic breathing and low-end drones claw out of claustrophobic silence, then tighten into stuttering risers and synthetic hits until the panic goes full sci-fi. Built as a strict three-act suffocation — isolated panting up front, dread in the middle, terror at the back. Cut it into the moment the air turns against the characters.
Track: Struggling gasps and warning klaxons give way to explosive decompression and grinding metallic distortion — a catastrophic systems failure rendered in sound. Hard-grid disaster cue that escalates from quiet alarm to total breach. For the instant the seal fails and the air rushes out.
Track: Strips away the back-end impacts and leaves you alone with the breath — exposed panting foley, ticking and low drones, an uncomfortable proximity you can't escape. Engineered for dialogue, where the human sound carries the fear and nothing competes with the actors. Fits: dialogue-heavy tension, isolation wards, documentary dread.
Album: Cinematic trailer cues built on voice and breath for sci-fi and thriller campaigns: contagion, deep space, quarantine, the gasp for air.
(Source: rC056 Air Hunger Metadata.xlsx, pulled 2026-09-22. Vessel examples removed 2026-09-22: exemplars come from shipped Air Hunger finals only.)

#### SSC
Track: Sparse, suspenseful opening: high strings and a soft ticking pulse leave room for dialogue. Col legno strings sharpen the pace from 0:50; a drop at 1:20 creates a pregnant pause before a chaotic, thicker back end that fades on a single held note. Fits: stalking scenes, night-street tension, slow-reveal dread
Track: A waltz through paranoia: lopsided pulses, lurching tempo changes and strings that argue with themselves, each section a further step into madness. Eight distinct, colorful passages offer a dialogue-friendly first half and a chaotic back end, with cut points at every turn. Fits: unravelling-mind sequences, paranoia montages, unreliable-narrator reveals
Album: Clockwork strings, held breath and waltzes that lose their footing: elegant music for minds coming apart.
(Source: SSC022 Nervous Habits, Damir's approved texts 2026-09-27. Provisional until the album ships.)

#### EPP
Track: Sub-bass-driven trap beat with metallic hits and tight hi-hats. Confident, attitude-forward energy - sports promos, streetwear, esports.
Track: Dark trap instrumental driven by deep sub-bass, rapid hi-hats, and sharp brass stabs. Generates escalating tension and undeniable swagger. Attitude with momentum - streetwear, esports, competitive sports.
Track: Pulsing hip-hop groove with distorted sub-bass and urgent synth textures. Forward-driving - automotive, lifestyle promos, athletic brand spots.
Album: Dark sub-bass hip-hop with swagger - built for sports promos, reality TV, and streetwear spots.
(Source: EPP064_Metadata.csv 2026-07-06.)

---

## Change log
- 0.7 — 2026-09-28 — Measure first (structure.py before Call A; measured timestamps only in Call B; referee.py cross-checks), instrument naming by confidence (0.9 plain / 0.6–0.9 "-like"), one timestamp per description, no cross-track phrase repeats, album order of work, film-title album names, track-title revision step, MailChimp intro as poster copy (locked note), first SSC exemplars (Nervous Habits).
- 0.6 — 2026-09-23 — Damir's PFD-CALLB-SHIP decision: voice.breath_and_body_foley family added to Call A; rC "Listen note" sent to Call A; G5–G8 warn instead of block until five albums have DIFF files; §6 edit-distance criterion withdrawn.
- 0.5 — 2026-09-22 — Call B final form (docs/PFD_v4_CallB_Final_2026-09-22.md §5): Fits become 2–3 lowercase scene-level tags, never media types; each catalog's "Placement list for Fits" becomes "Placement keywords"; album concept and track title go to Call B only; ALT mixes = fixed prefix + FULL description; exemplars from shipped finals only (Vessel removed); three-voice output stays retired; Track description spec rewritten to the three moves.
- 0.4 — 2026-09-16 — Prompt redesign (Fable): sonic_map added to the Analysis schema; Call B writes from the sonic map and actors only; Track description and Keywords specs rewritten to the shortlist-note brief.
- 0.3 — 2026-09-14 — Analysis schema: instrumentation is a flat list of observed families (Damir's schema decision); unlisted families are absent.
- 0.2 — 2026-09-14 — v4 gate: the second listen is replaced by waveform verification (LOCKED bullet, by Damir's instruction); Analysis schema block rewritten for the v4 Call A schema; track_writer wording follows Call B.
- 0.1 — 2026-09-12 — first draft, from the Fable planning session. Supersedes Drive pfd-skill v1.0, Dropbox pfd-delivery, RULES.md, EDIT-LOG.md, CHANGELOG.md, the Gemini GEM, GEMINI.md and Council_Personas.json.
