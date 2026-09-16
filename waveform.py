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
TEMPO_MIN_BPM, TEMPO_MAX_BPM = 50.0, 200.0
TEMPO_SEPARATION_BPM = 4.0
TEMPO_RIVAL_RATIO = 0.75   # a second peak this close in strength means the tempo is ambiguous


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

    tempo_bpm, candidates, confident = measure_tempo(y, sr, hop) if dur >= 4 else (None, [], False)

    return dict(duration=dur, first_sound_t=first_sound, loudest_t=loudest,
                quietest_t=quietest, tail_silence=tail_silence,
                decay_seconds=decay_s, per_sec_db=per_sec,
                peaks_t=top_peaks(per_sec), tempo_bpm=tempo_bpm,
                tempo_candidates=candidates, tempo_confident=confident)


def measure_tempo(y, sr: int, hop: int = HOP):
    """
    (primary bpm, candidates, confident).

    Candidates are the strongest peaks of the onset-strength autocorrelation.
    `confident` means one tempo stands alone: no rival peak within
    TEMPO_RIVAL_RATIO of the top (a half/double pair is a rival, not a
    confirmation), and librosa's own beat tracker agrees with it or with its
    half/double. Ambiguity is not a hallucination — G10 never blocks on it.
    """
    import librosa

    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    if onset.size < 8:
        return None, [], False
    ac = librosa.autocorrelate(onset, max_size=onset.size)
    lags = np.arange(1, len(ac))
    bpms = 60 * sr / hop / lags
    keep = (bpms >= TEMPO_MIN_BPM) & (bpms <= TEMPO_MAX_BPM)
    bpms, strengths = bpms[keep], ac[1:][keep]
    if not len(bpms):
        return None, [], False

    picked = []
    for i in np.argsort(strengths)[::-1]:
        if all(abs(bpms[i] - b) > TEMPO_SEPARATION_BPM for b, _ in picked):
            picked.append((float(bpms[i]), float(strengths[i])))
        if len(picked) == 3:
            break
    top_bpm, top_strength = picked[0]
    rivals = [b for b, s in picked[1:] if top_strength > 0 and s >= TEMPO_RIVAL_RATIO * top_strength]

    beat = np.atleast_1d(librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop)[0])
    beat_bpm = float(beat[0]) if beat.size and beat[0] > 0 else None
    agrees = beat_bpm is not None and any(abs(beat_bpm - c) <= 0.10 * c
                                          for c in (top_bpm, top_bpm * 2, top_bpm / 2))
    return top_bpm, [b for b, _ in picked], bool(not rivals and agrees)


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
