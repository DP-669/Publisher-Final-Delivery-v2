# Claude Code — PFD v3 build

Paste this entire file as your first message to Claude Code, opened in the `DP-669/Publisher-Final-Delivery-v2` repo. Put `PFD_RULES.md`, `EPP_LANES.md` and `README.md` from the delivery ZIP in the repo root first.

---

You are building Publisher Final Delivery v3 for redCola Music Group. Read this whole prompt, then `PFD_RULES.md`, `EPP_LANES.md`, `README.md`, and the existing code before writing anything.

## Authority and autonomy

Damir Price has already approved this build. Do not ask him for permission, confirmation, or preferences. He is not a developer and will not read diffs. Decide every ambiguity yourself using `PFD_RULES.md` as the tiebreaker, record the decision in `DECISIONS.md` (one line each: what, why, how to reverse), and keep going. You stop for exactly three things:

1. A required secret is missing locally and you cannot find it in `.streamlit/secrets.toml`, `.env`, or the environment. Ask once, listing every missing key in one message, then wait.
2. An action would delete or overwrite user data outside this repo (Dropbox, Drive). Never do that. Log it as a proposed Cowork task in `DECISIONS.md` instead.
3. You have made four attempts at one problem and it is still failing. Write the problem up in `BLOCKED.md` with everything tried, and move to the next item. No fifth attempt.

"Done" means observed on the live system, not "tests pass". Every milestone below has a DONE test. If a DONE test cannot be observed, the milestone is BLOCKED, written to `BLOCKED.md`, and you continue with the rest.

## Working method

- Branch `v3-build` off `main`. Commit small, message = what changed and why. Never force-push.
- Existing tests must keep passing (`python -m unittest discover -s . -p "test_*.py" -v`). Add tests for everything new. Every external call in tests is mocked — CI has no keys and no network.
- Before merging: run the full suite, `python -m py_compile app.py`, `python -c "import engine, prompts, models, feedback, persistence, dropbox_pipeline, rules"`, and `streamlit run app.py --server.headless true` for 20 seconds with a curl to `http://localhost:8501` returning 200.
- Merge `v3-build` to `main` when all milestones are DONE or BLOCKED. Streamlit Community Cloud redeploys on push. Wait 3 minutes, then fetch the live URL from `SETUP.md` / git remote notes and confirm HTTP 200 and that the page title contains "Publisher Final Delivery".
- Then send one line to ntfy: `curl -d "PFD v3 deployed. BLOCKED items: <n>. Damir: run one real track on iPad." ntfy.sh/Damir-rMG-2026`
- Write `BUILD_REPORT.md`: what shipped, what is BLOCKED and why, and the exact three-step check Damir does on his iPad.

## What you are building — the spec

### A. One rule file, loaded at runtime
- New module `rules.py`: loads `PFD_RULES.md` and `EPP_LANES.md` at startup, parses `## LOCKED`, the active catalog's `### <CODE>` block, and `## TUNABLE`, and exposes `system_instruction(catalog)` and `setting(name)` (e.g. `setting("track_writer")`).
- Every Gemini and Claude call receives `system_instruction(catalog)` as its system prompt. The other two catalogs' blocks are never sent.
- `prompts.py` is reduced to task templates only. Any rule text inside it (banned words, catalog DNA, register guidance, "Antigravity", "Council" persona text) is deleted and replaced by references to `rules.py`. Where prompts.py and PFD_RULES.md disagree, PFD_RULES.md wins.
- Delete: `GEMINI.md`, `02_VOICE_GUIDES/Council_Personas.json`, `dummy_assets/`, `create_dummy_assets.py`, `temp_metadata.csv`, `test_metadata.csv`. Remove every Antigravity reference from code and validator (8 sites at last count).
- The validator's banned list comes from the LOCKED "Hard banned list" line, parsed, not hard-coded.
- Contamination lists come from each catalog's "Forbidden placement words" line, parsed.

### B. The hallucination gate (Gemini analysis)
- Add `mutagen` to `requirements.txt`. Read true duration from the MP3 header before any API call. If the header cannot be read, fall back to `ffprobe` if present, else mark the track BLOCKED with reason `no_duration`.
- The analysis prompt receives audio bytes plus the mix type (FULL / SPARSE / SDE) and the catalog's system instruction. It never receives title, album, composer, or filename. Join the title to the result afterwards in code.
- Use structured output: `response_mime_type="application/json"` and a `response_schema` matching the "Analysis schema" block in PFD_RULES.md. Parse failures are impossible by construction; a schema violation is a hard error shown in the sidebar and the track row.
- Set `temperature` explicitly (start at 0.3; make it a constant with a comment; if the Gemini 3.x thinking model rejects or ignores temperature, log that in DECISIONS.md and proceed).
- Files larger than 15 MB go through the existing Files API upload path, not inline.
- Verification pass: after the first analysis, run a second call with the same audio and a stripped prompt: "Here are claims about this audio. Answer each TRUE or FALSE. Also state the duration in seconds." Claims = drums, vocals, choir, tempo_band, ending_type, and `abs(duration_seconds − real) ≤ 8%`. Any FALSE or a duration miss → re-run the first analysis once. A second failure → status BLOCKED with the disagreeing claims listed.
- Gate checks in code, independent of the model: every `events[].t` ≤ real duration; `abs(duration_seconds − real) ≤ 8%`; keyword count 12–18; no banned words; no forbidden placement words for the catalog. Any failure → BLOCKED with reasons.
- Track status is one of `PASSED | BLOCKED`. It is shown as a column in Tab 01, filterable, and exported as a column in the CSV. A BLOCKED track is never written as if it passed.
- Replace every `except Exception: pass` (11 at last count in engine.py, app.py, persistence.py, feedback.py) on the analysis, generation, export and logging paths with a visible `st.error` and a log line. Keep the app running; never hide the failure.
- The sound-design path returns a hard error on parse failure, not `{"Element_Type": "Unknown"}`.

