"""
Waveform grounding: what the decoded file itself says, measured with librosa.

The gate (gate.py) compares the model's timing, ending and loudness claims
against these numbers. Nothing here calls a model.

measure_waveform follows the v4 build spec, with three corrections, each
covered by test_waveform.py and recorded in DECISIONS.md:
- decay_seconds: the spec version looked for sub-threshold frames *before* the
  last audible frame, which never exist, so it returned 0.0 for every file and
  G8 would have blocked every ring-out and fade-out. It now measures from the
  end of the last loud stretch (within 6 dB of the final 8 s peak) to the end of sound.
- audible threshold: floor + 12 dB alone treats a quiet opening pad as silence
  on a file with no digital silence (the floor is the pad itself). The
  threshold is capped at -50 dBFS.
- quietest_t: the 3 s window search stops at the end of sound, so trailing
  silence is not reported as the quietest stretch.
Added for G6 and G10: peaks_t (three loudest seconds, 5 s apart) and tempo_bpm.
"""
import os
import tempfile
from typing import Dict, List

import numpy as np

SR = 22050
HOP = 512
AUDIBLE_CAP_DB = -50.0
LOUD_WINDOW_DB = 6.0
DECAY_LOOKBACK_S = 8.0


def measure_waveform(path: str) -> dict:
    import librosa

    y, sr = librosa.load(path, sr=SR, mono=True)
    dur = len(y) / sr
    hop = HOP
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    floor = np.percentile(db, 5)
    audible = db > min(floor + 12, AUDIBLE_CAP_DB)
    first_sound = float(t[np.argmax(audible)]) if audible.any() else 0.0
    loudest = float(t[np.argmax(db)])
    tail_idx = len(db) - np.argmax(audible[::-1]) if audible.any() else len(db)
    tail_silence = max(0.0, dur - float(t[min(tail_idx, len(t) - 1)]))

    win = int(3 * sr / hop)
    start = int(np.searchsorted(t, first_sound))
    if tail_idx - start > win:
        conv = np.convolve(db[start:tail_idx], np.ones(win) / win, mode="valid")
        quietest = float(t[start + np.argmin(conv)])
    else:
        quietest = first_sound

    decay_s = 0.0
    last_db = db[max(0, tail_idx - int(DECAY_LOOKBACK_S * sr / hop)):tail_idx]
    if len(last_db) > 0:
        loud = np.where(last_db >= last_db.max() - LOUD_WINDOW_DB)[0]
        decay_s = float(len(last_db) - 1 - loud[-1]) * hop / sr

    per_sec = [float(db[(t >= i) & (t < i + 1)].mean()) if ((t >= i) & (t < i + 1)).any() else float(floor)
               for i in range(int(dur))]

    tempo_bpm = None
    if dur >= 4:
        tempo = np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])
        tempo_bpm = float(tempo[0]) if len(tempo) and tempo[0] > 0 else None

    return dict(duration=dur, first_sound_t=first_sound, loudest_t=loudest,
                quietest_t=quietest, tail_silence=tail_silence,
                decay_seconds=decay_s, per_sec_db=per_sec,
                peaks_t=top_peaks(per_sec), tempo_bpm=tempo_bpm)


def top_peaks(per_sec_db: List[float], count: int = 3, min_gap_s: int = 5) -> List[float]:
    """Start times of the `count` loudest seconds, at least `min_gap_s` apart."""
    order = sorted(range(len(per_sec_db)), key=lambda i: per_sec_db[i], reverse=True)
    picked: List[int] = []
    for i in order:
        if all(abs(i - p) >= min_gap_s for p in picked):
            picked.append(i)
        if len(picked) == count:
            break
    return [float(p) for p in picked]


def measure_bytes(data: bytes, ext: str) -> Dict:
    """measure_waveform on in-memory audio. Raises when the file cannot be decoded."""
    ext = ext if ext.startswith(".") else f".{ext}"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        return measure_waveform(path)
    finally:
        os.remove(path)
