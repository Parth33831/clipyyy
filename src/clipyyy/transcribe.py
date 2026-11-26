"""Local transcription with word timestamps (faster-whisper)."""

from __future__ import annotations

import logging
from pathlib import Path

from clipyyy.config import home
from clipyyy.media import run_ffmpeg

logger = logging.getLogger(__name__)

SENTENCE_ENDINGS = (".", "!", "?", "…", "。", "？", "！", "؟", "।")


def transcribe(video_path: Path, work_dir: Path, model_size: str, language: str = "auto") -> dict:
    audio_path = work_dir / "audio.wav"
    run_ffmpeg(
        ["-i", str(video_path), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio_path)]
    )
    audio = load_wav(audio_path)
    lang = None if language in ("", "auto") else language
    try:
        words, detected = _run_whisper(audio, model_size, lang, "auto", "default")
    except RuntimeError as exc:
        # A GPU without the CUDA libraries faster-whisper expects: fall back to the CPU.
        if not any(k in str(exc).lower() for k in ("cuda", "cublas", "cudnn")):
            raise
        logger.warning("GPU transcription unavailable (%s); using the CPU", exc)
        words, detected = _run_whisper(audio, model_size, lang, "cpu", "int8")
    audio_path.unlink(missing_ok=True)
    return {"language": detected, "model": model_size, "words": words, "sentences": group_sentences(words)}


def transcribe_music(audio_path: Path, work_dir: Path, model_size: str, language: str = "auto") -> dict:
    """Transcribe a music track without speech VAD and retain Whisper word timings.

    VAD is useful for dialogue but can discard quiet or sustained singing. A wider
    beam also gives the small local model a better chance on sung vocals.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    wav_path = work_dir / "music-audio.wav"
    run_ffmpeg(["-i", str(audio_path), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)])
    audio = load_wav(wav_path)
    lang = None if language in ("", "auto") else language
    try:
        words, detected = _run_whisper(audio, model_size, lang, "auto", "default", music=True)
    except RuntimeError as exc:
        if not any(k in str(exc).lower() for k in ("cuda", "cublas", "cudnn")):
            raise
        logger.warning("GPU music transcription unavailable (%s); using the CPU", exc)
        words, detected = _run_whisper(audio, model_size, lang, "cpu", "int8", music=True)
    wav_path.unlink(missing_ok=True)
    return {"language": detected, "model": model_size, "words": words, "sentences": group_sentences(words)}


def _run_whisper(
    audio, model_size: str, language: str | None, device: str, compute_type: str, music: bool = False
):
    import warnings

    from faster_whisper import WhisperModel

    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*unauthenticated requests to the HF Hub.*")

    model = WhisperModel(
        model_size, device=device, compute_type=compute_type, download_root=str(home() / "models" / "whisper")
    )
    segments, info = model.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        vad_filter=not music,
        beam_size=5 if music else 1,
        condition_on_previous_text=music,
        temperature=0.0,
        no_speech_threshold=0.6,
    )
    words = [
        {"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
        for segment in segments
        for w in segment.words or []
        if w.word.strip()
    ]
    return words, info.language


def load_wav(path: Path):
    """16 kHz mono PCM as float32. Decoding ourselves avoids PyAV version drift."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def group_sentences(words: list[dict], max_words: int = 40, pause_seconds: float = 0.8) -> list[dict]:
    """Group words at punctuation or natural pauses, with a cap for unpunctuated speech."""
    sentences: list[dict] = []
    current: list[dict] = []
    for word in words:
        pause = current and float(word["start"]) - float(current[-1]["end"]) >= pause_seconds
        if pause:
            sentences.append(_sentence(current))
            current = []
        current.append(word)
        if word["word"].endswith(SENTENCE_ENDINGS) or len(current) >= max_words:
            sentences.append(_sentence(current))
            current = []
    if current:
        sentences.append(_sentence(current))
    return sentences


def _sentence(words: list[dict]) -> dict:
    return {
        "text": " ".join(w["word"] for w in words),
        "start": words[0]["start"],
        "end": words[-1]["end"],
    }

def align_lyric_text_to_words(
    lyrics: str, transcript_words: list[dict], max_lyrics_words: int = 500
) -> dict:
    """Align creator-supplied lyric words to Whisper timestamps without replacing their text."""
    import re
    from difflib import SequenceMatcher

    lyric_tokens = re.findall(r"\w+(?:['’]\w+)*", lyrics, flags=re.UNICODE)
    if not lyric_tokens:
        raise ValueError("Enter lyrics before asking CLIPYYY to align them.")
    if len(lyric_tokens) > max_lyrics_words:
        raise ValueError(f"Align up to {max_lyrics_words} lyric words at a time.")

    recognized = []
    for item in transcript_words[:2000]:
        try:
            word = str(item["word"]).strip()
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if word and start >= 0 and end > start:
            recognized.append({"word": word, "start": start, "end": end})
    if not recognized:
        raise ValueError("No usable word timestamps were detected in the soundtrack.")

    def normalize(value: str) -> str:
        return re.sub(r"[^\w]", "", value.casefold(), flags=re.UNICODE)

    wanted = [normalize(token) for token in lyric_tokens]
    heard = [normalize(item["word"]) for item in recognized]
    rows, cols = len(wanted), len(heard)
    trace = [bytearray(cols + 1) for _ in range(rows + 1)]
    previous = [0.0] * (cols + 1)
    skip_transcript, skip_lyric = -0.22, -1.65

    for i in range(1, rows + 1):
        current = [previous[0] + skip_lyric] + [0.0] * cols
        trace[i][0] = 3
        for j in range(1, cols + 1):
            left, right = wanted[i - 1], heard[j - 1]
            similarity = 0.0
            if left and right:
                if left == right:
                    similarity = 1.0
                elif left[0] == right[0] and abs(len(left) - len(right)) <= 2:
                    similarity = SequenceMatcher(None, left, right).ratio()
            match_score = 3.0 if similarity >= 0.92 else 1.25 if similarity >= 0.76 else -2.4
            choices = (
                previous[j - 1] + match_score,
                current[j - 1] + skip_transcript,
                previous[j] + skip_lyric,
            )
            best = max(range(3), key=choices.__getitem__)
            current[j] = choices[best]
            trace[i][j] = best + 1
        previous = current

    j = max(range(cols + 1), key=previous.__getitem__)
    i = rows
    matched = {}
    while i > 0 and j >= 0:
        direction = trace[i][j]
        if direction == 1:
            left, right = wanted[i - 1], heard[j - 1]
            similarity = 1.0 if left == right else SequenceMatcher(None, left, right).ratio()
            if similarity >= 0.76:
                matched[i - 1] = recognized[j - 1]
            i -= 1
            j -= 1
        elif direction == 2:
            j -= 1
        elif direction == 3:
            i -= 1
        else:
            break

    aligned = [
        {
            "word": lyric_tokens[index],
            "start": round(float(item["start"]), 3),
            "end": round(float(item["end"]), 3),
        }
        for index, item in sorted(matched.items())
    ]
    unmatched = [token for index, token in enumerate(lyric_tokens) if index not in matched]
    return {
        "words": aligned,
        "unmatched_words": unmatched,
        "word_count": len(lyric_tokens),
        "matched_count": len(aligned),
        "match_percent": round(100 * len(aligned) / len(lyric_tokens)),
    }