### C. Who writes what
- Track description and keywords: governed by `setting("track_writer")`. Implement all three modes: `gemini` (Gemini writes the description inside the analysis pass; Claude runs the Cliché Test, contamination check, length check, and edits only broken sentences), `claude_synth` (current behaviour), `claude_edit` (Claude edits Gemini's text under the rules). Default per PFD_RULES.md.
- Album description, five names, MailChimp intro, four cover-art prompts: Claude. Claude reads the catalog's last ten album descriptions (from the seeded master metadata) before writing the album description.
- Writer-test mode: a toggle in the sidebar. When on, Tab 02 shows three anonymised versions per track (the three modes, shuffled, labelled 1/2/3, no titles), Damir taps one per track, and the app writes `/PFD-App/tests/writer_test_<date>.md` to Dropbox with picks and a tally. This is how M3 happens on an iPad with no chat session.
- Claude model: the latest Opus available from the sidebar pin check; fall back to the current pinned model if the check fails. Gemini: the latest Pro with audio from the pin check; fall back to the pinned model.

### D. EPP lanes
- For EPP runs, the app proposes a lane from `EPP_LANES.md` (active lanes first) using the album-level analysis, shows it in Tab 03 with a dropdown to override, and then: lane = first keyword on every track, first Fits tag on every track, and never in the album title or name candidates. Name candidates containing a lane word are rejected before display.

### E. Fits line
- Every track description ends with `Fits: A, B, C` (two or three tags) drawn only from the catalog's "Placement list for Fits". The validator rejects tags outside the list.

### F. Capture
- On export, write `<CATALOG>_<ALBUMCODE>_<album>_DRAFT.csv` to Dropbox `/PFD-App/albums/<ALBUMCODE>/` automatically. This is the untouched app output, including the status column.
- Sidebar: "Upload FINAL CSV" — Vesna uploads the CSV she actually ingested; it is saved as `..._FINAL.csv` in the same folder. On upload, compute per-field word-level edit distance DRAFT vs FINAL and write `..._DIFF.md` next to them, with a one-line summary (percent of words changed per field). Fields: track description, keywords, album description.
- Keep `feedback.py` but its errors are visible (see B).
- Never write to Google Drive.

### G. Export
- One ZIP: one CSV plus the text assets (album description, names, MailChimp, cover prompts as .txt). Remove the six-folder package.
- CSV columns: keep the current SourceAudio-style column set. If `/PFD-App/reference/sourceaudio_columns.txt` exists in Dropbox, use its column order instead (Vesna will place it there). Add `PFD_Status` and `PFD_Block_Reasons` columns at the end.

### H. Cover art
- Tab 05 stays prompt-only (MidJourney is manual). Apply the anatomy rule and the gut-check line from PFD_RULES.md. No image-API integration in this build.

### I. Housekeeping
- `SETUP.md`: rewrite the "What changed" table for v3 and delete Step 2's long-lived access token instructions in favour of the refresh-token flow the code already uses.
- Sidebar: show `PFD_RULES.md` version, the three model badges, Dropbox status, and the count of BLOCKED tracks in the current run.

## Tests you must add (all mocked)
- `test_rules.py`: LOCKED and catalog blocks parse; the other catalogs' text is absent from `system_instruction("rC")`; `setting("track_writer")` reads the file; banned list and forbidden placement lists parse.
- `test_gate.py`: duration mismatch → BLOCKED; event timestamp past duration → BLOCKED; verification FALSE twice → BLOCKED; verification FALSE once then TRUE → PASSED; schema violation → hard error; title never appears in the analysis prompt (assert on the mocked call's contents); forbidden placement word → BLOCKED; Fits tag outside list → validator fails.
- `test_lanes.py`: EPP name candidate containing a lane word is rejected; lane is first keyword and first Fits tag.
- `test_capture.py`: DRAFT written on export; DIFF computed from a DRAFT/FINAL pair with known edits; no Drive calls anywhere (grep test).
- `test_no_silent_except.py`: a grep test asserting zero `except Exception:\s*pass` (and `except:\s*pass`) in engine.py, app.py, persistence.py, feedback.py.

## Milestones and DONE tests
- M-A rules module: DONE when `test_rules.py` passes and `grep -c Antigravity *.py` returns 0.
- M-B gate: DONE when `test_gate.py` passes and a real 30-second MP3 with a deliberately wrong filename, run locally with real keys, returns a duration within 8% and a PASSED/BLOCKED status. If no keys locally → BLOCKED (stop condition 1 applies).
- M-C writers + writer-test mode: DONE when the toggle renders three anonymised versions in a local run.
- M-D lanes, Fits, capture, export: DONE when a local export writes the ZIP and (with keys) the DRAFT CSV appears in Dropbox `/PFD-App/albums/TEST/`. Delete the TEST folder afterwards — that is the one Dropbox write you may clean up, because you created it.
- M-E deploy: DONE when the live URL returns 200 after merge and the ntfy line is sent.

## Damir's only job afterwards (put this at the top of BUILD_REPORT.md)
1. Open the app on iPad. Sidebar shows "Rules v0.1" and three green badges.
2. Pick a catalog, paste one Dropbox folder link with one real MP3, run Tab 01.
3. Confirm the row shows a duration, timestamped events, an ending type and PASSED or BLOCKED. That is the observation that makes this build DONE.

Begin.
