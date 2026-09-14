# Publisher Final Delivery v4 — Setup Guide

## What changed in v4

| Component | v3 | v4 |
|---|---|---|
| Screens | Eight tabs | **Start · Review · Export** |
| Proof it listened | Second listen had to agree TRUE/FALSE on six facts | **One listen with timestamped evidence, checked against the decoded waveform (librosa) and itself: rules G1–G16** |
| Analysis schema | Flat facts, 3–6 events | **31 instrument families (present/absent/uncertain + evidence), sections, ending, tempo, grounding** |
| Track status | PASSED / BLOCKED | **PASSED / PASSED_WITH_UNCERTAINTY / BLOCKED** — uncertainty never blocks |
| Writing | Gemini wrote in the analysis pass | **Call B: Gemini writes from the analysis (no audio); uncertain instruments are never mentioned** |
| Progress | Auto-save to "PFD Progress" | **`/PFD-App/albums/<CODE>/state.json` after every track** |
| Sidebar | Tabs, errors, uploads, learning, model check | **System health only** |

The full list is in `V4_CHANGES.md`. The gate is described in `GATE_FIX.md`.

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

librosa decodes MP3 through soundfile. `ffmpeg` is the fallback decoder; install it locally with your package manager. On Streamlit Cloud, `packages.txt` installs it.

## Step 5: Streamlit Community Cloud

The existing deployment's "Main file path" is `Publisher-Final-Delivery-v2/app.py`, from when the app lived in a subfolder. Community Cloud cannot change that after deployment, so that file forwards to the real `app.py` at the repo root. **Do not delete it — the live app launches through it.** Pushing to `main` redeploys.

---

## Models

At session start the app asks both providers which models exist. It uses the newest **Pro** for listening (Call A) and writing (Call B), and the newest **Opus** for checking and album copy.

The sidebar shows three badges (Listening, Writing, Checking): green = newest model in use, orange = fallback pin (the check failed), red = no key. The pins used when the check fails live in `engine.py` (`DEFAULT_GEMINI_AUDIO_MODEL`, `DEFAULT_CLAUDE_WRITING_MODEL`). Setting `GEMINI_AUDIO_MODEL` or `CLAUDE_WRITING_MODEL` in secrets locks that slot to a specific model.

## Rules

`PFD_RULES.md` is the only rule source. `rules.py` parses it. Every writing call gets the LOCKED section plus the active catalog's block as its system prompt, and task prompts quote the TUNABLE specs. The listen (Call A) deliberately gets no rules and no catalog: only the audio, its duration and its mix type. Change a rule: edit the file, bump the version line, push to `main`.

## Tests

```bash
python -m unittest discover -s . -p "test_*.py" -v
```

No API keys and no network — every provider and Dropbox call is mocked. The suite:
- `test_gate.py` — rules G1–G16, reasons, text rules
- `test_listen.py` — listen → gate → write, retries, fix actions
- `test_waveform.py` — librosa on synthetic WAVs
- `test_rules.py`, `test_lanes.py`, `test_capture.py` (export, DRAFT, DIFF, state.json, no Drive), `test_no_silent_except.py`
- keyword and model-version tests

GitHub Actions runs them on every push to `main` and every pull request.

`scripts/self_agreement.py` measures how consistent Call A is across five runs per config. It calls the real API, so run it by hand.

## Dropbox locations

- `/PFD-App/albums/<ALBUMCODE>/` — `state.json` (progress, saved after every track and edit), DRAFT (app output), FINAL (Vesna's upload), DIFF. Not a release folder; do not clean it.
- `/PFD-App/tests/` — writing-style comparisons.
- `/PFD-App/reference/sourceaudio_columns.txt` — optional column order for the CSV (one column per line).
