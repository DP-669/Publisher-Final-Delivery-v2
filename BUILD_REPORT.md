# PFD v4 — Call B final form: §6 acceptance (2026-09-22) — NOT PASSED

**Result: BLOCKED.** §1–§5 are implemented and audited (auditor PASS; 213 tests OK). §6 failed on the distance criterion on both runs. Per the fail-fast rule, no third prompt variation was tried. Nothing was merged to `main` and no success ntfy was sent.

## Pass criteria vs result (run 2, the final prompt)
- Median word-level edit distance, new vs shipped final: **0.934**. Slop baseline (09-16 prompts at e9f5ca0, same Call A maps): **0.948**. Reduction **1.4%**; the target is ≥30%, which would need a median ≤ 0.664. **FAIL**
- Mechanical checks: **100%** of outputs (12/12). Target ≥90%. **PASS**
- Held-out tracks (the 7 not used as exemplars): new 0.934 vs baseline 0.950, 1.7%.
- Only 12 of 13 tracks were scored. Annihilate's listen returned invalid JSON twice (G4), so there was no map to write from.

Run 1 (the §2–§4 prompt exactly as specified): median 0.925 vs 0.948 (2.4%); mechanical 8%. Most run-1 mechanical failures came from the checker: plain "brass" was counted as orchestral brass, but the maps had synth brass as a lead source. The checker was narrowed for run 2. The real prompt faults were outputs of 64–106 words, extra timestamps, three missing Move 1 dashes and one wrong Move 3 opener. For run 2 a user-turn checklist was added (`prompts.CALL_B_CHECKLIST`: 45–60 words, one timestamp, one-sentence Move 1, the concept not written as labels). The §2 system instruction is still verbatim.

## Per track (normalised word-level edit distance vs the shipped final; Fits line excluded, since shipped full-mix finals have none)
| Track | Listen gate | Baseline (09-16) | Run 1 | Run 2 | Mechanical (run 2) |
|---|---|---|---|---|---|
| Vox Clausa ¹ | BLOCKED | 0.953 | 0.957 | 0.925 | pass |
| Last Light, No Air | BLOCKED | 0.938 | 0.928 | 0.921 | pass |
| Hypoxia | BLOCKED | 0.970 | 0.882 | 0.942 | pass |
| Proximal ¹ | BLOCKED | 0.945 | 0.954 | 0.954 | pass |
| Delicate Matter | BLOCKED | 0.960 | 0.929 | 0.934 | pass |
| Containment Collapse ¹ | PASSED | 0.938 | 0.873 | 0.855 | pass |
| Cryovoid ¹ | BLOCKED | 0.944 | 0.921 | 0.934 | pass |
| Annihilate | — | — | — | — | no analysis (Call A schema error, G4, twice) |
| Tremor | BLOCKED | 0.934 | 0.894 | 0.885 | pass |
| Feral ¹ | BLOCKED | 0.952 | 0.890 | 0.948 | pass |
| Sacrilege | BLOCKED | 0.934 | 0.914 | 0.983 | pass |
| Unleashed | PASSED | 0.950 | 0.959 | 0.954 | pass |
| Splintered Nerve | BLOCKED | 0.955 | 0.939 | 0.910 | pass |

¹ This track's shipped final is one of the Call B exemplars (§4), so its answer leaks into the prompt. Even so, these tracks did not score closer.

## Five furthest tracks (run 2) — for Damir to read in Review
1. **Sacrilege** — 0.983
2. **Proximal** — 0.954
3. **Unleashed** — 0.954
4. **Feral** — 0.948
5. **Hypoxia** — 0.942

## Why the distance barely moves
1. **The listen hears different things from Damir.** The shipped finals are built on breath, foley, hyperventilation and sound design. On most tracks Call A reports brass, strings, choir, piano and synth, and Call B may only write what is in the map. Example: Hypoxia's final is "fading breath foley… organic choking"; its map has synth brass and impacts. A writing prompt can't recover sounds the listen never reported. That is a Call A problem, and Call A was out of scope.
2. **The listen gate blocked 11 of 13 tracks** ({'BLOCKED': 11, 'PASSED': 2}) on G4–G7 and G13: duration, loudness shape and ending checks. The maps used here are the second attempt's. The gate was out of scope and untouched, but the block rate on a real album is now measured, and it is high.
3. **The metric has a floor.** Two independently written 60-word notes about the same track share few words in order. Both prompts sit at 0.93–0.95. A 30% cut needs about a third of the words aligned with Damir's final, which in practice means copying phrasing. The new outputs are closer in shape (dash-statement, three moves, scene Fits, concept carried) but not in wording. A content-overlap measure (shared content words) would separate the two prompts better. That call is Damir's.

## What shipped in this branch
- §1: Call B input gains album_concept, album_title, track_title, alt_descriptor, sibling_full, ending and hybridity_electronic_pct. There is an "Album concept (one line)" field on Start, editable again in Review → Album details.
- §2–§4: the system instruction, voice blocks and exemplar sets are verbatim (the auditor compared exact strings). Only the active catalog's voice and set are sent.
- §5: PFD_RULES.md v0.5, with all five rulings. Fits tags are checked as lowercase scenes that are never a media type. ALT rows inherit `Alt Version Of the Full Mix (<descriptor>) - ` + the FULL mix's description.
- `scripts/acceptance_callb.py` reruns §6. The Call A cache and both runs are in `reference/acceptance/`.

