"""
§6 acceptance test for Call B, final form (docs/PFD_v4_CallB_Final_2026-09-22.md).

Air Hunger (rC056), 13 full mixes: Call A once per track (cached), then the
09-16 Call B (git HEAD~ prompts + PFD_RULES v0.4, the "slop" baseline) and the
current Call B on the same sonic map. Each output's description body (Fits line
removed; the shipped full-mix finals have none) is scored against the shipped
final with normalised word-level edit distance, and the new outputs are run
through the mechanical checks.

    python3 scripts/acceptance_callb.py <mp3_dir> <finals.xlsx> <out.json> [--baseline-ref e9f5ca0]

Needs GEMINI_API_KEY (env or .streamlit/secrets.toml). Call A results are cached
in <out.json>.calla.json so prompt iterations do not listen again.
"""
import concurrent.futures as cf
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gate  # noqa: E402
import rules  # noqa: E402
from engine import CALL_B_CONFIG, IngestionEngine, _secret_value  # noqa: E402

CONCEPT = "Breath and voice as the instrument: contagion, deep space, quarantine, the gasp for air."
ALBUM = {"album_concept": CONCEPT, "album_title": "Air Hunger", "sibling_full": ""}
EXEMPLAR_TRACKS = {"Annihilate", "Containment Collapse", "Cryovoid", "Feral", "Proximal", "Vox Clausa"}
MOVE3_OPENERS = ("for ", "cut it into ", "drop it where ", "made for ")
FORBIDDEN = ["epic", "huge", "massive", "awesome", "badass", "evocative", "haunting", "lush", "atmospheric",
             "soaring", "sweeping", "ethereal", "perfect", "seamless", "elevate", "journey", "builds tension",
             "sonic landscape", "sense of", "perfectly engineered", "designed specifically for",
             "engineered specifically for", "tailored specifically for", "proud to announce", "excited to share",
             "cinematic"]
# do_not_claim families → words that would claim them. Generic words (textures, pulse, hits) are left out.
CLAIM_WORDS = {
    "percussion.drum_kit": ["drum kit", "snare", "hi-hat", "hi-hats", "kick drum"],
    "percussion.electronic_beats": ["trap", "drum machine", "programmed beat"],
    "percussion.orchestral_percussion": ["timpani", "orchestral percussion"],
    "percussion.trailer_impacts": ["impacts", "boomer", "boomers"],
    "percussion.hand_and_world_percussion": ["taiko", "hand drum", "tabla", "frame drum"],
    "strings.orchestral_strings": ["strings", "string section", "violins", "violas"],
    "strings.solo_bowed_string": ["cello", "violin", "viola"],
    "strings.synth_string_pad": ["string pad"],
    "strings.harp": ["harp"],
    "strings.acoustic_guitar": ["acoustic guitar"],
    "strings.electric_guitar": ["electric guitar", "guitar"],
    "strings.world_plucked": ["oud", "koto", "sitar"],
    "keys_and_synths.piano": ["piano"],
    "keys_and_synths.electric_piano_or_organ": ["organ", "rhodes", "electric piano"],
    "keys_and_synths.synth_pad": ["synth pad"],
    "keys_and_synths.synth_lead_or_arp": ["arp", "arpeggio", "synth lead"],
    "keys_and_synths.pulses_and_ostinati": ["ostinato"],
    "bass.live_bass": ["bass guitar"],
    "bass.synth_bass": ["synth bass", "808"],
    "bass.drone_or_sub": ["sub drone", "sub-drone", "sub-bass", "sub bass", "low drone", "low drones"],
    "winds.orchestral_brass": ["orchestral brass", "french horn", "horn section", "horns"],  # "synth brass" is hybrid_or_synth_brass
    "winds.hybrid_or_synth_brass": ["braam", "braams"],
    "winds.woodwinds": ["flute", "clarinet", "oboe", "woodwind", "woodwinds"],
    "winds.world_wind": ["duduk", "shakuhachi"],
    "voice.solo_voice_lyrics": ["lyrics", "sung"],
    "voice.choir": ["choir", "choral"],
    "voice.vocal_chops_fx": ["vocal chops"],
    "voice.spoken_or_shouted": ["shout", "shouts", "spoken"],
    "sound_design.processed_or_reversed": ["reversed"],
}


