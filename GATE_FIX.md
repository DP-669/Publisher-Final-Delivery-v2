# GATE_FIX — the v4 gate (2026-09-14)

## Why
A real album run blocked 48 of 51 tracks. In v3 a second Gemini listen had to agree TRUE/FALSE with the first on drums, vocals, choir, tempo band, ending and duration. Some of those facts are genuinely ambiguous (timpani vs "drums"), so two listens to the same file disagreed and real music was blocked.

v4 replaces "two listens must agree" with "one listen must agree with the decoded waveform and with itself", and lets the model answer "uncertain" instead of guessing.

## What changed
- **Call A schema** (`analysis_schema.py`) — implemented exactly as specified. The scratchpad is filled first. 31 instrument families in 7 groups, each present / absent / uncertain, with prominence, confidence and up to 3 timestamped evidence items. Plus grounding, sections, ending, tempo and lyrics.
- **Call A context** — the analyst brief with the measured duration as system prompt. The user text is only "Mix type … Duration … Listen to the whole file." No title, filename, catalog, rules or previous track. Temperature 0, top_p 1, top_k 1, 6000 max tokens.
- **Waveform** (`waveform.py`) — librosa decodes the file and measures: duration, first sound, loudest moment and top-3 peaks, quietest 3 s stretch, trailing silence, end decay, per-second loudness, tempo.
- **Rules** (`gate.py`):

| Rule | Blocks when |
|---|---|
| G1 | a timestamp is outside [0, duration + 0.5 s] (or evidence ends before it starts) |
| G2 | sections overlap, are out of order, or cover < 90% of the file |
| G3 | a present family has no evidence, confidence < 0.6, or no prominence |
| G4 | the JSON does not match the schema |
| G5 | first sound is off by > 1.5 s |
| G6 | loudest moment is > 6 s from the measured loudest and from each of the top-3 peaks |
| G7 | trailing silence is off by > 1.5 s |
| G8 | hard_cut but the file decays > 1.0 s, or ring_out/fade_out but it decays < 1.0 s |
| G9 | Spearman(section energy, measured section loudness) < 0.4, with ≥ 3 sections |
| G10 | a kit or beats are present and neither bpm, bpm/2 nor bpm×2 is within 8% of librosa's tempo (not for rubato) |
| G11 | a kit or beats are present with tempo band rubato |
| G12 | intelligible words without solo_voice_lyrics or choir |
| G13 | choir present, but no evidence mentions voice / vocal / choir |
| G14 | dialogue_friendly with solo_voice_lyrics present |
| G15 | a sound design element with > 2 families present outside sound_design and trailer_impacts |
| G16 | sounds_like_no_names contains a known artist, composer or film |

- **Retry** — any failure re-runs Call A once. For G5–G16 the user text names what failed, never the measured value, so the model cannot copy the answer. A second failure blocks. At most 2 Call A per track.
- **Status** — PASSED, PASSED_WITH_UNCERTAINTY or BLOCKED. Uncertainty never blocks. Uncertain families go to `do_not_claim`, are never mentioned in copy, and are listed in the export.
- **Call B** (Gemini, text only, temperature 0.7) receives the analysis without the scratchpad, plus do_not_claim, the catalog rules and few-shot examples, plus: "You may only mention instruments present in the analysis. Anything in do_not_claim is never mentioned." It writes the three voices, the description, keywords and tip.
- **Reasons** — the app shows plain sentences ("It said the track ends with a hard cut, but the file rings out for 2.4 seconds."), never rule IDs.
- **Fits** — tag matching lowercases both sides (it already did in v3); a test pins it.
- **Removed** — the second listen, the verification schema, the mutagen/ffprobe header read, the ±8% duration rule (the duration is now measured and given to the model).

## Where the build departs from the spec, and why
1. **decay_seconds.** The spec's formula looked for quiet frames *before* the last audible frame, which never exist. It returned 0.0 on every file, including a synthetic 4 s ring-out, so G8 would have blocked every ring-out and fade-out. It now measures from the end of the last loud stretch (within 6 dB of the peak in the final 8 s) to the end of sound. Synthetic check: hard cut 0.05 s, ring-out 3.6 s, fade 3.0 s.
2. **Audible threshold capped at −50 dBFS.** The spec's `floor + 12 dB` treats a quiet intro on a file with no digital silence as silence, so G5 would false-block it.
3. **quietest_t** stops at the end of sound, so trailing silence is never the "quietest stretch".
4. **peaks_t and tempo_bpm** are added to the measurement, because G6 and G10 need them.
5. **G2** allows 0.5 s of rounding overlap between touching sections.
6. **G9** is skipped when either side is constant (Spearman undefined). **G10** is skipped when librosa finds no tempo.
7. **G15** uses the mix type the app knows from the folder, not the model's echo of it.
8. **G16 list** lives in `reference/known_names.txt` (83 entries). Names that are also ordinary words (Dune, Arrival, Joker…) are left out.
9. **Call B's `Writing` schema** was not in the spec: voices first, then description, 12–18 keywords, tip.
10. **"Tell it what's true"** re-runs Call A with the correction in the user text and marks the track PASSED with the note, even if a waveform rule still fails: an editor listened. If no analysis comes back at all, the track stays blocked.

## BLOCKER — Gemini rejects the Call A schema
Observed 2026-09-14 on `gemini-3.1-pro-preview` (the newest Pro on the key):
- A live Call A on one real 71 s redCola full mix returned `400 INVALID_ARGUMENT`. The file was read from Dropbox, nothing was written, and the waveform measured it in 1.5 s.
- Cheap text-only test calls isolated it. Call B's schema is accepted. Small schemas using `max_length`, nullable fields and list limits are accepted. The `Analysis` schema is rejected as `response_schema` and as `response_json_schema`; with or without `top_k`/`candidate_count`; with constraints, titles and descriptions stripped; with evidence lists removed; and with the families flattened to one level.
- The analysis without instrumentation is accepted (33 properties). Base plus any single instrument group is accepted (53–98 properties). Base plus two groups (144 properties) is rejected. **The limit is schema size, somewhere between about 100 and 140 properties.** The spec schema has 320.
- Also observed: thinking tokens count against `max_output_tokens` on this model (a 200-token cap was used up by thinking). 6000 may truncate a full analysis once a schema is accepted.

Mocked tests pass, but live listening cannot work until one of these is chosen:
- **A. Split Call A** into the base analysis plus one call per instrument group: 8 audio calls per track, about 8× the cost and time. The spec schema stays intact; the engine merges the parts.
- **B. One call without constrained decoding.** JSON mode with the schema written into the prompt, validated by the exact Pydantic model; violations re-run through G4. One call per track, but more G4 re-runs are likely. Untested.
- **C. Compact the instrumentation block** (e.g. one short coded string per family, parsed in code) so it fits in one constrained call. This changes the contract.
