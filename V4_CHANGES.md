# V4_CHANGES — PFD v4 vs v3 (2026-09-14)

Branch `v4-rebuild`, cut from `v3-final` (tag on `5352af9`, the v3-build head). The rejected `gate-calibration` branch is untouched.

**Status: built, not live.** Gemini rejects the Call A schema (see GATE_FIX.md → BLOCKER), so a real album cannot be analysed until that is decided.

## Gate
See GATE_FIX.md. In short: the second listen is gone. One listen with timestamped evidence is checked against the decoded waveform and against itself (G1–G16). One re-run, then BLOCKED. Uncertainty gives PASSED_WITH_UNCERTAINTY and never blocks. Call B writes from the analysis and never mentions uncertain instruments.

## Screens: 8 tabs → Start · Review · Export
- **Step bar** at the top: three buttons. Review and Export stay disabled until an album has tracks and nothing is running.
- **New album**, top right, always visible. With unexported changes it shows one yes/no row first.

### Start
- Three large catalog buttons (redCola, Short Story Collective, Ekonomic Propaganda), one link box, one **Analyze album** button.
- **Pre-run check** reads the folder once per link:
  - album code taken from the folder name and shown next to the link; editable only if it can't be read
  - the folder prefix must match the chosen catalog
  - audio files counted, with a time estimate: "SSC042 · 51 audio files found · about 38 minutes", at 45 s per track (`engine.SECONDS_PER_TRACK`)
  - alt mixes and cutdowns counted separately
- **Progress:** "Track 12 of 51 — listening…", a progress bar, a Stop button, and one row per track as it finishes. Progress is saved to `/PFD-App/albums/<CODE>/state.json` after every track. Stop pauses the run; Start then offers Resume or Review. Review opens automatically when the run finishes. ntfy messages go out on completion and on a quota stop.
- **Recent albums** from `/PFD-App/albums/*/state.json`: code, name, date, status, an Open button, and "Upload Vesna's final" once exported (saves FINAL and writes DIFF, as before).

### Review
- **One table:** Open, Status, Track, Description (inline editable), Keywords (inline editable), Ending. Filters: All · Needs a look (red + amber) · Ready (green). It defaults to Needs a look when that isn't empty.
- **Green** = ready. **Amber** = ready with a note; the uncertain instruments are listed, each with **Add it** (Call B rewrite, no re-listen) or **Leave it out**.
- **Red** = blocked. The description is replaced by a plain-language reason. Blocked rows can't be edited in the table.
- **Fix panel** (tick Open on a red row):
  - audio player and the reason sentences
  - **Run again** — a new listen for a listen problem; a Call B rewrite for a text-rule problem
  - **Tell it what's true** — a new listen with the correction; marked PASSED with a note
  - **I'll write it** — an empty box; saved only once the text passes the rules; keywords come from Call B, or are typed when there is no analysis; tagged Manual
  - **Skip this track** — left out of the export
- **Album details** (collapsed, above the table):
  - EPP lane (Suggest, Confirm)
  - album description, with an optional direction
  - five names to pick from
  - MailChimp intro
  - four cover prompts in copyable code blocks
- **Compare writing styles** (Settings toggle): in a track's panel, write three anonymised versions and pick one. Picks are written to `/PFD-App/tests/` on export.

### Export
- Counts: ready, ready with note, blocked, skipped.
- **Export for SourceAudio** stays grey while any track is red. It also stays grey while an EPP lane is unconfirmed or tracks are still pending (both additions to the spec).
- On export: a summary line, the ZIP download and the Dropbox DRAFT path. Album description and name issues are listed but don't stop the export.
- CSV: skipped tracks are left out. `PFD_Block_Reasons` carries the plain reasons for blocked rows and the notes for ready rows (uncertain instruments, corrections, Manual).

### Sidebar
Rules version, three model badges (Listening, Writing, Checking), Dropbox status, and one Settings expander. Nothing else.

## Removed from v3
- Tab 07 Fix Existing Copy
- the redo log and learning pass (`feedback.py`)
- the "PFD Progress" auto-save (`persistence.py`, replaced by state.json)
- the sidebar model check and API-key inputs (keys come from secrets)
- upload-files mode
- the album-description iteration history
- the human note on BLOCKED rows (replaced by the fix panel)
- writer test mode (now Compare writing styles)
- the verification call

## Files
- **Added:** `analysis_schema.py`, `waveform.py`, `pfd_fixtures.py`, `test_listen.py`, `test_waveform.py`, `scripts/self_agreement.py` (not run), `reference/known_names.txt`, `packages.txt` (ffmpeg for Streamlit Cloud), `GATE_FIX.md`, `V4_CHANGES.md`
- **Rewritten:** `gate.py`, `engine.py`, `prompts.py`, `app.py`, `test_gate.py`
- **Changed:** `capture.py` (state.json, recent albums, notes, skipped rows), `requirements.txt` (+ pydantic, librosa, numpy, soundfile; − mutagen), `PFD_RULES.md` 0.2 (LOCKED second-listen bullet replaced as instructed; Analysis schema block; track_writer wording), `test_rules.py`, `test_capture.py`, `test_no_silent_except.py`, the CI import check, README, SETUP, EPP_LANES, DECISIONS
- **Deleted:** `persistence.py`, `feedback.py`, `test_audio_logic.py`

## What was observed
- **Tests:** 149 pass (`python -m unittest discover -s . -p "test_*.py"`), all mocked except `test_waveform.py`, which decodes synthetic WAVs with librosa. `app.py` compiles; every module imports.
- **Browser (local, fixture album, Dropbox and models stubbed):** Review renders the step bar, the health-only sidebar, All (6) · Needs a look (3) · Ready (3), an amber row, and red rows with plain reasons. No server errors.
- **Live:** waveform measurement on one real 71 s redCola full mix took 1.5 s. Call A was rejected by Gemini (the BLOCKER).

## Not observed
- A full live album run: blocked on the schema decision.
- Claude writing: there is no Claude key in the local secrets.
- Real state.json writes to Dropbox (stubbed in the browser demo).
- The Streamlit Cloud deploy with librosa and ffmpeg.
