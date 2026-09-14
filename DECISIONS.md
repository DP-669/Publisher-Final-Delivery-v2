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
- Verification fails on any FALSE or when the verifier's own duration is >8% off; a failure re-runs analysis and verification once · spec wording · `gate.disagreements`.
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

---

# DECISIONS — PFD v4 rebuild (2026-09-14)

v3 entries above that mention tabs, the second listen or the writer test are superseded by these. One line each: what · why · how to reverse.

## Branches
- `v3-final` tags `5352af9` (v3-build head), not the `gate-calibration` commit · gate-calibration was the rejected direction · `git tag -f v3-final <sha>`.
- `gate-calibration` branch left in place, local and on GitHub · not asked to delete it · `git push origin --delete gate-calibration`.

## Gate
- measure_waveform decay rewritten · the spec formula returned 0.0 on every file (tested) and would block every ring-out/fade-out via G8 · restore the spec lines in `waveform.measure_waveform`.
- Audible threshold capped at −50 dBFS · `floor + 12` treats a quiet intro as silence on files without digital silence, so G5 false-blocks · drop `AUDIBLE_CAP_DB`.
- quietest_t search ends at the end of sound · trailing silence was reported as the quietest stretch · search `db[start:]` again.
- peaks_t and tempo_bpm added to the measurement · G6 and G10 need them · none.
- G2 allows 0.5 s overlap between touching sections; G1 also flags evidence that ends before it starts · model rounding · `gate.SECTION_SLACK_S = 0`.
- G9 skipped when either side is constant; G10 skipped when librosa finds no tempo · Spearman undefined / nothing to compare · `gate.check_waveform`.
- G15 uses the mix type from the folder, not the model's echo · the folder is ground truth · pass `a.mix_type.value`.
- Retry hints name the failed field, never the measured value · a model told the answer would copy it · `gate._HINTS`.
- G16 names in `reference/known_names.txt`; ordinary-word titles (Dune, Arrival, Joker, Succession, Tron, Drake) left out · they false-match plain descriptions · add them back to the file.
- Call A gets the analyst brief only, not `rules.system_instruction` · spec: no catalog in Call A context · pass the system instruction in `engine.listen`.
- Call B `Writing` schema defined here (voices, description, 12–18 keywords, tip) · the spec named `Writing` without fields · `analysis_schema.Writing`.
- `gemini` writer: if the Claude gate fails, Gemini's text is kept with a "Not checked by Claude." note · a missing Claude key should not block every track; the text still has to pass the code checks · raise in `engine.finish_description`.
- "Tell it what's true" → PASSED with note even if waveform rules still fail; stays BLOCKED only when no analysis returns · spec: "marks PASSED with note" · `engine.track_record`.
- "I'll write it" saves only text that passes the description rules; keywords are typed when there is no analysis for Call B · LOCKED rules still apply to hand-written copy; Call B needs an analysis · `engine.manual_description`.
- PFD_RULES.md LOCKED: only the second-listen bullet was replaced (as instructed). The bullets saying the analysis "receives audio and mix type only" (it now also gets the duration) and "must return duration_seconds, ending_type, 3–6 timestamped events" (now grounding, sections, ending, families) are stale and left for Damir · LOCKED is Damir-only · edit the file.

## UI
- Step bar is three buttons, not segmented_control/radio · neither can disable a single option · swap to `st.segmented_control` without disabling.
- Table rows open via an "Open" checkbox column · `st.data_editor` has no row selection · use `st.dataframe(on_select=...)` and lose inline editing.
- Needs a look = red + amber; Ready = green only · the counts don't overlap · `render_review` filter.
- Export is also disabled while an EPP lane is unconfirmed or tracks are pending · lane-first keywords and Fits can't be checked without the lane; pending tracks would be missing from the CSV · `render_export`.
- Skipped tracks are not exported · "Skip this track" means leave it out · `capture.track_rows`.
- Time estimate uses 45 s per track · the spec example implied ~11 s, well below v3's measured ~28 s listen · `engine.SECONDS_PER_TRACK`.
- persistence.py and feedback.py deleted · replaced by state.json; the redo log had no v4 screen · `git show v3-final:persistence.py`.
- Album details are written on demand with buttons, not automatically · they use Claude and need the track descriptions first · call them at the end of `render_progress`.

## Call A schema path
- Instrumentation is a flat list of Observations (≤ 20, present or uncertain only) with a Python-built 31-family map · Damir's schema decision after Gemini rejected the nested 31-family schema (320 properties) · restore the nested `Instrumentation` as the field type.
- **Path shipped: prompt** (`engine.CALL_A_MODE = "prompt"`): JSON mode, the Analysis JSON Schema in the system instruction, Pydantic validation (violations are G4) · `gemini-3.1-pro-preview` also rejected the flat schema with 400 INVALID_ARGUMENT (base analysis alone OK, Observation list alone OK, the two together rejected even without the enum); the approved fallback rule applies; live, the prompt path returned valid JSON twice within 6000 tokens · set `CALL_A_MODE = "schema"`.
- Duplicate families keep the higher confidence, logged as a warning and recorded in `result["duplicates"]` · spec · `analysis_schema.build_family_map`.
- G17 (present, no evidence) is read from the raw list, and G3 skips evidence-less families so the problem is reported once; its retry hint quotes the family names · spec: "same as G3, one retry quoting the violation" · `gate.check_observations`.
- Call A is never split into several audio calls · Damir: one listen only · none.

## Open
- One live track, BLOCKED on G5/G9/G10. The local waveform check shows the model was wrong on each (silent 1.5 s lead-in, reversed intro energy, 115 vs 68/136 BPM). The block rate across an album is unmeasured: run one small album before touching thresholds.

## Self-agreement runs
Written by scripts/self_agreement.py.
- 2026-09-14 · redcola trailer demo jaed.mp3 · gemini-3.1-pro-preview · a_temp0_topk1: 100.0% (3/5 valid) · b_temp1: 83.9% (4/5 valid)
