# Publisher Final Delivery (PFD) — how it works
For Damir, Vesna and Craig. Plain English. No code.

## What PFD is
One web app that turns a folder of finished MP3s into the metadata package Vesna ingests into SourceAudio: track descriptions, keywords, album description, album name, MailChimp intro and cover-art prompts. Nobody writes these by hand any more, and nobody does them in a chat window.

## What changed in v4 (September 2026)
- **Three steps instead of eight tabs:** Start, Review, Export.
- **The app checks the AI's listen against the file itself.** Every claim ("drums from 0:20", "rings out at the end", "loudest at 1:02") carries a timestamp. The app measures the audio and blocks a track only when the analysis contradicts the file or itself. When the AI isn't sure about an instrument, it says so. The track still passes, and that instrument is simply never mentioned.
- **One rule file** is unchanged: `PFD_RULES.md`, plus `EPP_LANES.md` for EPP lanes.
- **Every album is captured** as before: the app's DRAFT and Vesna's FINAL, compared automatically.

## Running an album — Damir (iPad)
1. **Start:** tap the catalog, then give the app the audio. Either paste a Dropbox link — an album folder, a folder of loose files, or a single file — or switch to **Upload files** and drop files in from the iPad or a computer. The app shows the album code, how many audio files it found and roughly how long it will take. Tap **Analyze** and leave it. You can stop it and resume later. One file goes through exactly the same listen and checks as a track in an album.
2. **Review:** the table opens on **Needs a look**.
   - **Green** needs nothing.
   - **Amber** is ready, with a note: the app wasn't sure about an instrument. If you can hear it, tap **Add it** and the description is rewritten.
   - **Red** is blocked, with one sentence saying why. Tick **Open**, listen, then tap **Run again**, **Tell it what's true**, **I'll write it**, or **Skip this track**.
   - Fix only what is wrong. Don't polish — polishing teaches the system nothing.
3. **Album details** (above the table): confirm the lane (EPP only), write the album description, pick the name, write the MailChimp intro and the cover prompts.
4. **Export:** tap **Export for SourceAudio** (it stays grey while anything is red). Download the ZIP. The DRAFT is saved to Dropbox automatically.

## After export — Vesna (browser)
1. Download the ZIP. Paste the CSV into the catalog's Master Metadata sheet and make the fixes you always make.
2. Export this album's rows as CSV. In the app, on **Start → Recent albums**, tap **Upload Vesna's final** on that album's row. That upload is the whole feedback step.
3. Ingest to SourceAudio and Harvest Media as usual. Reply to Damir with one line: "imported, no column fixes" or what you had to fix.
4. Once, please: put the exact SourceAudio import column list in Dropbox at `/PFD-App/reference/sourceaudio_columns.txt`. The app will use that order from then on.

## What "blocked" means
The app could not trust the analysis. It put a moment past the end of the file, called a ring-out a hard cut, heard a beat the file doesn't have, or contradicted itself. It is not a bug; it is the app refusing to guess. The red row says exactly what didn't match, and a human ear resolves it in under a minute.

## Where things live
- App code and rules: GitHub, `DP-669/Publisher-Final-Delivery-v2`. Pushing to `main` redeploys the app.
- Rules: `PFD_RULES.md` and `EPP_LANES.md` in that repo.
- Albums: Dropbox `/PFD-App/albums/<album code>/`, holding the progress file (`state.json`), DRAFT, FINAL and DIFF. Not a release folder; do not clean it.
- Writing-style comparisons: Dropbox `/PFD-App/tests/`.
- Nothing lives on Google Drive.

## Changing a rule
Edit `PFD_RULES.md` (the TUNABLE section), bump the version line at the top, push to `main`. The LOCKED section is Damir-only. No rule changes between albums two and five — the system needs five clean albums before the first improvement pass.

## Cover art
MidJourney stays manual. Album details gives four prompts per album, each with a copy button. Prompts never ask for hands, faces or full figures.

## Who to call
- App broken or badge red: Craig.
- CSV doesn't import: Vesna adjusts, then uploads her final so the app learns.
- Writing rules: Damir, via `PFD_RULES.md`.
