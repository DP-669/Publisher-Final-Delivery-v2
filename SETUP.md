# Publisher Final Delivery v2 — Setup Guide

## What Changed from v1

| Component | v1 | v2 |
|---|---|---|
| Audio Analysis | Gemini | **Gemini 2.5 Pro** (latest) |
| Track Descriptions | Gemini | **Claude Sonnet** |
| Album Description | Gemini | **Claude Sonnet** |
| Album Name | Gemini | **Claude Sonnet** |
| Cover Art Prompts | Gemini | **Claude Sonnet** |
| MailChimp Intro | Gemini | **Claude Sonnet** |
| Fix Bad Copy | ✗ | **Tab 07: Manual Refinement** |
| Cloud Storage | ✗ | **Dropbox integration** |
| Copy Buttons | ✗ | **All outputs** |

---

## Step 1: Get Your Claude API Key

1. Go to **console.anthropic.com**
2. Create an account (separate from claude.ai — this is the developer platform)
3. Go to **Settings → API Keys → Create Key**
4. Name it "Publisher Final Delivery"
5. Copy and store it securely — it's only shown once
6. Add billing at **Settings → Billing** (pay-as-you-go, cents per album)

---

## Step 2: Get Your Dropbox Access Token

1. Go to **dropbox.com/developers/apps**
2. Create a new app → "Scoped access" → "Full Dropbox"
3. Under Permissions, enable: `files.content.read`, `files.content.write`
4. Go to Settings → Generate access token
5. Copy the token

---

## Step 3: Configure Streamlit Secrets

Create a file at `.streamlit/secrets.toml` in the project root:

```toml
GEMINI_API_KEY = "your-gemini-key-here"
ANTHROPIC_API_KEY = "your-claude-key-here"
DROPBOX_TOKEN = "your-dropbox-token-here"
```

For deployed apps on Streamlit Cloud, add these in the app's **Secrets** settings panel.

---

## Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Step 5: Run Locally

```bash
streamlit run app.py
```

---

## Step 6: Deploy to Streamlit Cloud (for Budapest / Malta teams)

1. Push this repo to GitHub (private)
2. Go to **share.streamlit.io**
3. Connect your GitHub repo
4. Set the main file path to `app.py` (it is at the repo root)

**The existing deployment is different.** It was created when the app lived in a
subfolder, so its Main file path points at `Publisher-Final-Delivery-v2/app.py`.
Community Cloud cannot edit that setting after deployment — changing it means
deleting and redeploying the app, re-entering every secret and reclaiming the
subdomain. Instead, `Publisher-Final-Delivery-v2/app.py` is a forwarder to the
real entrypoint at the repo root. **Do not delete it — the live app launches
through it.** Only a from-scratch redeploy makes it removable.
5. Add your API keys under **Settings → Secrets**
6. Share the app URL with your team — no installation required, browser only

---

## Dropbox Folder Structure (Recommended)

```
/Publisher Final Delivery/
├── /01 Inbox/          ← Drop audio files here
│   ├── Track01.wav
│   └── Track02.mp3
└── /02 Output/         ← App writes ZIP files here
    └── EPP_Touched_Final_Delivery.zip
```

---

## Models

| Slot | Default pin | Set by |
|---|---|---|
| Audio analysis (Tab 01) | `gemini-3.1-pro-preview` | `GEMINI_AUDIO_MODEL` |
| All writing (Tabs 02–07) | `claude-sonnet-5` | `CLAUDE_WRITING_MODEL` |

The defaults live in `engine.py` as `DEFAULT_GEMINI_AUDIO_MODEL` and
`DEFAULT_CLAUDE_WRITING_MODEL`. You do not have to edit code to change them —
add either key to Streamlit secrets and it wins over the default:

```toml
GEMINI_AUDIO_MODEL = "gemini-3.4-pro"
CLAUDE_WRITING_MODEL = "claude-sonnet-6"
```

An environment variable of the same name works too, for local runs.

### Checking for newer models

A pinned model plus a hand-maintained doc goes stale silently. Both providers
publish a live list-models endpoint, so the app asks them instead of trusting
this file.

In the sidebar, under **🤖 Model Pins**, press **Check for newer models**. The
app lists every model your API keys can currently reach and reports:

- a newer version in the same family (a newer Pro supersedes the pinned Pro;
  a newer Flash does not — different family, different tradeoffs)
- the stable build of a preview you are pinned to
- a pin that has disappeared from the provider's list, meaning it is being
  retired and needs attention

**Nothing switches automatically, by design.** A newer ID is not automatically
better: it may be a preview, it may price differently, and on the Gemini side it
may not accept audio input at all. The check tells you what exists; you decide.

To adopt one: set the secret, reboot the app, run a **single** album through it,
and read the output before running a batch.

The logic lives in `models.py`; `test_models.py` covers the version-comparison
rules offline (no API key needed).

---

## Tests

```bash
python -m unittest discover -s . -p "test_*.py" -v
```

32 tests, no API keys and no network — every provider call is mocked. They
cover keyword formatting and the banned-word filter (`test_keyword_engine.py`),
Gemini response parsing and key normalisation (`test_audio_logic.py`), and the
model-version comparison rules (`test_models.py`).

GitHub Actions runs them on every push to `main` and every pull request
(`.github/workflows/tests.yml`).

---

## Tab 07: Fix Existing Copy

Use this tab to fix:
- Intern-written descriptions that are over-hyped
- MailChimp intros that sound like press releases
- Album descriptions with banned words
- Any copy that doesn't match the catalog DNA

Paste → select content type → Run Council Filter → copy or apply to session.
