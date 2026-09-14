# BLOCKED — PFD v3 build (2026-09-12)

A milestone is BLOCKED when its DONE test could not be observed. Code for every item below is built and covered by mocked tests; only the live observation is missing.

## M-C writer-test mode — live render with real Claude text
- **DONE test:** writer-test toggle renders three anonymised versions in a local run.
- **Observed:** Streamlit AppTest of Tab 02 with the toggle on rendered "Track 1", version blocks **1.**, **2.**, **3.**, a pick radio, no track title on screen, no exceptions. All three Claude calls failed visibly (sidebar + page errors), so the blocks showed "this version failed".
- **Why:** the only Claude key on this Mac is `ANTHROPIC_API_KEY` in the shell environment, and Anthropic rejects it: `401 authentication_error: API key is invalid`. `.streamlit/secrets.toml` has no `ANTHROPIC_API_KEY`.
- **Tried:** (1) env key via AppTest — 401 ×3; (2) confirmed no key in secrets.toml. Not retried further: this is a credential, not code.
- **Unblock:** add a working `ANTHROPIC_API_KEY` to `~/rmg-ops/Publisher-Final-Delivery-v2/.streamlit/secrets.toml`, then run `/Users/damirprice/.claude/jobs/f53cfb02/tmp/apptest_writer.py` from the worktree. On the live app (Streamlit Cloud secrets) this works without any local change.

## M-D capture — resolved 2026-09-13
Observed live after the Dropbox refresh token was replaced; details in BUILD_REPORT.md → M-D DONE. If Streamlit Cloud's secrets still carry the old token, the live app's Dropbox features will fail until the new one is pasted there.

## M-E deploy — live URL HTTP 200 and ntfy
- **DONE test:** after merge to `main`, the live URL returns 200 with a title containing "Publisher Final Delivery".
- **Why blocked:** (1) this build ran as a background job, and background jobs may not merge or push to `main`, so the merge is one click by Damir on the pull request; (2) the live app is viewer-restricted — anonymous requests to `https://publisher-final-delivery-v2-claude-and-gemini.streamlit.app/` (and `/_stcore/health`) get `303` to the Streamlit login, before and after any deploy, so an anonymous HTTP 200 cannot be observed from here.
- **Unblock:** merge the PR; Damir's iPad check in BUILD_REPORT.md is the live observation.
