# DECISIONS — PFD v3 build (2026-09-12)

One line each: what · why · how to reverse. PFD_RULES.md was the tiebreaker throughout.

## Rules
- System prompt = LOCKED + active catalog block (+ EPP lane names for EPP); TUNABLE specs are quoted per task via `rules.tunable()` · PFD_RULES.md says LOCKED + catalog block are injected; keeps every prompt catalog-clean · append `self.tunable_text` in `Rules.system_instruction`.
- Few-shot examples written into PFD_RULES.md TUNABLE as `#### rC/SSC/EPP` blocks from rC056, rC055 and EPP064 exports (all dated after 2026-06-01); version stays 0.1 · the file assigns this to Claude Code, not a rule change · delete the `####` blocks.
- One rC few-shot ("Last Light, No Air") left out; SSC has none · it contains the banned word "massive"; no SSC final after 2026-06-01 exists · add lines to the block.
- v2 reference examples and COUNCIL/CATALOG_DNA text deleted from prompts.py · they contradicted PFD_RULES.md (banned "evocative", lane-in-title EPP names, "Antigravity") · `git show 533b7b8:prompts.py`.
- "Antigravity" rule (no A/An/The first word) removed everywhere · it is not in PFD_RULES.md · add it to PFD_RULES.md and a check in `gate.description_reasons`.
- SSC "trailer (as a lead placement)" is enforced only in the first sentence, Fits tags and first keyword · the qualifier allows it elsewhere · `gate.forbidden_found`.
- SSC "Forbidden jargon" (underscore, bed, stinger) enforced as forbidden words; "cue-sheet language" left to the model · it is not a literal word · `rules.forbidden_placement_words`.
- Film stock per catalog kept in `prompts.FILM_STOCK` (v2 values) · PFD_RULES.md asks for a stock line but names none · write stocks into PFD_RULES.md and read them via rules.py.
- `02_VOICE_GUIDES/Banned_Keywords.txt` still unioned into the keyword filter · an existing test covers it; all its words are already in the LOCKED list · delete the file and `_banned_keywords` extra lines.

## Gate
- Analysis schema adds one field, `description`, beyond the rules block · the `gemini` and `claude_edit` writers need Gemini's text from the same listen; test_rules checks the other keys match the block · remove from `gate.analysis_schema`.
- Temperature 0.3 kept as specified · Google's Gemini 3 guide recommends 1.0 (looping risk); live run on gemini-3.1-pro-preview accepted 0.3 and returned valid JSON; whether it is honoured cannot be observed · set `gate.ANALYSIS_TEMPERATURE = 1.0`.
- Verification call also carries the catalog system instruction · spec: every Gemini call receives it · pass `system_instruction=None` for the verification call in `engine._gemini_json`.
- Verification audits ending type, vocals and choir only and fails on any FALSE; a failure re-runs analysis and verification once · 2026-09-14 calibration: drums and tempo band flipped between two listens of the same file (48/51 BLOCKED), duration is already checked against the file in code; see GATE_FIX.md · add the claims back to `gate.VERIFIED_CLAIMS` and `gate.claims_for`.
- Keyword checks (count 12–18, banned, forbidden) run on keywords after the ban filter/shortener; raw list kept as `keywords_raw` · these are what ships · `engine.analyze_track`.
- Physical/verification reasons are stored per track; keyword and description checks are recomputed on every rerun, and export requires a description · edits in Tab 02 must be able to clear or cause a block · `engine.refresh_status`.
- Alt mixes and cutdowns are not analysed; status follows the parent full mix, they reuse its Fits line, description rules are not applied · their text is a template from folder names, not a listen · `engine.refresh_status` alt branch.
- Sound-design elements use the same gated analysis (mix type SDE); the SDE-specific prompt is deleted · it sent the element name and returned `{"Element_Type": "Unknown"}` on parse failure · git history.
- Schema violation or API failure on a track = a BLOCKED row plus a visible error (sidebar + page) · the run continues and nothing is hidden · `app.analyse_bytes`.
- A human note on a BLOCKED track is exported inside PFD_Block_Reasons; status stays BLOCKED · LOCKED: BLOCKED is never silently converted · add an explicit override field in `capture._block_reasons`.

