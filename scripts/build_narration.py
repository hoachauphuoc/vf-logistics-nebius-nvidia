"""
Build the narration audio and matching English subtitles for the demo video.

Two outputs, both dropped straight onto a Clipchamp timeline:

  build/narration.wav  one track, each scene starting exactly on its clip boundary
  build/narration.srt   subtitles whose timings come from the audio, not a guess

The audio is cut to the picture, not the other way round. Each scene declares the
length of the clip that was actually recorded for it, and this pads that scene
with silence up to that length. Lay narration.wav at zero and drop the nine clips
in order and every line lands on the shot it describes; no nudging on the
timeline. If a scene's speech will not fit its clip the script says so and by how
much, because the fix for that is shorter writing, not a faster read.

Synthesis is per sentence rather than per scene on purpose. A subtitle needs to
appear when its own sentence is spoken, so the only way to time one honestly is
to measure that sentence's own audio. Scene-level synthesis would force the
timings to be interpolated from word counts, which drifts several seconds over a
three-minute read - long enough for a caption to sit under the wrong shot.

Usage:  python tools_build_narration.py
Requires: texttospeech.googleapis.com enabled, and gcloud application-default or
user credentials with access to the project.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import wave

OUT_DIR = "build"
WAV_PATH = os.path.join(OUT_DIR, "narration.wav")
SRT_PATH = os.path.join(OUT_DIR, "narration.srt")

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

# Studio voices read technical prose with fewer odd stresses than the Neural2
# set, which matters here: the narration is dense with product nouns.
VOICE = {"languageCode": "en-US", "name": "en-US-Studio-O"}
SAMPLE_RATE = 24000
SPEAKING_RATE = 1.0

# Silence held before the first word of a scene, so a line does not start on the
# very frame the shot cuts in.
LEAD_IN_S = 0.6
# Shorter beat between sentences inside a scene.
GAP_AFTER_SENTENCE_S = 0.25

# (scene name, recorded clip length in seconds, narration)
#
# Eight scenes, 165 seconds (2:45), one story: two cases, A and B, with the same booking
# data, which part ways on the purchase invoice. The rules ask for a video "less than three
# (3) minutes", so the cut lands under the limit, not on it.
#
# WORD BUDGET. There is no offline fit check in this script: the real one runs AFTER the
# billable TTS call, only warns, and exits 0. Estimate first with
# scripts/check_narration_budget.py:
#
#     seconds_needed = 0.6 + (sentences - 1) * 0.25 + words / 2.5
#
# An overrun is not local: clip_start advances by max(clip_seconds, spoken), so one long
# scene pushes every later scene off its cut. Splitting a sentence costs 0.25s even if no
# words are added.
#
# Scene 6 names the Tavily search recorded in the filmed case's own trace. If that search
# was served from the one-hour cache, the picture says so and the narration does not call
# it live.
SCENES: list[tuple[str, float, str]] = [
    (
        "1 - Two identical shipments",
        12.0,
        "Two shipments look identical at booking. "
        "Both declare Vietnamese plywood. "
        "Would you release both? "
        "The input origins are still unverified.",
    ),
    (
        "2 - Nemotron screens both",
        26.0,
        "Floorline screens both cases for a freight forwarder, on Nebius Token Factory. "
        "NVIDIA Nemotron 3 Nano scores fraud and compliance with live Tavily searches, "
        "and checks the tariff code against the goods. "
        "The rules set a risk floor the model may raise, never lower, "
        "and on this lane they ask where the plywood inputs came from.",
    ),
    (
        "3 - Evidence requested and received",
        20.0,
        "The reviewer requests a certificate of origin, a producer declaration, "
        "and input purchase invoices. "
        "The shipper uploads each document through its own link, without an account. "
        "Floorline records the documents and extracts their contents with MiniCPM-V.",
    ),
    (
        "4 - The invoice splits the cases",
        28.0,
        "The first two documents match. "
        "The purchase invoices reveal the difference. "
        "Case A identifies Vietnamese inputs. "
        "Case B identifies Chinese veneer, contradicting the declaration. "
        "Floorline marks A as provided and B as contradicted. "
        "Both results stay linked to the submitted evidence.",
    ),
    (
        "5 - A person decides, then it executes",
        24.0,
        "The reviewer reads the evidence and authorizes release for A, "
        "then blocks B with a reason. "
        "Confirmation comes before execution. "
        "The system records the person, evidence version, and the decision sent. "
        "These are human decisions, supported by AI and checks.",
    ),
    (
        "6 - Nemotron in the trace",
        22.0,
        "Every hop in the trace names its model, tokens and cost. "
        "When the floor sits fifteen points above Nano's score, "
        "Nemotron 3 Ultra debates the case and calls Tavily itself. "
        "It can send a case to Nemotron 3 Super for investigation, never clear it.",
    ),
    (
        "7 - The next reviewer can follow",
        18.0,
        "The timeline ties each decision to the reviewer and evidence version, "
        "then records dispatch. "
        "A second reviewer can inspect the same chain, from missing information "
        "to the action taken.",
    ),
    (
        "8 - Close",
        15.0,
        "Floorline helps freight forwarders turn missing information into a "
        "documented decision: move a case forward when evidence supports it, "
        "and stop it when the evidence conflicts.",
    ),
]


def access_token() -> str:
    out = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, shell=True,
    )
    if out.returncode != 0:
        raise SystemExit("could not get an access token:\n" + (out.stderr or ""))
    return out.stdout.strip()


def split_sentences(text: str) -> list[str]:
    """
    Split on sentence enders, keeping the ender.

    Colons are deliberately not split on: the narration uses them mid-sentence
    ("inside it: value under the ceiling"), and breaking there would put half a
    clause on screen on its own.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def synthesise(text: str, token: str) -> bytes:
    body = json.dumps({
        "input": {"text": text},
        "voice": VOICE,
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": SAMPLE_RATE,
            "speakingRate": SPEAKING_RATE,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "x-goog-user-project": project_id(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"synthesis failed ({exc.code}): {exc.read().decode('utf-8', 'replace')}"
        )
    return base64.b64decode(payload["audioContent"])


_PROJECT: str | None = None


def project_id() -> str:
    global _PROJECT
    if _PROJECT is None:
        out = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True, text=True, shell=True,
        )
        _PROJECT = out.stdout.strip()
    return _PROJECT


def pcm_from_wav(data: bytes) -> tuple[bytes, int, int, int]:
    """Strip the WAV header the API returns, keeping the raw frames."""
    import io

    with wave.open(io.BytesIO(data), "rb") as w:
        return (
            w.readframes(w.getnframes()),
            w.getnchannels(),
            w.getsampwidth(),
            w.getframerate(),
        )


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_caption(text: str, width: int = 42) -> str:
    """Lay a caption chunk out as at most two short lines."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines[:2]) if len(lines) <= 2 else "\n".join(
        [lines[0], " ".join(lines[1:])]
    )


MAX_CAPTION_CHARS = 84  # two lines of 42


def caption_chunks(text: str, limit: int = MAX_CAPTION_CHARS) -> list[str]:
    """
    Break one spoken sentence into caption-sized pieces.

    A sentence is the right unit to *time* - it is what gets measured - but not
    always the right unit to *show*. "Each one can hide price manipulation, a
    sanctioned counterparty, or dual-use cargo dressed up as farm equipment"
    runs over six seconds and 130 characters; as a single caption it either
    overflows the frame or shrinks past reading size. Clause boundaries are
    preferred as break points, falling back to word boundaries, so a caption
    never splits mid-phrase.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text]

    # Prefer clause boundaries; keep the comma with the clause it closes.
    pieces = [p.strip() for p in re.split(r"(?<=,)\s+", text) if p.strip()]

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if len(candidate) > limit and current:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)

    # A single clause can still be too long; fall back to words for those.
    out: list[str] = []
    for chunk in chunks:
        if len(chunk) <= limit:
            out.append(chunk)
            continue
        words = chunk.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > limit and current:
                out.append(current)
                current = word
            else:
                current = candidate
        if current:
            out.append(current)

    return out


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    token = access_token()

    channels = sample_width = framerate = None
    audio_chunks: list[bytes] = []
    cues: list[tuple[float, float, str]] = []
    report: list[tuple[str, float, float, float]] = []
    clip_start = 0.0

    def silence(seconds: float) -> bytes:
        return b"\x00" * (int(framerate * seconds) * sample_width * channels)

    for scene_name, clip_seconds, narration in SCENES:
        sentences = split_sentences(narration)
        print(f"[{scene_name}] {len(sentences)} sentence(s)", flush=True)

        scene_frames: list[bytes] = []
        scene_cues: list[tuple[float, float, str]] = []
        offset = LEAD_IN_S  # relative to the scene start

        for sentence_index, sentence in enumerate(sentences):
            wav_bytes = synthesise(sentence, token)
            frames, ch, sw, fr = pcm_from_wav(wav_bytes)

            if channels is None:
                channels, sample_width, framerate = ch, sw, fr
                scene_frames.append(b"\x00" * (int(fr * LEAD_IN_S) * sw * ch))
            elif (ch, sw, fr) != (channels, sample_width, framerate):
                raise SystemExit("the API returned inconsistent audio formats")
            elif not scene_frames:
                scene_frames.append(silence(LEAD_IN_S))

            duration = len(frames) / (fr * sw * ch)

            # Time the sentence, but show it in readable pieces: each chunk gets
            # the share of the sentence's own duration that its length implies.
            chunks = caption_chunks(sentence)
            total_chars = sum(len(c) for c in chunks) or 1
            chunk_at = offset
            for chunk in chunks:
                share = duration * len(chunk) / total_chars
                scene_cues.append((chunk_at, chunk_at + share, chunk))
                chunk_at += share

            scene_frames.append(frames)
            offset += duration

            if sentence_index != len(sentences) - 1:
                scene_frames.append(silence(GAP_AFTER_SENTENCE_S))
                offset += GAP_AFTER_SENTENCE_S

        spoken = offset
        # Hold the scene open for exactly as long as its clip runs, so the next
        # scene's first word lands on the next cut.
        pad = clip_seconds - spoken
        if pad < 0:
            print(
                f"     ! overruns its {clip_seconds:.0f}s clip by {-pad:.1f}s"
                " - shorten the narration for this scene",
                flush=True,
            )
        else:
            scene_frames.append(silence(pad))

        audio_chunks.extend(scene_frames)
        for start, end, text in scene_cues:
            cues.append((clip_start + start, clip_start + end, text))
        report.append((scene_name, clip_start, clip_seconds, spoken))
        clip_start += max(clip_seconds, spoken)

    with wave.open(WAV_PATH, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sample_width)
        out.setframerate(framerate)
        out.writeframes(b"".join(audio_chunks))

    with open(SRT_PATH, "w", encoding="utf-8") as fh:
        for i, (start, end, text) in enumerate(cues, start=1):
            fh.write(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n")
            fh.write(wrap_caption(text) + "\n\n")

    print(f"\nwrote {WAV_PATH}  ({clip_start:.1f}s total)")
    print(f"wrote {SRT_PATH}  ({len(cues)} captions)")
    print("\nScene            clip    spoken   headroom")
    for name, start, clip_seconds, spoken in report:
        mark = "!" if spoken > clip_seconds else " "
        print(
            f"  {int(start) // 60}:{int(start) % 60:02d}  {name:32s}"
            f" {clip_seconds:5.0f}s {spoken:7.1f}s {clip_seconds - spoken:+6.1f}s {mark}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
