# GATE_FIX — the v4 gate (2026-09-14)

## Why
A real album run blocked 48 of 51 tracks. In v3 a second Gemini listen had to agree TRUE/FALSE with the first on drums, vocals, choir, tempo band, ending and duration. Some of those facts are genuinely ambiguous (timpani vs "drums"), so two listens to the same file disagreed and real music was blocked.

v4 replaces "two listens must agree" with "one listen must agree with the decoded waveform and with itself", and lets the model answer "uncertain" instead of guessing.

## What changed
- **Call A schema** (`analysis_schema.py`). The scratchpad is filled first. Instrumentation is a flat list of `Observation`s: only the families heard, each marked present or uncertain, with prominence, confidence, 0–2 timestamped evidence items and a note; at most 20. Also: grounding, sections, ending, tempo, lyrics. This is Damir's schema decision, after the nested 31-family block was rejected by Gemini.
- **Family map.** Python rebuilds the full 31-family map after every Call A; every family not listed is absent. `simplify()`, `walk_families()` and the gate read the map, never the raw list. A family listed twice keeps the higher-confidence entry, and the duplicate is logged and recorded on the result.
- **Call A context.** The system prompt is the analyst brief with the measured duration, plus: "List every family you hear as present or uncertain. Do not list absent families. Never list a family twice." The user text is only mix type and duration. No title, filename, catalog, rules or previous track. One listen per attempt; Call A is never split. Temperature 0, top_p 1, top_k 1, 6000 max tokens.
- **Waveform** (`waveform.py`). librosa measures duration, first sound, loudest moment and top-3 peaks, quietest 3 s stretch, trailing silence, end decay, per-second loudness and tempo.
- **Rules** (`gate.py`):

| Rule | Blocks when |
|---|---|
| G1 | a timestamp is outside [0, duration + 0.5 s], or evidence ends before it starts |
| G2 | sections overlap, are out of order, or cover < 90% of the file |
| G3 | a present family with evidence has confidence < 0.6 or no prominence |
| G4 | the JSON does not match the Pydantic schema |
| G5 | first sound off by more than 1.5 s, compared at the 0.1 s precision the app shows |
| G6 | loudest moment > 6 s from the measured loudest and from each of the top-3 peaks |
| G7 | trailing silence off by > 1.5 s |
| G8 | hard_cut but the file decays > 1.0 s, or ring_out/fade_out but it decays < 1.0 s |
| G9 | Spearman(section energy, measured section loudness) < 0.4, with ≥ 3 sections |
| G10 | kit or beats present, librosa confident in one tempo, and the model's BPM more than 20% away from it and not within 10% of it, its double or its half (not for rubato). Ambiguous tempo is logged, never blocked |
| G11 | kit or beats present with tempo band rubato |
| G12 | intelligible words without solo_voice_lyrics or choir |
| G13 | choir present, but no evidence mentions voice / vocal / choir |
| G14 | dialogue_friendly with solo_voice_lyrics present |
| G15 | a sound design element with > 2 families present outside sound_design and trailer_impacts |
| G16 | sounds_like_no_names contains a known artist, composer or film |
| G17 | an Observation is present with empty evidence (read from the raw list, so it is not also reported as G3) |

- **Retry.** Any failure re-runs Call A once. For G5–G17 the user text names what failed (G17 quotes the family names), never the measured value, so the model cannot copy the answer. A second failure blocks. At most 2 Call A per track.
- **Status.** PASSED, PASSED_WITH_UNCERTAINTY or BLOCKED. Uncertainty never blocks. Uncertain families go to `do_not_claim`, are never mentioned in copy, and are listed in the export.
- **Call B** (Gemini, text only, temperature 0.7) gets the analysis without the scratchpad, plus do_not_claim, the catalog rules and few-shot examples, plus: "You may only mention instruments present in the analysis. Anything in do_not_claim is never mentioned."
- **Reasons.** The app shows plain sentences, never rule IDs.
- **Fits.** Tag matching lowercases both sides; a test pins it.
- **Removed.** The second listen, the verification schema, the mutagen/ffprobe header read, the ±8% duration rule.

## Call A schema path — which one shipped
**Shipped (2026-09-15): the schema path** (`engine.CALL_A_MODE = "schema"`). Call A uses `response_schema=Analysis`.

**List caps above 7 are no longer in the schema; Python enforces them:**
- more than 10 sections fails G2
- edit points are trimmed to 8, with a log line
- more than 20 observations is logged (the instrumentation cap was removed in `a65017c`)

**Automatic fallback:**
- **Trigger:** any `400 INVALID_ARGUMENT` on Call A. Widened 2026-09-16: the message text is not dependable, since the 2026-09-14 schema rejections said only "Request contains an invalid argument."
- **What happens:** the same request is re-issued in prompt mode (JSON Schema in the system instruction, same Pydantic validation). The track is marked `call_a_mode="prompt-fallback"`, a warning is logged, and the sidebar shows "Schema rejected by Gemini — ran in prompt mode; check DECISIONS.md."
- **Every other error** (429, 5xx, network) still raises, so a run stops instead of quietly degrading.

