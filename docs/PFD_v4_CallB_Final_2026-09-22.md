# PFD v4 — Call B, final form (grounded in Damir's shipped finals)
2026-09-22. From Claude Fable, for Cowork → Claude Code. Replaces §3–§6 of "PFD v4 Writing Prompts 2026-09-16". Call A (sonic map + gate) is unchanged.

## 0. What was found, and one correction
- The Gemini transcript Damir exported is **Air Hunger (rC056)**, the album that was briefly "Apnea Threshold." **Vessel is rC055**, a different album by a different composer, released earlier. Both sets of shipped finals were pulled from Dropbox today (`rC056 Air Hunger Metadata.xlsx`; `rC055_Metadata Vessel.csv`).
- **Air Hunger is the target voice.** Its shipped descriptions are the July fusion Damir approved — the richest finals in the catalog. Vessel's are the older two-sentence style. Air Hunger is the model; Vessel is not.
- Why Gemini-in-chat read well and the app did not: the GEM knew the **album concept** ("the breath concept manifests as…") and the **track title**, and it wrote three perspectives that Damir then fused. The app strips title and concept from everything to stop hallucination. Right for the listen, wrong for the writing. Also visible in the transcript: Gemini hallucinated filenames on roughly a third of the uploads. The gate stays; the writing gets its context back.
- Damir's own finals answer the open Fits question: his sparse-mix finals end with **scene-level** tags ("Fits: dialogue-heavy tension, isolation wards, documentary dread"), not media types. Ruling below.

## 1. Inputs to Call B (Python builds this object; nothing else is sent)
```
album_concept      one line typed by Damir on the Start screen; optional; e.g. "Breath and voice as the instrument: contagion, deep space, quarantine."
album_title        working or final title, if known
track_title        the real title — now sent to Call B only, never to Call A
mix_type           FULL | SPARSE | ALT | SDE
alt_descriptor     for ALT: the parenthetical from the filename, e.g. "Stripped Percussion"
sibling_full       for SPARSE/ALT: the already-written FULL description of the same composition
sonic_map          from Call A (opening_statement, events, motif, arc_shape, dialogue_room, edit_points, what_it_makes_possible, composer_intent)
ending, tempo_band, lead_sources, supporting_sources, do_not_claim, dialogue_friendly, hybridity_electronic_pct
catalog            rC | SSC | EPP  (selects the voice block and exemplars)
```
UI change (small, Claude Code): one optional text field "Album concept (one line)" on the Start screen, stored in album state, shown again in Review → Album details. Empty is allowed; the prompt handles it.

## 2. Call B system instruction (replace in full)
```
You are the music supervisor who has just licensed this track and is writing the shortlist note that tells an editor why it works and where to cut it in. You are not describing music. You are handing someone a plan.

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

Before answering, check: Move 1 ends in a dash-statement; at least one timestamp; Move 3 names a scene; Fits has 2–3 scene tags; no forbidden words; every instrument has a verb; nothing from do_not_claim; length in range; concept honoured if given. Fix, then output JSON only.
```

Output schema (unchanged from 09-16): `description`, `editor_note`, `keywords[12–18]`, `fits[2–3]`, `scene_named`.

## 3. Catalog voice blocks (only the active one is sent)
**rC** — A supervisor's shortlist note to a studio marketing team. Direct, physical, built around campaign beats: the reveal, the turn, the title card, the back end. Sound design is deliberate — say what the vacuum cut or the klaxon does for the cut. Move 3 names a campaign moment: "For the instant the seal fails and the air rushes out."

**SSC** — A film programmer's note. Compositional story first: who poses the question, who answers, how long the answer takes, what the composer chose. Instruments are players with intent — "the cello poses", "the harp declines to resolve it". No production language (no drop, hit, sound design); use accent, silence, return. Never "cinematic". Move 3 names a kind of scene: grief that hasn't landed, a reunion that isn't a relief.

**EPP** — An editor's bookmark. Move 1 is one mood word then the groove in actors and verbs; Move 2 is utility with timestamps (the 30, the 15, VO room, loop); Move 3 is the format list in plain words: "Attitude with momentum — streetwear, esports, competitive sports." The lane is the first Fits tag and the first keyword.

## 4. Exemplars (few-shot; send the active catalog's set verbatim)
All rC and EPP exemplars below are Damir's shipped finals, unedited except where a forbidden word is bracketed for the model's benefit.

