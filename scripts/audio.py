"""Turns the spoken brief into an MP3, using Piper.

Runs as its own workflow step rather than inside morning.py, so that a failure
here can never stop the report being published. Piper is a local neural voice:
no API key, no network at generation time, and nothing sent anywhere.
"""

import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEF = os.path.join(ROOT, "data", "brief.txt")
OUT_DIR = os.path.join(ROOT, "docs", "audio")
CACHE = os.path.join(ROOT, ".voice")

VOICE = os.environ.get("PIPER_VOICE", "en_GB-alan-medium")
KEEP_DAYS = int(os.environ.get("AUDIO_KEEP_DAYS", "30"))

# Delivery, not accent, is what separates "measured" from "rushed". Slowing the
# read slightly and leaving a real gap between sentences buys most of the
# gravitas; it is the same trick a newsreader uses.
LENGTH_SCALE = os.environ.get("PIPER_LENGTH_SCALE", "1.08")   # >1 is slower
SENTENCE_SILENCE = os.environ.get("PIPER_SENTENCE_SILENCE", "0.38")
SPEAKER = os.environ.get("PIPER_SPEAKER", "")   # multi-speaker voices only

# The British male shortlist, with what each one actually is. None of these are
# RP-plummy; alan is the safe default.
SHORTLIST = [
    ("en_GB-alan-medium",
     "Neutral, unfussy British male. Clear, no regional edge, no plum."),
    ("en_GB-alan-low",
     "Same voice, smaller model. Slightly rougher, much faster to render."),
    ("en_GB-northern_english_male-medium",
     "Warmer, northern. Reads as a real person rather than a broadcaster."),
    ("en_GB-semaine-medium",
     "Multi-speaker set; speaker 0 is a measured British male."),
    ("en_GB-vctk-medium",
     "Over a hundred British speakers - set PIPER_SPEAKER to pick one."),
]

HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
CANDIDATES = [
    HF + "/en/en_GB/{name}/{quality}/{voice}{ext}",
    HF + "/en/en_US/{name}/{quality}/{voice}{ext}",
]


def _voice_parts(voice):
    bits = voice.split("-")
    return (bits[1] if len(bits) > 2 else "alan",
            bits[2] if len(bits) > 2 else "medium")


def fetch_voice(voice=VOICE):
    """Download the model once and cache it. Returns the .onnx path."""
    os.makedirs(CACHE, exist_ok=True)
    onnx = os.path.join(CACHE, voice + ".onnx")
    cfg = onnx + ".json"
    if os.path.exists(onnx) and os.path.exists(cfg):
        return onnx
    name, quality = _voice_parts(voice)
    errors = []
    for ext, dest in ((".onnx", onnx), (".onnx.json", cfg)):
        done = False
        for template in CANDIDATES:
            url = template.format(name=name, quality=quality, voice=voice, ext=ext)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "piper"})
                with urllib.request.urlopen(req, timeout=120) as r, \
                        open(dest, "wb") as fh:
                    shutil.copyfileobj(r, fh)
                if os.path.getsize(dest) > 1000:
                    done = True
                    break
            except Exception as exc:        # noqa: BLE001
                errors.append(f"{url}: {exc}")
        if not done:
            raise RuntimeError("could not fetch voice model; tried:\n  "
                               + "\n  ".join(errors[-4:]))
    return onnx


def synthesise(text, wav_path, voice=VOICE, length=None, silence=None,
               speaker=None):
    model = fetch_voice(voice)
    os.makedirs(os.path.dirname(wav_path), exist_ok=True)
    base = [sys.executable, "-m", "piper", "--model", model,
            "--output_file", wav_path]
    tuned = base + ["--length_scale", str(length or LENGTH_SCALE),
                    "--sentence_silence", str(silence or SENTENCE_SILENCE)]
    spk = speaker if speaker is not None else SPEAKER
    if spk not in ("", None):
        tuned += ["--speaker", str(spk)]

    # If this build of piper does not accept the tuning flags, fall back to a
    # plain read rather than losing the audio entirely.
    for cmd, label in ((tuned, "tuned"), (base, "plain")):
        proc = subprocess.run(cmd, input=text.encode("utf-8"),
                              capture_output=True)
        if proc.returncode == 0 and os.path.exists(wav_path):
            if label == "plain":
                print("[audio] tuning flags rejected; used default delivery")
            return wav_path
        err = proc.stderr.decode("utf-8", "replace")[-300:]
    raise RuntimeError("piper failed: " + err)


