"""
Structure measurement: what the file itself says about SHAPE, measured with
librosa before any model listens (Damir's decision 2026-09-28, "measure first").

Ported from the Mac Studio script tools/pfd_measure.py (2026-09-27), which
passed its acceptance test against Damir's ears on Echoes Of Eternity and Day
Of Reckoning. Images are left out; everything else is the same arithmetic.

measure_structure(path) returns a dict:
  duration_s, sections (list of seconds), stop_downs [{start, len}], hits (seconds),
  ending {type, tail_len_s, last_hit_at, end_drop_db}, trajectory, peak_at_s,
  dialogue_room_share, dialogue_sections [[start, end]], tempo (str), bpm, bpm_conf,
  section_tempi [{start, end, bpm}], harmonic_share, weight_carrier, evolution,
  keywords (ending / dialogue / modular keywords that are true).

brief(structure) renders the facts as short lines for a prompt. Nothing here
calls a model.
"""
import os
import tempfile
import warnings
from typing import Dict, List

import numpy as np

warnings.filterwarnings("ignore")

SR = 22050
HOP = 512


def fmt(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _rms_windows(y, sr, win_s):
    n = int(sr * win_s)
    k = len(y) // n
    if k == 0:
        return np.array([np.sqrt(np.mean(y ** 2))])
    w = y[:k * n].reshape(k, n)
    return np.sqrt(np.mean(w ** 2, axis=1))


def _to_pct(r):
    peak = r.max() if r.max() > 0 else 1.0
    return np.round(100.0 * r / peak).astype(int)


def stop_downs(y, sr, thresh_db=-20, min_len=0.5) -> List[Dict]:
    """Near-silence: >= 0.5 s at least 20 dB under the 95th-percentile level and 12 dB under the preceding 2 s."""
    n = int(sr * 0.05)
    k = len(y) // n
    r = np.sqrt(np.mean(y[:k * n].reshape(k, n) ** 2, axis=1))
    db = 20 * np.log10(r + 1e-12)
    ref = np.percentile(db, 95)
    quiet = db < ref + thresh_db
    out, i = [], 40
    while i < k:
        if quiet[i]:
            j = i
            while j < k and quiet[j]:
                j += 1
            length = (j - i) * 0.05
            if length >= min_len and j * 0.05 < (k * 0.05 - 1.0) and db[i - 40:i].mean() - db[i:j].mean() >= 12:
                out.append({"start": round(i * 0.05, 2), "len": round(length, 2)})
            i = j
        else:
            i += 1
    return out


def hits(y, sr) -> List[float]:
    """A hit = level jump >= 12 dB over a calm previous second (std < 5 dB), near the top, decaying >= 6 dB within 2 s."""
    n = int(sr * 0.05)
    k = len(y) // n
    r = np.sqrt(np.mean(y[:k * n].reshape(k, n) ** 2, axis=1))
    db = 20 * np.log10(r + 1e-12)
    top = np.percentile(db, 85)
    out, i = [], 20
    while i < k - 40:
        prev = db[i - 20:i]
        cur = db[i:i + 2].max()
        if cur - prev.mean() >= 12 and prev.std() < 5 and cur >= top - 6:
            after = db[i + 20:i + 40].mean()
            if cur - after >= 6:
                out.append(round(i * 0.05, 2))
                i += 40
                continue
        i += 1
    return out


def ending(y, sr, dur) -> Dict:
    n = int(sr * 0.25)
    seg = y[-int(sr * min(30, dur)):]
    k = len(seg) // n
    db = 20 * np.log10(np.sqrt(np.mean(seg[:k * n].reshape(k, n) ** 2, axis=1)) + 1e-12)
    ref = db.max()
    loud = db > ref - 6
    last_loud = int(np.where(loud)[0].max())
    tail_len = round((k - 1 - last_loud) * 0.25, 2)
    end_db = db[-2:].mean()
    drop = ref - end_db
    last_hit = None
    start8 = k - int(8 / 0.25)
    for i in range(max(start8, 3), k):
        if db[i] >= ref - 8 and db[i] - db[i - 3:i].min() >= 15:
            last_hit = round(dur - (k - i) * 0.25, 2)
    if last_hit is not None:
        tail_len = round(dur - last_hit, 2)
    if last_hit is not None and dur - last_hit <= 2.5:
        kind = "hard hit"
    elif last_hit is not None:
        kind = "hit with tail"
    elif tail_len >= 3 and drop >= 15:
        kind = "fade"
    elif drop < 8:
        kind = "sustained"
    elif tail_len < 1.5:
        kind = "abrupt"
    else:
        kind = "fade"
    return {"type": kind, "tail_len_s": tail_len, "last_hit_at": last_hit, "end_drop_db": round(float(drop), 1)}


def trajectory(r10, sd, dur):
    n = len(r10)
    if n < 3:
        return "flat", "first"
    start, end = r10[:max(1, n // 5)].mean(), r10[-max(1, n // 5):].mean()
    peak_i = int(np.argmax(r10))
    third = ["first", "middle", "last"][min(2, peak_i * 3 // n)]
    body = r10[:-1] if n > 4 else r10
    diffs = np.diff(body)
    mid = [i for i, d in enumerate(diffs) if 0.2 * n <= i + 1 <= 0.8 * n and d >= 25]
    mid_sd = [s for s in sd if 0.2 * dur <= s["start"] <= 0.8 * dur]
    if r10.max() - r10.min() < 20:
        cls = "flat"
    elif (len(mid_sd) == 1 or len(mid) == 1) and end > start + 15:
        cls = "two-phase"
    elif end < start - 20 and third == "first":
        cls = "decline"
    elif third == "middle" and start < r10.max() - 25 and end < r10.max() - 25:
        cls = "arch"
    elif len(mid) >= 2 and end > start:
        cls = "stepped build"
    elif end > start + 15:
        cls = "steady build"
    else:
        cls = "arch" if r10.max() - end > 25 else "flat"
    return cls, third


def sections(y, sr, dur):
    import librosa
    mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=HOP)
    ch = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    X = np.vstack([librosa.util.normalize(mf, axis=1), librosa.util.normalize(ch, axis=1)])
    Xs = librosa.util.sync(X, librosa.time_to_frames(np.arange(0, dur, 1.0), sr=sr, hop_length=HOP),
                           aggregate=np.mean)
    k = int(np.clip(round(dur / 35), 3, 7))
    try:
        bounds = librosa.segment.agglomerative(Xs, k)
        times = [float(b) for b in bounds]
    except Exception:
        times = [0.0]
    times = sorted(set([0.0] + [t for t in times if 3 < t < dur - 3]))
    return times, Xs


def evolution(Xs):
    if Xs.shape[1] < 20:
        return "unknown"
    w = 5
    V = [Xs[:, i:i + w].mean(axis=1) for i in range(0, Xs.shape[1] - w + 1, w)]

    def cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    adj = [cos(V[i], V[i - 1]) for i in range(1, len(V))]
    lo, hi = int(0.15 * len(adj)), int(0.85 * len(adj))
    back = [cos(V[i], V[i - 6]) for i in range(6, len(V))]
    adj_med = float(np.median(adj))
    back_med = float(np.median(back)) if back else adj_med
    sharp = int(np.sum(np.array(adj[lo:hi]) < 0.75))
    if sharp >= 2:
        return "sectional"
    if adj_med >= 0.97 and back_med >= 0.95:
        return "static loop"
    return "slowly evolving"


def weight_carrier(y):
    import librosa
    H, P = librosa.effects.hpss(y)
    eh, ep = np.sum(H ** 2), np.sum(P ** 2)
    return round(float(eh / (eh + ep + 1e-12)), 2)


def dialogue_room(r1, sec_bounds, dur):
    share = round(float((r1 < 45).mean()), 2)
    ok = []
    for a, b in zip(sec_bounds, sec_bounds[1:] + [dur]):
        seg = r1[int(a):int(b)]
        if len(seg) and seg.mean() < 45:
            ok.append([round(a, 1), round(b, 1)])
    return share, ok


def tempo(y, sr):
    import librosa
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    t = librosa.feature.tempo(onset_envelope=onset, sr=sr, hop_length=HOP, aggregate=None)
    bpm = float(np.median(t))
    conf = float(1.0 - np.std(t) / (bpm + 1e-9))
    ac = librosa.autocorrelate(onset)
    pulse = "no steady pulse" if conf < 0.85 or ac[1:].max() < 0.3 * ac[0] else f"{bpm:.0f} BPM"
    return pulse, round(bpm, 1), round(conf, 2)


def section_tempi(y, sr, bounds, dur) -> List[Dict]:
    """Tempo per measured section (2026-09-27 lesson: one BPM hid What Lies Beyond's tempo changes)."""
    import librosa
    out = []
    for a, b in zip(bounds, bounds[1:] + [dur]):
        if b - a < 6:
            continue
        seg = y[int(a * sr):int(b * sr)]
        onset = librosa.onset.onset_strength(y=seg, sr=sr, hop_length=HOP)
        try:
            t = librosa.feature.tempo(onset_envelope=onset, sr=sr, hop_length=HOP, aggregate=None)
            out.append({"start": round(a, 1), "end": round(b, 1), "bpm": int(round(float(np.median(t))))})
        except Exception:
            continue
    return out


def measure_structure(path: str) -> Dict:
    import librosa
    y_full, sr_full = librosa.load(path, sr=None, mono=True)
    y = librosa.resample(y_full, orig_sr=sr_full, target_sr=SR) if sr_full != SR else y_full
    dur = len(y_full) / sr_full
    r1 = _to_pct(_rms_windows(y_full, sr_full, 1.0))
    r10 = _to_pct(_rms_windows(y_full, sr_full, 10.0))
    sd = stop_downs(y_full, sr_full)
    traj, _ = trajectory(r10, sd, dur)
    hh = hits(y, SR)
    end = ending(y_full, sr_full, dur)
    sec, Xs = sections(y, SR, dur)
    sec = sorted(set(sec) | {round(x["start"] + x["len"], 1) for x in sd if x["len"] >= 1.0 and 5 < x["start"] < dur - 8})
    hshare = weight_carrier(y)
    dshare, dsecs = dialogue_room(r1, sec, dur)
    pulse, bpm, bconf = tempo(y, SR)
    peak10 = int(np.argmax(r10)) * 10
    keywords = [k for k, c in [
        ("Hard Cut Ending", end["type"] == "hard hit"),
        ("Button Ending", end["type"] in ("hard hit", "hit with tail")),
        ("Ring-Out Tail", end["tail_len_s"] >= 3),
        ("Dialogue Friendly", dshare >= 0.4),
        ("Modular", len(sd) >= 1)] if c]
    return {
        "duration_s": round(dur, 2),
        "sections": [round(s, 1) for s in sec],
        "stop_downs": sd,
        "hits": hh,
        "ending": end,
        "trajectory": traj,
        "peak_at_s": peak10,
        "dialogue_room_share": dshare,
        "dialogue_sections": dsecs,
        "tempo": pulse, "bpm": bpm, "bpm_conf": bconf,
        "section_tempi": section_tempi(y, SR, sec, dur),
        "harmonic_share": hshare,
        "weight_carrier": "harmonic" if hshare >= 0.6 else ("percussive" if hshare <= 0.4 else "mixed"),
        "evolution": evolution(Xs),
        "keywords": keywords,
    }


def measure_bytes(file_bytes: bytes, ext: str) -> Dict:
    suffix = "." + ext.lower().lstrip(".")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        return measure_structure(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def event_times(s: Dict) -> List[float]:
    """Every measured moment a description may quote: section starts, stop-downs, hits, the last hit."""
    out = set(float(t) for t in s.get("sections") or [])
    out |= {float(x["start"]) for x in s.get("stop_downs") or []}
    out |= {float(t) for t in s.get("hits") or []}
    last = (s.get("ending") or {}).get("last_hit_at")
    if last:
        out.add(float(last))
    out.add(float(s.get("duration_s") or 0))
    return sorted(out)


def brief(s: Dict) -> str:
    """The facts as prompt lines. Timestamps here are the only ones a writer may use."""
    if not s:
        return ""
    end = s.get("ending") or {}
    lines = [
        f"duration {fmt(s['duration_s'])}",
        "sections start at " + ", ".join(fmt(t) for t in s.get("sections") or []),
        "stop-downs (near silence): " + (", ".join(f"{fmt(x['start'])} ({x['len']} s)" for x in s.get("stop_downs") or []) or "none"),
        f"hits (sudden level jumps): " + (", ".join(fmt(t) for t in (s.get("hits") or [])[:12]) or "none"),
        f"ending: {end.get('type')}, tail {end.get('tail_len_s')} s" + (f", last hit at {fmt(end['last_hit_at'])}" if end.get("last_hit_at") else ""),
        f"loudness shape: {s.get('trajectory')}, loudest around {fmt(s.get('peak_at_s') or 0)}",
        f"dialogue room: {int((s.get('dialogue_room_share') or 0) * 100)}% of the track; quiet sections "
        + (", ".join(f"{fmt(a)}-{fmt(b)}" for a, b in s.get("dialogue_sections") or []) or "none"),
        f"tempo: {s.get('tempo')}"
        + ("; per section " + ", ".join(f"{fmt(x['start'])} {x['bpm']}" for x in s.get("section_tempi") or []) if s.get("section_tempi") else ""),
        f"weight carrier: {s.get('weight_carrier')} (harmonic share {s.get('harmonic_share')}); "
        + ("drums are unlikely to carry this track" if (s.get("harmonic_share") or 0) >= 0.85 else "percussive weight is real"),
        f"evolution: {s.get('evolution')}",
    ]
    return "\n".join(lines)