### rC — full mixes (Air Hunger, rC056, released 2026-07-03)
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

Note to the model: these finals predate the timestamp rule. Yours must add one m:ss timestamp in Move 2. Everything else about them is the standard.

### EPP — full mixes (Flexing and Finessing, EPP064, released 2026-05-24; lane: Sounds Like Trouble)
> **Fitted Up** — Dark trap instrumental driven by deep sub-bass, rapid hi-hats, and sharp brass stabs. Generates escalating tension and undeniable swagger. Attitude with momentum — streetwear, esports, competitive sports.

> **Comeuppance** — Hip-hop groove with resonant sub-bass, crisp trap percussion, and a mysterious synth motif. Quiet confidence — fashion, lifestyle, editorial, true crime docs.

> **New Challenger** — Hip-hop anthem with bold brass swells and stomping drums. Big and triumphant — sports highlights, athletic campaigns, lifestyle features.

> **Money Spread** — Pulsing hip-hop groove with distorted sub-bass and urgent synth textures. Forward-driving — automotive, lifestyle promos, athletic brand spots.

Note to the model: EPP finals are terser than rC on purpose. Yours add Move 2 utility with one timestamp (the 30, VO room, loop) and the Fits line with the lane first; keep the length.

### SSC — no Damir-approved finals exist yet
Send these two provisional exemplars, written to the rules, and replace them with real finals after the first SSC album ships through the app:
> For the scene where the threat is real and the outcome isn't: a low string drone holds while a plucked figure marks time beneath it, and nothing answers for nearly a minute. The harp enters at 1:05 not to reply but to add a second line, so the tension compounds instead of peaking; the figure thins to a single voice and rings out from 2:58. The opening minute alone carries dialogue; the accent at 1:51 makes a cold reveal. Fits: unresolved threat, interrogation rooms, the wait before bad news.

> A solo cello poses a falling three-note question over a held bass and is left alone with it — no reply, no pulse, only air. Strings take the figure up an octave at 1:12 and widen it without resolving it; a single horn answers at 2:04 and the ensemble settles into a ring-out from 2:40. Cut at 1:12 for the turn; the first minute sits under any dialogue. Fits: grief that hasn't landed, a reunion that isn't a relief, period drama interiors.

## 5. Rulings recorded here (log in DECISIONS.md and PFD_RULES.md)
- **Fits = scene-level tags**, lowercase, 2–3, an editor's search terms for a moment. Media placements move to keywords. Source: Damir's shipped Air Hunger sparse finals. Update PFD_RULES.md LOCKED "Fits" and each catalog's "Placement list for Fits" accordingly (the lists become keyword lists).
- **Album concept and track title go to Call B only.** Call A stays blind. Add the Start-screen field.
- **ALT mixes**: fixed prefix + full-mix description, exactly as the shipped finals do. No separate listen for ALTs; they inherit the FULL map and gate result.
- **Exemplars come only from shipped finals.** rC = Air Hunger; EPP = Flexing and Finessing; SSC = provisional until the first app-shipped SSC album, then replaced. Vessel finals are not used as exemplars.
- The three-voice output stays retired; the perspectives live inside Call A's map questions and fuse in Move 1–3.

## 6. Acceptance test (machine-run before Damir reads anything)
Re-run Air Hunger's 13 full mixes through Call A + this Call B with `album_concept = "Breath and voice as the instrument: contagion, deep space, quarantine, the gasp for air."` Score each output against the shipped final with word-level edit distance. Pass if the median distance is lower than the median distance between the shipped finals and the 09-16-prompt outputs (the "slop" baseline) by at least 30 %, and 90 %+ of outputs satisfy the mechanical checks (Move 1 dash-statement present; ≥1 m:ss timestamp; Move 3 opener from the allowed list; 2–3 Fits tags, none a media type; zero forbidden words; nothing from do_not_claim). Report the five furthest tracks. Damir then reads those five — the only human step.

## 7. Cowork instructions
1. Save this file to `/PFD-App/v3-build/` and to the repo `docs/`.
2. Hand it to Claude Code with: "Implement §1 (inputs + Start-screen field), §2–§4 (prompts and exemplars into rules.py/prompts.py), §5 (PFD_RULES.md edits), then run §6 and write the scores to BUILD_REPORT.md. Do not touch Call A or the gate."
3. When §6 passes, ntfy: "PFD: Call B grounded in Air Hunger finals. Median distance −<n>%. Five tracks for Damir to read in Review."
