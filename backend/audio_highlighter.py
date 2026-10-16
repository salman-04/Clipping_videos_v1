"""
Audio-based viral clip detection — NO LLM, NO API KEYS.
Finds exciting moments by analyzing audio energy, pitch, and chaos.
"""
import os
import subprocess
import numpy as np
from pathlib import Path


def analyze_audio(audio_path: Path, window_seconds: float = 3.0):
    """
    Analyze audio in windows. Returns list of (start, end, score).
    Score is based on RMS energy + spectral centroid + zero-crossing rate.
    """
    import librosa

    print(f"🎵 Analyzing audio: {audio_path.name}")
    y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    duration = len(y) / sr

    # Hop length = window_seconds
    hop = int(sr * window_seconds)
    frame_length = hop * 2

    # Compute features per frame
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop)[0]
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=frame_length, hop_length=hop)[0]
    cent = librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=frame_length, hop_length=hop)[0]

    # Normalize each feature to 0-1
    def norm(arr):
        arr = np.array(arr, dtype=float)
        if arr.max() > arr.min():
            return (arr - arr.min()) / (arr.max() - arr.min())
        return arr

    rms_n = norm(rms)
    zcr_n = norm(zcr)
    cent_n = norm(cent)

    # Combine: energy is most important, then brightness, then chaos
    # Weighted: 50% energy, 30% spectral (excitement), 20% chaos
    scores = 0.5 * rms_n + 0.3 * cent_n + 0.2 * zcr_n

    # Build windows
    windows = []
    for i in range(len(scores)):
        start = i * window_seconds
        end = min(start + window_seconds, duration)
        if end - start < 1.0:
            continue
        windows.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "score": round(float(scores[i]) * 10, 2),  # 0-10 scale
        })

    print(f"   ✅ Analyzed {len(windows)} windows")
    return windows


def find_peaks(windows, min_dur: float, max_dur: float, num_clips: int):
    """Find peak moments expanded into clips of correct duration."""
    if not windows:
        return []

    sorted_w = sorted(windows, key=lambda w: w["score"], reverse=True)
    clips, used = [], []

    for w in sorted_w:
        if len(clips) >= num_clips:
            break
        center = (w["start"] + w["end"]) / 2
        if any(s <= center <= e for s, e in used):
            continue

        target = (min_dur + max_dur) / 2
        start = max(0, center - target / 2)
        end = start + target

        actual = end - start
        if actual < min_dur:
            end = start + min_dur
        elif actual > max_dur:
            end = start + max_dur

        clips.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "score": int(min(10, round(w["score"]))),
            "title": f"Highlight at {int(start//60)}:{int(start%60):02d}",
            "hook": "",
            "reason": f"Audio energy spike ({w['score']:.1f}/10)",
        })
        used.append((start, end))

    clips.sort(key=lambda c: c["start"])
    return clips


def detect_highlights(audio_path: Path, min_dur: int, max_dur: int, num_clips: int):
    """
    Main entry: analyze audio, find peaks, return clip candidates.
    """
    windows = analyze_audio(audio_path)
    clips = find_peaks(windows, min_dur, max_dur, num_clips)
    print(f"🎯 Found {len(clips)} candidate clips from audio analysis")
    return clips