def words(text):
    return re.findall(r"[a-z0-9:'’-]+", (text or "").lower())


def edit_distance(a, b):
    """Normalised word-level Levenshtein: edits / max(len)."""
    a, b = words(a), words(b)
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb)))
        prev = cur
    return prev[-1] / max(len(a), len(b), 1)


def body_of(description):
    return gate.split_fits(description)[0]


def mechanical(desc, do_not_claim):
    body, tags = gate.split_fits(desc)
    sents = gate.sentences(body)
    first = sents[0] if sents else ""
    checks = {
        "move1_dash": bool(re.search(r"\s[—–-]\s\S", first)),
        "timestamp": bool(re.search(r"\b\d{1,2}:[0-5]\d\b", body)),
        "move3_opener": bool(sents) and sents[-1].lower().startswith(MOVE3_OPENERS),
        "fits_scene_tags": tags is not None and not gate.fits_reasons(tags, "rC"),
        "no_forbidden": not [w for w in FORBIDDEN + rules.banned_list() if gate._find(w, desc)],
        "no_do_not_claim": not [w for f in do_not_claim for w in CLAIM_WORDS.get(f, []) if gate._find(w, body)],
    }
    detail = {
        "forbidden_hits": sorted({w for w in FORBIDDEN + rules.banned_list() if gate._find(w, desc)}),
        "claim_hits": sorted({f"{f}:{w}" for f in do_not_claim for w in CLAIM_WORDS.get(f, [])
                              if gate._find(w, body)}),
        "fits": tags, "words": len(body.split()), "sentences": len(sents),
    }
    return checks, detail


