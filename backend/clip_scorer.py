"""
Fusion scoring: combines LLM semantic score + audio energy + heuristics.
"""
from config import FUSION_WEIGHTS


# ─────────────────────────────────────────────────────────────
# Heuristic keywords (from viral clip research)
# ─────────────────────────────────────────────────────────────
HOOK_KEYWORDS = {
    "listen", "here's", "the thing", "never", "always", "best", "worst",
    "secret", "truth", "real", "actually", "honestly", "literally",
    "imagine", "what if", "why", "how", "the problem", "the issue",
    "nobody", "everybody", "most people", "you need", "you should",
}

EMOTION_KEYWORDS = {
    "love", "hate", "crazy", "insane", "shocked", "amazing", "terrible",
    "incredible", "unbelievable", "hilarious", "funny", "sad", "angry",
    "scared", "excited", "proud", "disappointed", "frustrated",
}


def _text_heuristic_score(text: str) -> float:
    """
    Score a text segment on heuristic features (0-10).
    Higher = more likely to be a viral hook.
    """
    text_lower = text.lower()
    words = text_lower.split()
    if not words:
        return 0.0

    score = 5.0  # baseline

    # Question marks — engagement driver
    if "?" in text:
        score += 1.5

    # Exclamation marks — emotional intensity
    exclaims = text.count("!")
    score += min(exclaims * 0.5, 1.5)

    # Hook keywords
    hook_hits = sum(1 for kw in HOOK_KEYWORDS if kw in text_lower)
    score += min(hook_hits * 0.8, 2.5)

    # Emotion keywords
    emotion_hits = sum(1 for kw in EMOTION_KEYWORDS if kw in text_lower)
    score += min(emotion_hits * 0.6, 2.0)

    # Short sentences = punchy
    avg_word_len = sum(len(w) for w in words) / len(words)
    if avg_word_len < 5:
        score += 0.5

    # Sentence count — multi-sentence clips tell a story
    sentences = [s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    if 2 <= len(sentences) <= 4:
        score += 0.5

    return max(0.0, min(10.0, score))


def _audio_energy_for_window(energy_windows: list, start: float,
                              end: float) -> float:
    """Get average audio energy score for a time window (0-10)."""
    if not energy_windows:
        return 5.0

    relevant = [
        w["score"] for w in energy_windows
        if w["end"] > start and w["start"] < end
    ]
    if not relevant:
        return 5.0
    return sum(relevant) / len(relevant)


def fuse_scores(clips: list,
                transcript_segments: list,
                energy_windows: list,
                log_fn=None) -> list:
    """
    Merge LLM clips with audio energy and heuristic scores.

    clips: list of clip dicts from LLM (start, end, title, score, hook, reason)
    transcript_segments: list of {start, end, text}
    energy_windows: list of {start, end, score} from audio_highlighter

    Returns clips with updated 'final_score' and 'score_breakdown'.
    """
    w = FUSION_WEIGHTS

    for clip in clips:
        s = clip["start"]
        e = clip["end"]

        # 1. LLM score (normalize to 0-10)
        llm_score = min(10.0, max(0.0, float(clip.get("score", 5))))

        # 2. Audio energy score
        audio_score = _audio_energy_for_window(energy_windows, s, e)

        # 3. Heuristic score — get text for this window
        clip_text = " ".join(
            seg["text"] for seg in transcript_segments
            if seg["end"] > s and seg["start"] < e
        )
        heuristic_score = _text_heuristic_score(clip_text)

        # 4. Fuse
        final = (
            w["llm"] * llm_score +
            w["audio"] * audio_score +
            w["heuristic"] * heuristic_score
        )

        clip["final_score"] = round(final, 2)
        clip["score_breakdown"] = {
            "llm": round(llm_score, 1),
            "audio": round(audio_score, 1),
            "heuristic": round(heuristic_score, 1),
        }

        if log_fn:
            log_fn(f"   📊 {clip['title'][:30]}: "
                   f"LLM={llm_score:.1f} Audio={audio_score:.1f} "
                   f"Heur={heuristic_score:.1f} → Final={final:.1f}")

    # Sort by final score
    clips.sort(key=lambda c: c["final_score"], reverse=True)
    return clips