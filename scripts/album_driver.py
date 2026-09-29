"""
Album driver — the Mac Studio path (Damir's decision 2026-09-27/28: no new app; the
same engine the Streamlit app runs, driven from the command line so Claude can run
it from a chat linked to the Mac and results stay comparable with the app).

    python3 scripts/album_driver.py <album_folder> --catalog SSC --code SSC022 \
        --title "Nervous Habits" --concept "..." --out <out_dir> [--only "Within The Mist,Warriors Path"]

Steps (PFD_RULES "Album order of work"):
  1. every master in the folder: measure (structure.py) → listen (Call A) → write (Call B)
  2. referee across the album, one redo round with its findings as guidance
  3. state.json + a PFD draft CSV in <out_dir>
Album title, description, track titles and the MailChimp intro run through the same
engine methods when an Anthropic key is present (env ANTHROPIC_API_KEY or Keychain
item "claude-api"); otherwise they are left for the chat, and the CSV says so.

Keys: GEMINI_API_KEY env or Keychain item "gemini-api". Nothing runs on a schedule.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import gate  # noqa: E402
import referee  # noqa: E402
import stems  # noqa: E402
from engine import IngestionEngine, ClaudeError  # noqa: E402

AUDIO = {".aif", ".aiff", ".wav", ".mp3", ".flac"}


def keychain(service: str) -> str:
    try:
        return subprocess.check_output(["security", "find-generic-password", "-s", service, "-w"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def mix_of(name: str) -> str:
    low = name.lower()
    if "sparse" in low or "sparce" in low:
        return "Sparse Mix"
    if re.search(r"\balt\b|\(", low):
        return "Alt"
    return "Full Mix"


def title_of(name: str) -> str:
    base = re.sub(r"\.[^.]+$", "", name)
    base = re.sub(r"\b(full|sparse|sparce)?\s*master(_\d+)?\b", "", base, flags=re.I)
    return re.sub(r"\s+", " ", base).strip(" -_")


def find_masters(folder: Path, only: set):
    files = [p for p in folder.rglob("*") if p.suffix.lower() in AUDIO and "master" in p.name.lower()]
    files = [p for p in files if mix_of(p.name) != "Alt"]
    if only:
        files = [p for p in files if title_of(p.name).lower() in only]
    return sorted(files, key=lambda p: (title_of(p.name).lower(), mix_of(p.name)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--concept", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-album-steps", action="store_true")
    ap.add_argument("--stems", default="", help="root of the composer's stem folders (presence list for the writer)")
    args = ap.parse_args()

    gem = os.environ.get("GEMINI_API_KEY") or keychain("gemini-api")
    cla = os.environ.get("ANTHROPIC_API_KEY") or keychain("claude-api")
    if not gem:
        sys.exit("No Gemini key (env GEMINI_API_KEY or Keychain 'gemini-api').")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    album = json.load(open(state_path)) if state_path.exists() else {}
    album.setdefault("album_code", args.code)
    album.setdefault("catalog", args.catalog)
    album["album_title"] = args.title or album.get("album_title", "")
    album["album_concept"] = args.concept or album.get("album_concept", "")
    album.setdefault("tracks", [])
    done = {(t["Title"], t["Mix Type"]) for t in album["tracks"] if t.get("Track Description")}

    eng = IngestionEngine()
    eng.album_state = album
    only = {s.strip().lower() for s in args.only.split(",") if s.strip()}
    files = find_masters(Path(args.folder), only)
    print(f"{len(files)} masters", flush=True)

    # Full mixes first so a sparse mix can see its sibling's description.
    for p in sorted(files, key=lambda p: 0 if mix_of(p.name) == "Full Mix" else 1):
        title, mix = title_of(p.name), mix_of(p.name)
        if (title, mix) in done:
            print(f"skip {title} [{mix}] (done)", flush=True)
            continue
        t0 = time.time()
        data = p.read_bytes()
        st = stems.stems_for(args.stems, title, mix) if args.stems else None
        if args.stems:
            print(f"   stems: {', '.join(st['labels']) if st and st['labels'] else 'none found'}"
                  + (f"  ({'; '.join(st['anomalies'])})" if st and st.get("anomalies") else ""), flush=True)
        try:
            tr = eng.process_track(title, mix, data, p.suffix.lstrip("."), args.catalog, gem, cla or "",
                                   source_path=str(p), track_id=f"{title}|{mix}", stems=st)
        except Exception as exc:
            print(f"FAILED {title} [{mix}]: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
            continue
        album["tracks"] = [t for t in album["tracks"] if t.get("track_id") != tr["track_id"]] + [tr]
        json.dump(album, open(state_path, "w"), indent=1, default=str)
        s = tr.get("structure") or {}
        print(f"{title} [{mix}] {round(time.time() - t0)} s  gate {tr['PFD_Gate']['status']}  "
              f"sections {[gate.format_time(x) for x in s.get('sections', [])]}  ending {(s.get('ending') or {}).get('type')}",
              flush=True)
        print("   " + (tr.get("Track Description") or tr.get("Gemini Description") or "(no description)"), flush=True)

    print("\nreferee…", flush=True)
    remaining = eng.referee_redo(album, args.catalog, gem, cla or "")
    for f in remaining:
        print(f"   {f['rule']} {f.get('tracks')}: {f['detail']}", flush=True)

    if cla and not args.no_album_steps:
        descs = [referee._body(t) for t in album["tracks"] if referee._body(t)]
        try:
            if not album.get("album_description"):
                album["album_description"] = eng.generate_album_description(descs, args.catalog, cla)
            if not album.get("album_name_candidates"):
                names = eng.generate_album_names(album["album_description"], args.catalog, cla, descs)
                album["album_name_candidates"] = [n["name"] for n in names["names"]]
                album["album_name_rationales"] = {n["name"]: n["rationale"] for n in names["names"]}
            if album.get("album_title") and not album.get("track_title_proposals"):
                album["track_title_proposals"] = eng.generate_track_titles(
                    album["tracks"], album["album_title"], album.get("album_description", ""), args.catalog, cla)
            if album.get("album_title") and not album.get("mailchimp_intro"):
                album["mailchimp_intro"] = eng.generate_mailchimp_intro(
                    album["album_title"], album.get("album_description", ""), args.catalog, cla, descs)
        except ClaudeError as exc:
            print(f"album steps stopped: {exc}", flush=True)
    else:
        album.setdefault("notes", []).append("Album steps (title, description, track titles, MailChimp) left for the chat: no Anthropic key.")

    json.dump(album, open(state_path, "w"), indent=1, default=str)
    write_csv(album, out / f"{args.code} PFD draft.csv")
    print(f"\nsaved {state_path} and the CSV", flush=True)


def write_csv(album, path):
    cols = ["ALBUM: Code", "ALBUM: Title", "ALBUM: Description", "TRACK: Number", "TRACK: Title",
            "TRACK: Original Title (composer)", "TRACK: Version", "TRACK: Duration", "BPM", "Ending",
            "TRACK: Description", "Fits", "Key Words", "Tip", "Status", "Referee", "TRACK: Audio Filename"]
    renames = {r["original"]: r["proposed"] for r in album.get("track_title_proposals") or [] if not r.get("keep")}
    rows = []
    for i, t in enumerate(sorted(album["tracks"], key=lambda t: (t["Title"].lower(), t["Mix Type"])), 1):
        body, tags = gate.split_fits(t.get("Track Description") or t.get("Gemini Description") or "")
        s = t.get("structure") or {}
        new = renames.get(t["Title"], t["Title"])
        rows.append([album.get("album_code"), album.get("album_title"), album.get("album_description", ""), i,
                     new + (" (Sparse)" if t["Mix Type"] == "Sparse Mix" else ""), t["Title"], t["Mix Type"],
                     t.get("Duration", ""), s.get("tempo", ""), (s.get("ending") or {}).get("type", ""),
                     body, ", ".join(tags or []), t.get("Keywords", ""), t.get("Tip", ""), t.get("PFD_Status", ""),
                     "; ".join(f"{f['rule']}: {f['detail']}" for f in t.get("PFD_Referee") or []),
                     os.path.basename(t.get("Source Path", ""))])
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


if __name__ == "__main__":
    main()
