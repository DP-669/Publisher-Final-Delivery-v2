# GATE_FIX — gate calibration (2026-09-14)

A real album run came back 48 of 51 tracks BLOCKED. Three causes, three fixes.

## 1. Second listen audits ending type, vocals and choir only
- Removed from the second listen: drums, tempo band, duration.
- Why: two Gemini listens of the same file disagreed on drums (timpani vs no percussion) and tempo band. That disagreement caused most of the blocks. Duration is already checked against the real file in code (mutagen/ffprobe), so the second listen does not need to hear it.
- Unchanged: the first listen still returns drums and tempo band (PFD_RULES.md Analysis schema). The code checks still run: analysis duration within 8% of the file, no events past the end, title never sent.
- Code: `gate.VERIFIED_CLAIMS`, `gate.claims_for`, `gate.verification_schema`, `gate.parse_verification`, `gate.disagreements` (no longer takes a duration), `engine.analyze_track`, `prompts.verification_prompt`.

## 2. Fits tag matching
- The matcher was already case-insensitive. "documentaries" failed because it is plural; the list has "Documentary".
- Fix: tags are compared on a key that is lowercase, single-spaced and plural-folded (`gate._fits_key`), so "documentaries", "DOCUMENTARY" and "Documentary" all match. The description keeps the tag exactly as written.

## 3. Fits line is a hard requirement in the Gemini prompt
- `prompts.analysis_prompt` now says the description MUST end with `Fits: [tag1], [tag2], [tag3]`, 2–3 tags copied exactly from the active catalog's placement list (the list is included), nothing after it, or the track is BLOCKED.

## Tests
- test_gate.py: disagreement tests now use vocals, choir and ending type. The duration re-run test was replaced by one that checks the second listen asks about ending type, vocals and choir only. Added a Fits case/plural test and a prompt test.
- test_audio_logic.py: the verification prompt assertion now checks "Vocals are absent." instead of "Drums are present."
- DECISIONS.md: the verification line is updated.

## Not changed
- PFD_RULES.md LOCKED still says a second listen "audits the hard facts". It now audits a subset. That section is Damir's to edit.
- BUILD_REPORT.md is a record of the original build and still describes the old second listen.
