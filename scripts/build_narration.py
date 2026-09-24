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
# Clip lengths are the ones actually shot on 31/08. The writing is sized to them:
# scene 5 is the review queue and carries the strongest argument in the video, but
# its clip is only 16 seconds, so it keeps one point and drops two rather than
# being read at auctioneer speed.
SCENES: list[tuple[str, float, str]] = [
    (
        "1 - The problem",
        17.0,
        "A freight forwarder clears thousands of shipments a week. "
        "Any one of them can hide price manipulation, a sanctioned buyer, "
        "or dual-use cargo dressed up as farm equipment. "
        "Checking all of them by hand is impossible. "
        "Letting a model release them is reckless.",
    ),
    (
        "2 - A real document",
        15.0,
        "This is a real bill of lading, dropped the way a mailroom would drop it. "
        "Nothing about it is pre-registered. "
        "Model Armor screens the file before any model reads it. "
        "Then an intake agent transcribes it.",
    ),
    (
        "3 - Cost and model tiering",
        17.0,
        "Fraud detection and compliance screening run in parallel on Nemotron Nano. "
        "When either raises something serious, an investigation agent opens a "
        "deeper case on Super. "
        "Every call is metered per agent, in tokens and in dollars. "
        "Screening a shipment costs well under a cent.",
    ),
    (
        "4 - A case that cleared itself",
        22.0,
        "This one cleared on its own. "
        "It arrived as a data event, and it sat inside every limit the business "
        "granted the agent: value under the ceiling, no forbidden destination, "
        "no deterministic finding. "
        "The agent did not decide it was safe. "
        "It proved it was permitted, and recorded which rule allowed it.",
    ),
    (
        "5 - The review queue",
        16.0,
        "Everything the agent was not permitted to close comes here. "
        "Red is escalated, yellow is held; the state is the border colour. "
        "The shipping document sits beside the findings, because approving a hold "
        "you cannot check is a rubber stamp.",
    ),
    (
        "6 - A rendered bill of lading",
        19.0,
        "This shipment arrived as a data event, with no document at all. "
        "So the system rendered one from the record it received, and labelled it "
        "as rendered, on the page and in the provenance. "
        "A reconstruction is never presented as an original. "
        "That would corrupt the audit trail.",
    ),
    (
        "7 - The delegation boundary",
        38.0,
        "The agent has no authority of its own. "
        "A human publishes a machine-readable boundary, and the agent operates "
        "inside it. "
        "It sets the value ceiling, the forbidden destinations, and which actions "
        "the agent may execute without asking. "
        "Every action it takes records the boundary version that allowed it, so a "
        "decision made months ago can be replayed against the policy in force at "
        "the time. "
        "Withdraw the boundary and the system suspends itself. "
        "It keeps analysing and proposing, but the execution gate refuses every "
        "protected action. "
        "Autonomy here is delegated, and delegation can be revoked.",
    ),
    (
        "8 - Prompt injection blocked",
        18.0,
        "This document told the agent to ignore its instructions and release the "
        "container. "
        "Model Armor caught it before any model was invoked, so no tokens were "
        "spent. "
        "The case opened already denied, and the file was kept for a human to see.",
    ),
    (
        "9 - Close",
        18.0,
        "Seven agents on Nebius Token Factory. "
        "Nemotron Nano screens every shipment, Super investigates, and Ultra argues "
        "the cases where the floor and the model disagree. "
        "Agents that act, inside limits a person set, and stop when they should.",
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
