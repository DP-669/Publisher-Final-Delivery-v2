# PFD v3 — Build Report (2026-09-12)

## Damir's only job afterwards
0. Merge the pull request on GitHub (one green button). This build ran as a background job, which is not allowed to merge to `main` itself. Merging redeploys the app in about three minutes.
1. Open the app on iPad. Sidebar shows "Rules v0.1" and three green badges.
2. Pick a catalog, paste one Dropbox folder link with one real MP3, run Tab 01.
3. Confirm the row shows a duration, timestamped events, an ending type and PASSED or BLOCKED. That is the observation that makes this build DONE.

Pull request: see "Where it lives" below.

---

## What shipped
- **One rule file.** `rules.py` parses `PFD_RULES.md` and `EPP_LANES.md` at startup. Every Gemini and Claude call gets LOCKED + the active catalog's block as its system prompt; the other catalogs' blocks are never sent. `prompts.py` is task wording only. The banned list, forbidden placement words and Fits lists are parsed from the markdown, not hard-coded. GEMINI.md, Council_Personas.json, dummy assets and temp CSVs are deleted; "Antigravity" appears nowhere.
- **Hallucination gate.** True duration is read from the file (mutagen, ffprobe fallback) before any API call. Gemini gets audio + mix type only, with structured JSON output validated against the Analysis schema; the title is joined afterwards in code. A second, stripped TRUE/FALSE listen audits drums, vocals, choir, tempo band, ending type and duration; one disagreement re-runs, a second BLOCKS. Code checks events vs duration, duration ±8%, 12–18 keywords, banned and forbidden words. Files over 15 MB go through the Files API.
- **PASSED / BLOCKED** is a column in Tab 01 (filterable, with reasons, re-run button, human note) and in the CSV (`PFD_Status`, `PFD_Block_Reasons`). Sound-design elements go through the same gate. Schema violations are hard errors, shown on the page, in the sidebar and on the row.
- **No silent failures.** All `except …: pass` sites on the analysis, generation, export and logging paths now show `st.error`, log, and keep the app running. Claude errors raise instead of being saved as copy.
- **Writers.** `track_writer` = `gemini` (default from the rules file), `claude_synth` or `claude_edit`. Album description (reads the catalog's last ten from the master sheets), five names, MailChimp and four cover prompts are Claude. Writer test mode: sidebar toggle → three anonymised versions per track → tap → `/PFD-App/tests/writer_test_<date>.md` with picks and tally.
- **Models.** Newest Opus and newest Pro are found live at session start; pins are the fallback; a secret can lock either. Three sidebar badges.
- **EPP lanes.** Tab 03 proposes a lane from the album analysis, with a dropdown (active lanes first). On confirm, the lane becomes the first keyword and first Fits tag on every track. Name candidates containing a lane word are rejected before display.
- **Fits line** validated: 2–3 tags from the catalog's list (EPP: lane first).
- **Capture.** Export writes `<CATALOG>_<ALBUMCODE>_<album>_DRAFT.csv` to `/PFD-App/albums/<ALBUMCODE>/`. The sidebar "Upload FINAL CSV" saves `_FINAL.csv` and writes `_DIFF.md` (word-level edit distance per field, one-line summary). It recognises the master sheets' `TRACK: Description` / `TRACK: Keywords` / `ALBUM: Description` headers. Nothing touches Google Drive.
- **Export.** One ZIP: one CSV plus Album_Description, Album_Names, MailChimp_Intro and Cover_Art_Prompts .txt files. Uses `/PFD-App/reference/sourceaudio_columns.txt` order when Vesna adds it (it does not exist yet).
- **Cover art.** Prompt-only, with the anatomy rule and gut-check line; the page flags any hands, faces or figures that slip in.
- **Housekeeping.** SETUP.md rewritten (v3 table; refresh-token Dropbox flow checked against Dropbox's docs). Few-shot examples populated in PFD_RULES.md TUNABLE from July 2026 finals. DECISIONS.md lists every judgment call.

## What was observed
- **Tests:** 98 pass, all mocked (`python -m unittest discover -s . -p "test_*.py"`), plus `py_compile app.py` and the full module import. New: test_rules, test_gate, test_lanes, test_capture, test_no_silent_except.
- **App boots:** `streamlit run app.py --server.headless true` → `http://localhost:8501` HTTP 200, health `ok`.
- **M-A DONE:** test_rules passes; `grep -c Antigravity *.py` → 0 in every file.
- **M-B DONE (live, real keys):** a real 30-second redCola clip saved as `Sunny_Ukulele_Picnic_FULL.mp3`, run on `gemini-3.1-pro-preview`:
  - Result: file 30.02 s, model heard 29 s (3.4%), PASSED on the first attempt in 27 s.
  - Events: 0:00 metallic drone · 0:05 sub-bass rumble · 0:13 alarm pulse · 0:20 distorted riser · 0:26 hard cut.
  - Ending and facts: Hard Cut; no drums, no vocals, no choir; tempo Rubato. The second listen agreed on every claim.
  - No title leak: zero "sunny", "ukulele" or "picnic" in the model output. It described dark sound design, not a picnic.
- **M-D local half:** export ZIP built from that live track; validator clean; CSV status columns last.

## What is BLOCKED and why (details in BLOCKED.md)
- **M-C live render:** the writer-test page renders correctly (Track 1, versions 1/2/3, pick buttons, no title). The Claude key on this Mac is rejected (401), so the three versions showed visible errors instead of text. Works on the live app with its own secrets.
- **M-D Dropbox half:** the Dropbox app key and secret in the local secrets file are 7 characters (real ones are 15). Dropbox says `invalid_client`, so nothing was written and there was nothing to clean up.
- **M-E deploy:** merge is one click by Damir (background-job rule). The live URL is login-protected, so an anonymous HTTP 200 cannot be observed; the iPad check above is the observation.

## Where it lives
- Branch `v3-build` on GitHub `DP-669/Publisher-Final-Delivery-v2`, pull request into `main`.
