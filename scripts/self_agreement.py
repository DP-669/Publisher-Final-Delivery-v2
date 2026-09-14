"""
Call A self-agreement check.

Runs Call A five times on the same track under two configs:
  (a) temperature 0.0, top_p 1.0, top_k 1   (the production CALL_A_CONFIG)
  (b) temperature 1.0                        (Google's recommended default)
and prints, per config, the fraction of instrument-family presence fields that
came back identical in every successful run. The result is appended to
DECISIONS.md under "Self-agreement runs".

It calls the Gemini API ten times with real audio, so it is not part of the
test suite. Run it by hand:

    python scripts/self_agreement.py path/to/track.mp3 [--mix full|sparse|sound_design] [--runs 5] [--model ID]

GEMINI_API_KEY comes from .streamlit/secrets.toml or the environment.
"""
import argparse
import datetime
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gate  # noqa: E402
import waveform  # noqa: E402
from analysis_schema import walk_families  # noqa: E402
from engine import CALL_A_CONFIG, GEMINI_AUDIO_MODEL, IngestionEngine, _secret_value  # noqa: E402

CONFIGS = {
    "a_temp0_topk1": CALL_A_CONFIG,
    "b_temp1": CALL_A_CONFIG.model_copy(update={"temperature": 1.0, "top_p": None, "top_k": None}),
}


def presence_map(analysis) -> dict:
    return {path: fam.presence.value for path, fam in walk_families(analysis.instrumentation)}


def agreement(runs: list) -> tuple:
    """(fraction identical, disagreeing family paths) across successful runs."""
    ok = [r for r in runs if r is not None]
    if len(ok) < 2:
        return None, []
    values = defaultdict(set)
    for r in ok:
        for path, presence in r.items():
            values[path].add(presence)
    disagree = sorted(p for p, v in values.items() if len(v) > 1)
    return 1 - len(disagree) / len(values), disagree


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio")
    parser.add_argument("--mix", default="full")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--model", default=GEMINI_AUDIO_MODEL)
    args = parser.parse_args()

    key = _secret_value("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set.")
    path = Path(args.audio)
    data = path.read_bytes()
    measured = waveform.measure_waveform(str(path))
    duration = measured["duration"]

    eng = IngestionEngine(root_path=str(ROOT))
    eng.gemini_model = args.model
    client = eng._client(key)
    audio = eng._audio_part(client, data, path.suffix)
    system = eng.prompts.call_a_system(duration)
    user = eng.prompts.call_a_user(args.mix, duration)

    results = {}
    for name, config in CONFIGS.items():
        runs = []
        for i in range(args.runs):
            try:
                analysis = gate.parse_analysis(eng._generate(client, [audio, user], config, system))
                runs.append(presence_map(analysis))
                print(f"{name} run {i + 1}: ok")
            except gate.SchemaViolation as exc:
                runs.append(None)
                print(f"{name} run {i + 1}: schema violation — {str(exc)[:120]}")
        frac, disagree = agreement(runs)
        results[name] = (frac, sum(r is not None for r in runs), disagree)
        shown = "n/a (fewer than two valid runs)" if frac is None else f"{frac:.1%}"
        print(f"\n{name}: presence fields identical across runs = {shown}")
        if disagree:
            print("  disagreeing families: " + ", ".join(disagree))

    day = datetime.date.today().isoformat()
    parts = [f"{n}: {'n/a' if f is None else f'{f:.1%}'} ({ok}/{args.runs} valid)" for n, (f, ok, _) in results.items()]
    line = f"- {day} · {os.path.basename(args.audio)} · {args.model} · " + " · ".join(parts)
    decisions = ROOT / "DECISIONS.md"
    text = decisions.read_text(encoding="utf-8")
    if "## Self-agreement runs" not in text:
        text = text.rstrip() + "\n\n## Self-agreement runs\nWritten by scripts/self_agreement.py.\n"
    decisions.write_text(text.rstrip() + "\n" + line + "\n", encoding="utf-8")
    print(f"\nAppended to DECISIONS.md:\n{line}")


if __name__ == "__main__":
    main()