def load_old_prompts(ref):
    """The 09-16 prompts.py with the 09-16 PFD_RULES.md behind it."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "old_prompts.py").write_text(subprocess.check_output(["git", "show", f"{ref}:prompts.py"], cwd=ROOT).decode())
    (tmp / "PFD_RULES.md").write_text(subprocess.check_output(["git", "show", f"{ref}:PFD_RULES.md"], cwd=ROOT).decode())
    old_rules = rules.load(tmp / "PFD_RULES.md", rules.LANES_PATH)
    spec = importlib.util.spec_from_file_location("old_prompts", tmp / "old_prompts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Shim:
        catalog_code = staticmethod(rules.catalog_code)
        system_instruction = staticmethod(old_rules.system_instruction)
        tunable = staticmethod(old_rules.tunable)
        few_shot = staticmethod(old_rules.few_shot)
    mod.rules = Shim
    return mod.PromptEngine()


def to_mp3(src, dst_dir):
    dst = Path(dst_dir) / (Path(src).stem + ".mp3")
    if not dst.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-codec:a", "libmp3lame",
                        "-b:a", "192k", str(dst)], check=True)
    return dst


def main():
    audio_dir, finals_xlsx, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    ref = sys.argv[sys.argv.index("--baseline-ref") + 1] if "--baseline-ref" in sys.argv else "e9f5ca0"
    key = _secret_value("GEMINI_API_KEY")
    if not key:
        import tomllib
        key = tomllib.load(open(ROOT / ".streamlit/secrets.toml", "rb"))["GEMINI_API_KEY"]

    import openpyxl
    rows = list(openpyxl.load_workbook(finals_xlsx, read_only=True).active.iter_rows(values_only=True))
    hdr = rows[0]
    finals = {}
    for r in rows[1:]:
        d = dict(zip(hdr, r))
        if d.get("TRACK: Title") and d.get("TRACK: Description"):
            finals[d["TRACK: Title"]] = d["TRACK: Description"]

    files = sorted(p for p in audio_dir.iterdir() if re.match(r"rC056 0(0\d|1[0-3]) ", p.name) and "Mix" not in p.name)
    titles = {p: re.sub(r"^rC056 \d{3} ", "", p.stem) for p in files}
    assert len(files) == 13, [p.name for p in files]

    eng = IngestionEngine(str(ROOT))
    cache_path = out.with_suffix(".calla.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    mp3_dir = audio_dir / "mp3"
    mp3_dir.mkdir(exist_ok=True)

    def listen(p):
        title = titles[p]
        if title in cache and cache[title].get("analysis"):
            return title, cache[title]
        mp3 = to_mp3(p, mp3_dir)
        return title, IngestionEngine(str(ROOT)).listen(mp3.read_bytes(), ".mp3", "full", key)

    with cf.ThreadPoolExecutor(4) as ex:
        for title, result in ex.map(listen, files):
            cache[title] = result
            print(f"Call A · {title}: {result['status']} ({result['attempts']} attempt(s))", flush=True)
    cache_path.write_text(json.dumps(cache, indent=1))

    old = load_old_prompts(ref)
    reuse = {}
    if "--reuse-old" in sys.argv:
        prev = json.loads(Path(sys.argv[sys.argv.index("--reuse-old") + 1]).read_text())
        reuse = {t["title"]: t["old"] for t in prev["tracks"] if t.get("old")}
    client = eng._client(key)

    def call_b(title):
        track = eng.track_record(title, "full", cache[title], "rC")
        track["Duration Seconds"] = (cache[title].get("measured") or {}).get("duration")
        if not track.get("analysis"):
            return title, None
        out_ = {"gate": cache[title]["status"], "do_not_claim": []}
        from prompts import call_b_input
        out_["do_not_claim"] = call_b_input(track, "rC")["do_not_claim"]
        if title in reuse:   # the baseline is fixed once written, so reruns compare against the same slop
            out_["old"] = reuse[title]
        for name, prompt, system in (
                ("new", eng.prompts.call_b_prompt(track, "rC", album=ALBUM), eng.prompts.call_b_system("rC")),
                ("old", old.call_b_prompt(track, "rC"), old.call_b_system("rC"))):
            if name in out_:
                continue
            text = eng._generate(client, prompt, CALL_B_CONFIG, system)
            try:
                w = gate.parse_writing(text)
            except gate.SchemaViolation:
                text = eng._generate(client, prompt, CALL_B_CONFIG.model_copy(
                    update={"max_output_tokens": 16384}), system)
                w = gate.parse_writing(text)
            desc = w.description.strip()
            if gate.split_fits(desc)[1] is None:
                desc = gate.join_fits(desc, w.fits)
            out_[name] = {"description": desc, "keywords": w.keywords, "editor_note": w.editor_note}
        return title, out_

    results = {}
    with cf.ThreadPoolExecutor(6) as ex:
        for title, r in ex.map(call_b, [titles[p] for p in files]):
            results[title] = r
            print(f"Call B · {title}: {'ok' if r else 'no analysis'}", flush=True)

    tracks = []
    for title, r in results.items():
        if not r:
            tracks.append({"title": title, "error": "no analysis"})
            continue
        final = finals[title]
        checks, detail = mechanical(r["new"]["description"], r["do_not_claim"])
        tracks.append({
            "title": title, "held_out": title not in EXEMPLAR_TRACKS, "gate": r["gate"],
            "final": final, "new": r["new"], "old": r["old"],
            "d_new": round(edit_distance(body_of(r["new"]["description"]), final), 3),
            "d_old": round(edit_distance(body_of(r["old"]["description"]), final), 3),
            "checks": checks, "check_detail": detail, "mechanical_pass": all(checks.values()),
        })
    scored = [t for t in tracks if "d_new" in t]

    def summary(ts):
        if not ts:
            return {}
        mn, mo = statistics.median(t["d_new"] for t in ts), statistics.median(t["d_old"] for t in ts)
        return {"n": len(ts), "median_new": round(mn, 3), "median_old": round(mo, 3),
                "reduction_pct": round(100 * (mo - mn) / mo, 1) if mo else 0.0}

    s_all, s_held = summary(scored), summary([t for t in scored if t["held_out"]])
    mech_rate = sum(t["mechanical_pass"] for t in scored) / len(scored) if scored else 0
    per_check = {k: sum(t["checks"][k] for t in scored) for k in (scored[0]["checks"] if scored else {})}
    report = {"concept": CONCEPT, "baseline_ref": ref, "all": s_all, "held_out": s_held,
              "mechanical_pass_rate": round(mech_rate, 3), "per_check_pass": per_check,
              "passed": bool(scored) and len(scored) == 13 and s_all["reduction_pct"] >= 30 and mech_rate >= 0.9,
              "furthest": [t["title"] for t in sorted(scored, key=lambda t: -t["d_new"])[:5]],
              "tracks": tracks}
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "tracks"}, indent=1))


if __name__ == "__main__":
    main()
