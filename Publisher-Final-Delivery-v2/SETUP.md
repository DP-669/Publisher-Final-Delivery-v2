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
4. Set the main file as `app.py`
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

## The Gemini Model

The app uses `gemini-2.5-pro-preview-06-05` for audio analysis.
To update to a newer version when released, change `GEMINI_AUDIO_MODEL` in `engine.py` line 17.

## The Claude Model

The app uses `claude-sonnet-4-6` for all writing.
To update, change `CLAUDE_WRITING_MODEL` in `engine.py` line 18.

---

## Tab 07: Fix Existing Copy

Use this tab to fix:
- Intern-written descriptions that are over-hyped
- MailChimp intros that sound like press releases
- Album descriptions with banned words
- Any copy that doesn't match the catalog DNA

Paste → select content type → Run Council Filter → copy or apply to session.
