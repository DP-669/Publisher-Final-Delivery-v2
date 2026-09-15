# V4_CHANGES — PFD v4 vs v3 (2026-09-14)

Branch `v4-rebuild`, cut from `v3-final` (tag on `5352af9`, the v3-build head). The rejected `gate-calibration` branch is untouched.

**Status (2026-09-15):** built, and live-verified on three tracks, one per catalog. Call A runs in schema mode (`response_schema=Analysis`), with an automatic, visible fallback to prompt mode if Gemini rejects the schema (GATE_FIX.md → "Call A schema path"). rC was blocked legitimately; SSC passed with a note; EPP passed. No full album has been run yet.

## Gate
See GATE_FIX.md. In short:
- The second listen is gone. One listen, with timestamped evidence for every present instrument, is checked against the decoded waveform and against itself (G1–G17). One re-run, then BLOCKED.
- Instrumentation comes back as a flat list of observed families; Python rebuilds the 31-family map.
- Uncertainty gives PASSED_WITH_UNCERTAINTY and never blocks.
- Call B writes from the analysis and never mentions uncertain instruments.

## Screens: 8 tabs → Start · Review · Export
- **Step bar** at the top: three buttons. Review and Export stay disabled until an album has tracks and nothing is running.
- **New album**, top right, always visible. With unexported changes it shows one yes/no row first.

### Start
- Three large catalog buttons (redCola, Short Story Collective, Ekonomic Propaganda), one link box, one **Analyze album** button.
- **Pre-run check**, once per link:
  - album code taken from the folder name and shown next to the link; editable only if it can't be read
  - the folder prefix must match the chosen catalog
  - audio files counted, with a time estimate: "SSC042 · 51 audio files found · about 38 minutes", at 45 s per track (`engine.SECONDS_PER_TRACK`; the live track took 60 s with a re-run)
  - alt mixes and cutdowns counted separately
- **Progress:** "Track 12 of 51 — listening…", a progress bar, a Stop button, and one row per track as it finishes. Progress is saved to `/PFD-App/albums/<CODE>/state.json` after every track. Stop pauses the run; Start then offers Resume or Review. Review opens automatically at the end. ntfy messages go out on completion and on a quota stop.
- **Recent albums** from `/PFD-App/albums/*/state.json`: code, name, date, status, an Open button, and "Upload Vesna's final" once exported.

### Review
- **One table:** Open, Status, Track, Description (inline editable), Keywords (inline editable), Ending. Filters: All · Needs a look (red + amber) · Ready (green). It defaults to Needs a look when that isn't empty.
- **Green** = ready. **Amber** = ready with a note; the uncertain instruments are listed with the model's reason, each with **Add it** (Call B rewrite, no re-listen) or **Leave it out**.
- **Red** = blocked, with a plain-language reason in place of the description. Blocked rows can't be edited in the table.
- **Fix panel:**
  - audio player and the reason sentences
  - **Run again** — a new listen for a listen problem; a Call B rewrite for a text-rule problem
  - **Tell it what's true** — a new listen with the correction; marked PASSED with a note
  - **I'll write it** — an empty box; saved only once the text passes the rules; keywords from Call B, or typed when there is no analysis; tagged Manual
  - **Skip this track**
- **Album details** (collapsed): EPP lane, album description, five names, MailChimp intro, four cover prompts with copy buttons.
- **Compare writing styles** (Settings toggle): three anonymised versions per track; picks are written to `/PFD-App/tests/` on export.

### Export
- Counts, then **Export for SourceAudio**. It stays grey while any track is red, an EPP lane is unconfirmed, or tracks are still pending.
- On export: a summary line, the ZIP download and the Dropbox DRAFT path. Skipped tracks are left out. `PFD_Block_Reasons` carries the plain reasons for blocked rows and the notes for ready rows.

### Sidebar
Rules version, three model badges (Listening, Writing, Checking), Dropbox status, one Settings expander.

## Removed from v3
- Tab 07 Fix Existing Copy
- the redo log and learning pass (`feedback.py`)
- the "PFD Progress" auto-save (`persistence.py`)
- the sidebar model check and API-key inputs
- upload-files mode
- the album-description iteration history
- the human note on BLOCKED rows
- writer test mode (now Compare writing styles)
- the verification call

## Files
- **Added:** `analysis_schema.py`, `waveform.py`, `pfd_fixtures.py`, `test_listen.py`, `test_waveform.py`, `scripts/self_agreement.py` (not run), `reference/known_names.txt`, `packages.txt`, `GATE_FIX.md`, `V4_CHANGES.md`
- **Rewritten:** `gate.py`, `engine.py`, `prompts.py`, `app.py`, `test_gate.py`
- **Changed:**
  - `capture.py`: state.json, recent albums, notes, skipped rows
  - `requirements.txt`: + pydantic, librosa, numpy, soundfile; − mutagen
  - `PFD_RULES.md` 0.3: LOCKED second-listen bullet replaced as instructed; Analysis schema block with the flat instrumentation list; track_writer wording
  - `test_rules.py`, `test_capture.py`, `test_no_silent_except.py`, the CI import check
  - README, SETUP, EPP_LANES, DECISIONS, BUILD_REPORT
- **Deleted:** `persistence.py`, `feedback.py`, `test_audio_logic.py`

## What was observed
- **Tests:** 156 pass (`python -m unittest discover -s . -p "test_*.py"`), all mocked except `test_waveform.py` (librosa on synthetic WAVs). `app.py` compiles; every module imports.
- **Browser (local fixture album, Dropbox and models stubbed):** Start, Review and Export render.
  - Review: filter counts, amber and red rows with plain reasons; ticking Open shows the fix panel with audio, the reason sentence and the four actions.
  - Export: counts, the blocked warning, the grey Export button.
  - Start: catalog buttons, link box, disabled Analyze, Recent albums.
  - No server errors.
- **Live Gemini** (one 71 s redCola full mix, read from Dropbox, nothing written): as described in GATE_FIX.md.

## Not observed
- A full album run.
- Claude writing (no Claude key in the local secrets).
- Call B on real audio: the one live track was blocked before writing.
- Real state.json writes to Dropbox.
- The Streamlit Cloud deploy with librosa and ffmpeg.
