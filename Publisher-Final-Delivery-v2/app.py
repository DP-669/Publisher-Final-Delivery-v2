"""
TEMPORARY SHIM — safe to delete once Streamlit Cloud is pointed at ../app.py.

The app used to live in this subfolder, so Streamlit Cloud's "Main file path"
setting still points here. The code moved to the repo root; without this file
that setting resolves to nothing and the deployed app fails to start.

This forwards to the real entrypoint so the live app keeps working until the
setting can be changed in the Streamlit Cloud dashboard.

To remove: set Main file path to `app.py`, reboot the app, delete this folder.
"""
import pathlib
import runpy
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Imports (engine, prompts, models…) and the asset folders are resolved
# relative to the repo root, so both the import path and the working directory
# have to point there before the real app runs.
sys.path.insert(0, str(REPO_ROOT))
import os
os.chdir(REPO_ROOT)

runpy.run_path(str(REPO_ROOT / "app.py"), run_name="__main__")