---

# PFD v4 — Call A schema path (updated 2026-09-15)

**Shipped: the schema path** (`engine.CALL_A_MODE = "schema"`, `response_schema=Analysis`). It went live after the list caps above 7 moved from the schema into Python: sections ≤ 10 via G2, edit points trimmed to 8, instrumentation unbounded and logged over 20.

- **Fallback:** any `400 INVALID_ARGUMENT` on Call A re-issues it in prompt mode (widened 2026-09-16). The track is marked `call_a_mode="prompt-fallback"` and the sidebar shows a warning. Every other error raises.
- **Verified** on three real tracks, one per catalog, with zero 400s and all `call_a_mode="schema"`:
  - rC Loaded Gun: BLOCKED, legitimate (G5, G10)
  - SSC Frozen In Motion: PASSED_WITH_UNCERTAINTY
  - EPP EPP056 003 Folk Celebration: PASSED
- **2026-09-14:** the prompt path shipped briefly. Gemini rejected the nested schema and the capped flat schema with `400 INVALID_ARGUMENT`.
- **Details:** GATE_FIX.md → "Call A schema path". The full v4 change list is in V4_CHANGES.md.

The v3 report below is kept as history.

---

# PFD v3 — Build Report (2026-09-12, live checks re-run 2026-09-13)

## Damir's only job afterwards
0. Merge the pull request on GitHub (one green button). This build ran as a background job, which is not allowed to merge to `main` itself. Merging redeploys the app in about three minutes.
1. Open the app on iPad. Sidebar shows "Rules v0.1" and three green badges.
2. Pick a catalog, paste one Dropbox folder link with one real MP3, run Tab 01.
3. Confirm the row shows a duration, timestamped events, an ending type and PASSED or BLOCKED. That is the observation that makes this build DONE.
4. If the live app's Dropbox features fail, paste the new `DROPBOX_REFRESH_TOKEN` from the local secrets file into Streamlit Cloud's secrets.

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
- **Tests:** 98 pass, all mocked (`python -m unittest discover -s . -p "test_*.py"`), plus `py_compile app.py` and the full module import. Re-run 2026-09-13 with pytest: 98 passed in 11 s. New: test_rules, test_gate, test_lanes, test_capture, test_no_silent_except.
- **App boots:** `streamlit run app.py --server.headless true` → `http://localhost:8501` HTTP 200, health `ok`.
- **M-A DONE:** test_rules passes; `grep -c Antigravity *.py` → 0 in every file.
- **M-B DONE (live, real keys, observed twice):** a real 30-second redCola clip saved as `Sunny_Ukulele_Picnic_FULL.mp3`, run on `gemini-3.1-pro-preview` (found live as the newest Pro).
  - 2026-09-12 result: file 30.02 s, model heard 29 s (3.4%), PASSED on the first attempt in 27 s. Events: 0:00 metallic drone · 0:05 sub-bass rumble · 0:13 alarm pulse · 0:20 distorted riser · 0:26 hard cut.
  - 2026-09-13 re-run: file 30.02 s, model heard 29 s (within ±8%), PASSED on the first attempt in 28 s. Events: 0:00 eerie metallic drone and low bass swell · 0:10 mechanical pulse · 0:20 distorted synth blast and stuttering riser · 0:26 abrupt impact and hard cut.
  - Both runs: Hard Cut; no drums, no vocals, no choir; tempo Rubato. The second listen agreed on every claim (all TRUE). Wording differs between runs; the facts, ending and cut point at 0:26 do not.
  - No title leak in either run: zero "sunny", "ukulele" or "picnic" in the model output. It described dark sci-fi/horror sound design, not a picnic.
- **M-D DONE (live, 2026-09-13, after the refresh token was replaced):** `live_md.py` from the worktree signed in as the redCola Dropbox account, exported the M-B track and wrote `rC_TEST_PFD_Test_Album.zip` (one CSV + four .txt). `/PFD-App/albums/TEST/rC_TEST_PFD_Test_Album_DRAFT.csv` appeared in Dropbox (1,425 bytes, PFD_Status/PFD_Block_Reasons last, row PASSED). A hand-edited FINAL uploaded through `save_final_and_diff` wrote `_FINAL.csv` and `_DIFF.md` ("Words changed — track description: 12.5% · keywords: 0.0% · album description: 0.0%"; 7 of 56 words). The folder held only those three files; `/PFD-App/albums/TEST` was then deleted and confirmed gone. The Columns Reference was absent (expected; Vesna has not placed it), so the default column order was used.

## What is BLOCKED and why (details in BLOCKED.md)
- **M-C live render:** the writer-test page renders correctly (Track 1, versions 1/2/3, pick buttons, no title). No `ANTHROPIC_API_KEY` is in the local secrets file and the shell's key is rejected (401), so the three versions showed visible errors instead of text. Works on the live app with its own secrets. Not re-run 2026-09-13: the secrets file still has no Claude key.
- **M-E deploy:** merge is one click by Damir (background-job rule). The live URL is login-protected, so an anonymous HTTP 200 cannot be observed; the iPad check above is the observation.

## Where it lives
- Branch `v3-build` on GitHub `DP-669/Publisher-Final-Delivery-v2`.
- Pull request into `main`: https://github.com/DP-669/Publisher-Final-Delivery-v2/pull/1
