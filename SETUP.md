# Publisher Final Delivery v3 — Setup Guide

## What changed in v3

| Component | v2 | v3 |
|---|---|---|
| Rules | Spread across prompts.py, GEMINI.md, Council_Personas.json, Drive/Dropbox skill files | **One file: `PFD_RULES.md`** (+ `EPP_LANES.md`), read at startup |
| Audio analysis | Gemini, given the track title; free-form JSON | **Gemini, audio + mix type only; structured output; title joined afterwards in code** |
| Proof it listened | None | **Real duration check, timestamped events, second independent listen, one re-run** |
| Track status | — | **PASSED or BLOCKED**, shown in Tab 01 and exported (`PFD_Status`, `PFD_Block_Reasons`) |
| Track descriptions | Claude synthesis | **`track_writer` setting: `gemini` / `claude_synth` / `claude_edit`**, plus a blind writer test |
| Models | Pinned Sonnet / Gemini Pro | **Newest Opus and newest Pro, found live; pins are the fallback** |
| EPP | No lanes | **Lane proposed in Tab 03; first keyword and first Fits tag; never in the title** |
| Fits line | Free text | **2–3 tags from the catalog's placement list, validated** |
| Export | CSV + text files | **One ZIP; DRAFT CSV saved to Dropbox automatically** |
| Learning | Redo log | **Vesna uploads FINAL; the app writes a word-level DIFF** |
| Failures | Often silent | **Always shown (page + sidebar error list)** |
| Google Drive | Libraries installed | **Never written to** |

---

## Step 1: API keys

- **Claude:** console.anthropic.com → Settings → API Keys → Create Key. Add billing.
- **Gemini:** aistudio.google.com → Get API key.

## Step 2: Dropbox (refresh token — does not expire)

The app authenticates with a refresh token, which stays valid until revoked. Do not use a short-lived access token.

1. dropbox.com/developers/apps → your app (Scoped access, Full Dropbox). Permissions tab: `account_info.read`, `files.metadata.read`, `files.content.read`, `files.content.write`, `sharing.read`. Adding a scope later does not upgrade an existing refresh token — repeat steps 3–4 after any permission change.
2. Copy the **App key** and **App secret** from the app's Settings tab (15 characters each).
3. In a browser, open (replace `APP_KEY`):
   `https://www.dropbox.com/oauth2/authorize?client_id=APP_KEY&token_access_type=offline&response_type=code`
   Approve, and copy the code shown.
4. Exchange the code once, in a terminal:
   ```bash
   curl https://api.dropbox.com/oauth2/token \
     -d code=THE_CODE \
     -d grant_type=authorization_code \
     -d client_id=APP_KEY \
     -d client_secret=APP_SECRET
   ```
   The JSON response contains `refresh_token`. Keep it.

## Step 3: Secrets

Local runs: `.streamlit/secrets.toml` in the repo root (gitignored). Streamlit Cloud: app → Settings → Secrets.

```toml
GEMINI_API_KEY = "..."
ANTHROPIC_API_KEY = "..."
DROPBOX_APP_KEY = "..."
DROPBOX_APP_SECRET = "..."
DROPBOX_REFRESH_TOKEN = "..."

# Optional: lock a model instead of using the newest one
# GEMINI_AUDIO_MODEL = "gemini-3.1-pro-preview"
# CLAUDE_WRITING_MODEL = "claude-opus-5"
```

Environment variables with the same names also work locally.

## Step 4: Install and run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

`ffprobe` (from ffmpeg) is optional; it is the fallback when an MP3 header cannot be read.

## Step 5: Streamlit Community Cloud

The existing deployment's "Main file path" is `Publisher-Final-Delivery-v2/app.py`, from when the app lived in a subfolder. Community Cloud cannot change that after deployment, so that file forwards to the real `app.py` at the repo root. **Do not delete it — the live app launches through it.** Pushing to `main` redeploys.

---

## Models

At session start the app asks both providers which models exist and uses the newest **Opus** (writing) and the newest **Pro** (audio analysis and verification). The sidebar shows three badges: green = newest model in use, orange = fallback pin (the check failed), red = no key. The pins used when the check fails live in `engine.py` (`DEFAULT_GEMINI_AUDIO_MODEL`, `DEFAULT_CLAUDE_WRITING_MODEL`). Setting `GEMINI_AUDIO_MODEL` or `CLAUDE_WRITING_MODEL` in secrets locks that slot to a specific model. Sidebar → 🤖 Model check → "Re-check models now" refreshes the list.

## Rules

`PFD_RULES.md` is the only rule source. `rules.py` parses it; every model call gets the LOCKED section plus the active catalog's block as its system prompt, and task prompts quote the TUNABLE specs. Change a rule: edit the file, bump the version line, push to `main`.

## Tests

```bash
python -m unittest discover -s . -p "test_*.py" -v
```

No API keys and no network — every provider and Dropbox call is mocked. `test_rules.py` (rule parsing), `test_gate.py` (hallucination gate and validator), `test_lanes.py` (EPP lanes and names), `test_capture.py` (export, DRAFT, DIFF, no Drive), `test_no_silent_except.py`, plus keyword, request and model-version tests. GitHub Actions runs them on every push to `main` and every pull request.

## Dropbox locations

- `/PFD-App/albums/<ALBUMCODE>/` — DRAFT (app output), FINAL (Vesna's upload), DIFF. Not a release folder; do not clean it.
- `/PFD-App/tests/` — writer-test results.
- `/PFD-App/reference/sourceaudio_columns.txt` — optional column order for the CSV (one column per line).
- `/00 production operations/04 sa, hm, cwr, csv/PFD Progress/` — auto-saved sessions.