**Verification, 2026-09-15, `gemini-3.1-pro-preview`:** three real tracks, zero 400s, all recorded `call_a_mode="schema"`, no fallback warnings.

| Catalog | Track | Result | Call A attempts | Time |
|---|---|---|---|---|
| rC | Loaded Gun (full mix, mastered) | BLOCKED — G5 first sound 0.0 vs 1.5 s; G10 120 vs 68 BPM | 2 | 72 s |
| SSC | Frozen In Motion (Collin Reyer, master) | PASSED_WITH_UNCERTAINTY — orchestral strings | 1 | 57 s |
| EPP | EPP056 003 Folk Celebration | PASSED | 1 | 42 s |

- **The rC block is legitimate:** the local waveform check on the same file shows digital silence until 1.25 s, and librosa's onset tempi are 68/136/129/144/55, none near 120.

**Gate calibration, 2026-09-16 (Damir).** G5 now compares at the 0.1 s precision the app displays, and G10 only blocks on a tempo librosa is confident about. Re-run of the same three tracks, schema mode, zero 400s: **all three PASSED** — rC "Loaded Gun" (was blocked on G5 by 0.03 s and on G10 against an ambiguous 68/136 pair), SSC "Frozen In Motion", EPP "Folk Celebration". All three files have rival tempo peaks at 0.85–1.00 of the top, so none of them can block on BPM. Two things surfaced that are not gate problems and are open in DECISIONS.md: Gemini does not enforce string `max_length` in schema mode (one Call A came back with a 312-character `narrative_map`, caught as G4, clean on the re-run), and Call B truncated its JSON once on the same track and wrote cleanly the next time.
- **Call B:** valid Writing JSON with 15 keywords on SSC and EPP. The Claude gate was skipped locally (no key), so Gemini's text was kept with a note.

History (the path before 2026-09-15), all on `gemini-3.1-pro-preview`, 2026-09-14:
- **Nested schema** (31 families × 7 groups, 320 properties): 400 INVALID_ARGUMENT in every form. Limit found: base plus one group is accepted, base plus two groups (144 properties) is rejected.
- **Flat observation schema:** also 400. Text-only checks: the base analysis alone is accepted, and the Observation list alone is accepted (with or without the family enum). Base plus list is rejected, even with the enum replaced by a plain string. Under the approved fallback rule, the prompt path ships.
- **Prompt path, live, one real 71 s redCola full mix:** JSON validated against the Pydantic model on both attempts (no G4), inside 6000 tokens including thinking. 60 s for two Call A attempts. The waveform took 1.5 s.
  - Result: BLOCKED after the one allowed re-run, on G5, G9 and G10. Ending (G8), loudest moment (G6) and trailing silence (G7) matched.
  - The local check says the model was wrong, not the gate:
    - G5: the file is digital silence (−106 to −120 dBFS) until 1.25 s and starts at 1.5 s; the model said 0.0 s.
    - G9: the model rated the −34 dBFS intro energy 4 and the −16 dBFS breakdown energy 2.
    - G10: librosa's onset tempi are 68 and 136 (a double pair); the model said 115.
  - Call B was not reached. One track is not a block rate: run a small album before judging the thresholds.

## Where the build departs from the spec, and why
1. **decay_seconds.** The spec's formula returned 0.0 on every file, including a synthetic 4 s ring-out, so G8 would have blocked every ring-out and fade-out. It now measures from the end of the last loud stretch (within 6 dB of the peak in the final 8 s) to the end of sound. Synthetic check: hard cut 0.05 s, ring-out 3.6 s, fade 3.0 s.
2. **Audible threshold capped at −50 dBFS.** `floor + 12 dB` treats a quiet intro on a file with no digital silence as silence, so G5 would false-block.
3. **quietest_t** stops at the end of sound.
4. **peaks_t and tempo_bpm** are added to the measurement, because G6 and G10 need them.
5. **G2** allows 0.5 s of rounding overlap between touching sections.
6. **G9** is skipped when either side is constant. **G10** is skipped when librosa finds no tempo.
7. **G15** uses the mix type the app knows from the folder.
8. **G16 list** lives in `reference/known_names.txt` (83 entries). Ordinary-word titles are left out.
9. **Call B `Writing` schema** (not in the spec): voices, description, 12–18 keywords, tip.
10. **"Tell it what's true"** marks PASSED with the note even if a waveform rule still fails. It stays blocked only when no analysis returns.
11. **Absent families in the map** get confidence 0.0 and no evidence. An uncertain Observation's `note` becomes the family's uncertain reason, shown next to "Add it".
