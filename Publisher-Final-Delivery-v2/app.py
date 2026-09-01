"""
DO NOT DELETE — this is the entrypoint Streamlit Cloud actually launches.

The deployed app
(publisher-final-delivery-v2-claude-and-gemini.streamlit.app) was created with
its "Main file path" set to this location, back when the whole app lived in
this subfolder. Community Cloud does not let that setting be edited after
deployment — the only way to change it is to delete and redeploy the app, which
would mean re-entering every secret and reclaiming the subdomain. Not worth it.

So the code lives at the repo root, where it belongs, and this file forwards to
it. It is deliberate, not leftover. Deleting it takes the live app down.

If the app is ever redeployed from scratch, set Main file path to `app.py` and
this folder can go.
"""
import os
import pathlib
import runpy
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Imports (engine, prompts, models…) and the asset folders (01_VISUAL_REFERENCES,
# 02_VOICE_GUIDES) are both resolved relative to the repo root, so the import
# path and the working directory have to point there before the real app runs.
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

runpy.run_path(str(REPO_ROOT / "app.py"), run_name="__main__")