def audition(text=None, out_dir=None, voices=None):
    """Render the same passage in each shortlisted voice so they can be compared.

    Run once from the Actions tab, listen, then set PIPER_VOICE to the winner.
    """
    text = text or (
        "Good morning. Today is high risk, scoring seventy one out of one "
        "hundred. The story driving things is Iran, and the US and Israel. "
        "It reaches gold through three channels at once: the haven bid, "
        "lower real yields, and the risk to oil coming through the Strait of "
        "Hormuz. On the model that argues for gold up. And gold is doing "
        "exactly that. That is the brief.")
    out_dir = out_dir or os.path.join(OUT_DIR, "auditions")
    os.makedirs(out_dir, exist_ok=True)
    made, failed = [], []
    for voice, _note in (voices or SHORTLIST):
        wav = os.path.join(out_dir, f"{voice}.wav")
        mp3 = os.path.join(out_dir, f"{voice}.mp3")
        try:
            synthesise(text, wav, voice=voice)
            made.append(os.path.basename(to_mp3(wav, mp3) or wav))
        except Exception as exc:            # noqa: BLE001
            failed.append(f"{voice}: {exc}")
    return made, failed


def to_mp3(wav_path, mp3_path):
    """MP3 keeps a daily file at roughly a megabyte instead of eight."""
    if not shutil.which("ffmpeg"):
        return None
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
         "-codec:a", "libmp3lame", "-b:a", "64k", "-ac", "1", mp3_path],
        capture_output=True)
    if proc.returncode != 0 or not os.path.exists(mp3_path):
        return None
    os.remove(wav_path)
    return mp3_path


def prune(keep_days=KEEP_DAYS, today=None):
    """A daily audio file would otherwise grow the repo without limit."""
    if not os.path.isdir(OUT_DIR):
        return 0
    cutoff = (today or date.today()) - timedelta(days=keep_days)
    removed = 0
    for name in os.listdir(OUT_DIR):
        stem, ext = os.path.splitext(name)
        if ext not in (".mp3", ".wav"):
            continue
        try:
            when = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if when < cutoff:
            os.remove(os.path.join(OUT_DIR, name))
            removed += 1
    return removed


def main():
    if "--audition" in sys.argv:
        made, failed = audition()
        for name in made:
            print(f"[audio] audition: {name}")
        for problem in failed:
            print(f"[audio] audition failed: {problem}")
        print("[audio] listen under docs/audio/auditions/, then set "
              "PIPER_VOICE in the workflow to the one you want")
        return 0
    if not os.path.exists(BRIEF):
        print("[audio] no brief to speak")
        return 0
    text = open(BRIEF, encoding="utf-8").read().strip()
    if not text:
        print("[audio] brief is empty")
        return 0
    today = date.today().isoformat()
    wav = os.path.join(OUT_DIR, f"{today}.wav")
    mp3 = os.path.join(OUT_DIR, f"{today}.mp3")
    try:
        synthesise(text, wav)
    except Exception as exc:                # noqa: BLE001
        print(f"[audio] synthesis failed: {exc}")
        return 0                            # never block the report
    out = to_mp3(wav, mp3) or wav
    size = os.path.getsize(out) / 1024
    print(f"[audio] wrote {os.path.basename(out)} ({size:.0f} KB)")
    gone = prune()
    if gone:
        print(f"[audio] pruned {gone} file(s) older than {KEEP_DAYS} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
