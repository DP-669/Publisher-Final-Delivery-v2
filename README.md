# Publisher Final Delivery (PFD) — how it works
For Damir, Vesna and Craig. Plain English. No code.

## What PFD is
One web app that turns a folder of finished MP3s into the metadata package Vesna ingests into SourceAudio: track descriptions, keywords, album description, album name, MailChimp intro and cover-art prompts. Nobody writes these by hand any more and nobody does them in a chat window.

## What changed in v3 (September 2026)
- **The app checks that the AI actually listened.** Every track gets a real duration check, timestamped events, an ending type and a second independent listen that audits the facts. If the two listens disagree, the track is marked **BLOCKED** and a human must listen. Before v3 a fabricated analysis looked identical to a real one.
- **One rule file.** All writing rules live in `PFD_RULES.md` inside the app's code repository. Change the file, push it, and the app behaves differently. The old Drive skill, Dropbox skill, Gemini GEM and rule/changelog files are retired.
- **EPP has lanes.** Every EPP album belongs to one lane (Sounds Like Trouble, Sounds Like Mischief, …). Album titles stay short; the lane goes into keywords and the Fits line. See `EPP_LANES.md`.
- **Every album is captured.** The app saves what it produced (DRAFT) and Vesna saves what she actually ingested (FINAL). The difference is how the system learns, without anyone logging anything.

## Running an album — Damir (iPad, ~10 minutes)
1. Open the app. Pick the catalog (rC, SSC or EPP).
2. Paste the Dropbox folder link from the intake folder. Run Tab 01. Do nothing while it runs.
3. Look at the status column. **PASSED** rows need no reading. For any **BLOCKED** row: listen to that one file, read what the two listens disagreed on, and either re-run it or type a one-line correction in its box.
4. Tab 02: skim. Fix only what is wrong. Do not polish — polishing teaches the system nothing.
5. Tab 03: confirm the lane (EPP only) and pick the album name. Tabs 04–06: accept or edit.
6. Export ZIP. The DRAFT file is saved automatically.

## After export — Vesna (browser)
1. Download the ZIP. Paste the CSV into the catalog's Master Metadata sheet and make the fixes you always make.
2. Export this album's rows as CSV and upload it in the app sidebar under "Upload FINAL CSV". That upload is the whole feedback step.
3. Ingest to SourceAudio and Harvest Media as usual. Reply to Damir with one line: "imported, no column fixes" or what you had to fix.
4. Once, please: put the exact SourceAudio import column list in Dropbox at `/PFD-App/reference/sourceaudio_columns.txt`. The app will use that order from then on.

## What BLOCKED means
The app could not prove the analysis is real: the duration didn't match the file, an event was timestamped past the end, or the two listens disagreed on a fact (drums, vocals, choir, tempo, ending). It is not a bug. It is the app refusing to guess. A human ear resolves it in under a minute.

## Where things live
- App code and rules: GitHub, `DP-669/Publisher-Final-Delivery-v2`, branch `main`. Pushing to `main` redeploys the app.
- Rules: `PFD_RULES.md` and `EPP_LANES.md` in that repo.
- Captured albums: Dropbox `/PFD-App/albums/<album code>/` — DRAFT, FINAL and DIFF files. Not a release folder; do not clean it.
- Writer tests: Dropbox `/PFD-App/tests/`.
- Nothing lives on Google Drive.

## Changing a rule
Edit `PFD_RULES.md` (the TUNABLE section), bump the version line at the top, push to `main`. Craig can do this in two minutes; Damir can do it in the GitHub web editor by pasting the whole file. The LOCKED section is Damir-only. No rule changes between albums two and five — the system needs five clean albums before the first improvement pass.

## Cover art
MidJourney stays manual. Tab 05 gives four prompts per album. Prompts never ask for hands, faces or full figures — that is where AI images give themselves away. Claude Design templates for typography are a later phase, once all past covers are gathered in one folder.

## Who to call
- App broken or badge red: Craig.
- CSV doesn't import: Vesna adjusts, then uploads FINAL so the app learns.
- Writing rules: Damir, via `PFD_RULES.md`.