## Writers and album
- Default writer read from PFD_RULES.md (`gemini`); all three modes implemented · spec · edit `track_writer`.
- Redo in `gemini` mode uses the Claude edit prompt with guidance · re-listening for every redo is slow and costly · `engine.write_track_description`.
- Writer test: the picked version becomes the track description when the test is saved · the tap is a real editorial choice · remove the loop at the end of Tab 02 writer test.
- Model resolution: newest Opus / newest Pro from the live list at session start (cached 6h); an explicit GEMINI_AUDIO_MODEL / CLAUDE_WRITING_MODEL secret locks the model; failure → pins gemini-3.1-pro-preview / claude-sonnet-5 · spec, plus a human lock if a new model misbehaves · set the secret.
- The three sidebar model badges are Analysis, Verification (same Gemini model) and Writing; Dropbox shown separately · spec lists Dropbox status as its own item · `app.model_badge` calls.
- Album description prompt reads `reference/recent_album_descriptions.json` (last ten per catalog, from master sheets, 2026-09-12) · spec: "last ten from the seeded master metadata" · refresh the JSON when albums ship.
- Lane words = every word of every lane name (active and dormant) except "like"/"the"; any EPP name containing one is rejected · strictest reading of "no lane words in EPP titles" · narrow `rules.lane_words`.
- Name generation asks once more when fewer than five pass; names already in the catalog's last ten are rejected · spec wants five · `engine.generate_album_names`.
- Lane is applied in code after "Confirm lane": first keyword, first Fits tag, other lane names stripped, keywords capped at 18 · descriptions are written before Tab 03 · `gate.apply_lane`.
- Before a lane is confirmed, any lane name is accepted as the first EPP Fits tag; after, it must equal the lane · Tab 02 runs before Tab 03 · `gate.fits_reasons`.

## Export and capture
- BLOCKED rows export with PFD_Status and PFD_Block_Reasons; open issues no longer disable the download · the DRAFT must capture everything, and the status column stops anything reading as passed · disable the Tab 08 button when `errors`.
- CSV columns = v2 set + Album + Album Description + PFD_Status, PFD_Block_Reasons last · album description is needed for the DIFF · `capture.BASE_COLUMNS`.
- `/PFD-App/reference/sourceaudio_columns.txt` does not exist yet (checked 2026-09-12); default column order used until Vesna adds it · spec · none needed.
- DRAFT is overwritten on re-export (one DRAFT per album = latest app output); writer tests use add + autorename · one DRAFT to diff against · `capture.write_draft` mode.
- FINAL rows matched to DRAFT by title with SourceAudio header aliases (`TRACK: Description`, `TRACK: Keywords`, `ALBUM: Description`, `TRACK: Title`) · those are the master sheets' real headers · `capture.DIFF_FIELDS`.
- v2 "Upload ZIP to Dropbox album folder" removed · v3 captures the DRAFT in /PFD-App/albums; the ZIP is downloaded · git history.
- Google Drive client libraries removed from requirements · no code used them; nothing may write to Drive · re-add to requirements.txt.
- test_audio_logic.py rewritten to the gated contract (same intents: audio attached, model called, garbage fails loudly, ban filter) · v2 tests asserted the title-in-prompt parser that LOCKED forbids · git history.

## Process
- Merge to `main` is left to Damir as one click on the pull request · this build ran as a background job, and background jobs may not merge or push to main · merge the PR.
- Proposed Cowork tasks (deletes/overwrites outside the repo): none were needed. The only Dropbox write/delete planned is `/PFD-App/albums/TEST/`, created and removed by this build.
