# BLOCKED — PFD v3 build (2026-09-12)

A milestone is BLOCKED when its DONE test could not be observed. Code for every item below is built and covered by mocked tests; only the live observation is missing.

## M-C writer-test mode — live render with real Claude text
- **DONE test:** writer-test toggle renders three anonymised versions in a local run.
- **Observed:** Streamlit AppTest of Tab 02 with the toggle on rendered "Track 1", version blocks **1.**, **2.**, **3.**, a pick radio, no track title on screen, no exceptions. All three Claude calls failed visibly (sidebar + page errors), so the blocks showed "this version failed".
- **Why:** the only Claude key on this Mac is `ANTHROPIC_API_KEY` in the shell environment, and Anthropic rejects it: `401 authentication_error: API key is invalid`. `.streamlit/secrets.toml` has no `ANTHROPIC_API_KEY`.
- **Tried:** (1) env key via AppTest — 401 ×3; (2) confirmed no key in secrets.toml. Not retried further: this is a credential, not code.
- **Unblock:** add a working `ANTHROPIC_API_KEY` to `~/rmg-ops/Publisher-Final-Delivery-v2/.streamlit/secrets.toml`, then run `/Users/damirprice/.claude/jobs/f53cfb02/tmp/apptest_writer.py` from the worktree. On the live app (Streamlit Cloud secrets) this works without any local change.

## M-D capture — DRAFT CSV in Dropbox `/PFD-App/albums/TEST/`
- **DONE test:** a local export writes the ZIP and the DRAFT CSV appears in Dropbox, then TEST is deleted.
- **Observed (2026-09-12):** local export wrote `rC_TEST_PFD_Test_Album.zip` (one CSV + four .txt, PFD_Status/PFD_Block_Reasons last, row PASSED).
- **Observed (2026-09-13 re-run):** the new `DROPBOX_APP_KEY` and `DROPBOX_APP_SECRET` (15 characters each) are accepted — Dropbox's error moved from `invalid_client` to `invalid_grant: refresh token is invalid or revoked`. The Dropbox half still did not run; nothing was written, so there was nothing to clean up.
- **Why:** `DROPBOX_REFRESH_TOKEN` (64 characters, unchanged since 2026-09-12) was issued for a different app key or has been revoked. A refresh token only works with the app that issued it.
- **Tried:** (1) direct token refresh with HTTP basic auth — `invalid_grant`; (2) same with client_id/client_secret in the body — `invalid_grant: refresh token is invalid or revoked`; (3) `live_md.py` through `engine.get_dropbox_client()` — `AuthError invalid_access_token` at `users_get_current_account`, before any write. Not retried further: this is a credential, not code.
- **Unblock:** mint a new refresh token for app key `c9r3u232nlb84cq` (SETUP.md Step 2, steps 3–4): open `https://www.dropbox.com/oauth2/authorize?client_id=c9r3u232nlb84cq&token_access_type=offline&response_type=code`, approve, and give the code to a Claude session, which exchanges it, writes `DROPBOX_REFRESH_TOKEN` into `.streamlit/secrets.toml`, and runs `live_md.py` from the worktree. It refuses to run if `/PFD-App/albums/TEST/` already holds files, and deletes only that folder afterwards. If Streamlit Cloud's secrets carry the same old token, the live app's Dropbox features fail the same way — paste the new token there too.

## M-E deploy — live URL HTTP 200 and ntfy
- **DONE test:** after merge to `main`, the live URL returns 200 with a title containing "Publisher Final Delivery".
- **Why blocked:** (1) this build ran as a background job, and background jobs may not merge or push to `main`, so the merge is one click by Damir on the pull request; (2) the live app is viewer-restricted — anonymous requests to `https://publisher-final-delivery-v2-claude-and-gemini.streamlit.app/` (and `/_stcore/health`) get `303` to the Streamlit login, before and after any deploy, so an anonymous HTTP 200 cannot be observed from here.
- **Unblock:** merge the PR; Damir's iPad check in BUILD_REPORT.md is the live observation.
