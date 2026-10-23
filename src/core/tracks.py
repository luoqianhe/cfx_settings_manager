# src/core/tracks.py
"""The iSaber music tracks in the card's root /tracks folder (manual: "Audio Player -
iSaber & Local Tracks"): track1.wav, track2.wav, ... numbered from 1. In ledstrip mode the
blade "plays along" with these per special.txt's blademusicstyle. (A font's own tracks
folder plays music too, but the blade doesn't react to it.)

The board plays 16-bit WAV at 22,050 or 44,100 Hz; the manual says files in any other
format "will be skipped during the boot". It suggests normalizing tracks to around 50-60%
of full scale so they sit at a similar level to the saber's own sounds.
"""
import array
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import List, Optional

TRACK_RE = re.compile(r'^track(\d+)\.wav$', re.IGNORECASE)
SAMPLE_RATES = (44100, 22050)
NORMALIZE_PEAK = 0.56     # ~ -5 dBFS: within the manual's suggested 50-60%


def read_format(path: Path) -> Optional[dict]:
    """{'channels', 'bits', 'rate', 'ms'} of a PCM WAV, or None if it isn't one."""
    try:
        with wave.open(str(path), 'rb') as w:
            return {'channels': w.getnchannels(), 'bits': w.getsampwidth() * 8,
                    'rate': w.getframerate(),
                    'ms': round(w.getnframes() * 1000 / max(1, w.getframerate()))}
    except (wave.Error, EOFError, OSError):
        return None


def format_problems(info: Optional[dict]) -> List[str]:
    """Why the board would skip (or might mishandle) a file with this format."""
    if info is None:
        return ["Not a plain (PCM) WAV file - the board will skip it."]
    problems = []
    if info['bits'] != 16:
        problems.append(f"{info['bits']}-bit - the board needs 16-bit, so it will skip it.")
    if info['rate'] not in SAMPLE_RATES:
        problems.append(f"{info['rate']} Hz - the board needs 22,050 or 44,100 Hz, so it "
                        f"will skip it.")
    if info['channels'] != 1:
        problems.append(f"{info['channels']} channels - the board's own sounds are mono "
                        f"(it has one speaker); convert to mono to be safe.")
    return problems


def list_tracks(folder: Path) -> List[dict]:
    """[{'number', 'path', 'info', 'problems'}] for every track<N>.wav, by number."""
    tracks = []
    if folder.is_dir():
        for path in folder.iterdir():
            m = TRACK_RE.match(path.name)
            if m and path.is_file():
                info = read_format(path)
                tracks.append({'number': int(m.group(1)), 'path': path, 'info': info,
                               'problems': format_problems(info)})
    tracks.sort(key=lambda t: t['number'])
    return tracks


def numbering_problem(tracks: List[dict]) -> Optional[str]:
    numbers = [t['number'] for t in tracks]
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        return (f"Tracks are numbered {', '.join(map(str, numbers))} - the board expects "
                f"track1, track2, … with no gaps. Use Renumber to fix it.")
    return None


def converter() -> Optional[str]:
    """'afconvert' (built into macOS) or 'ffmpeg', whichever is available."""
    if sys.platform == 'darwin' and shutil.which('afconvert'):
        return 'afconvert'
    if shutil.which('ffmpeg'):
        return 'ffmpeg'
    return None


def convert(source: Path, dest: Path, rate: int = 44100, mono: bool = True) -> None:
    """Convert any audio file the converter understands (MP3, M4A, AIFF, WAV, ...) into the
    board's format: 16-bit PCM WAV at `rate`, mono unless told otherwise."""
    tool = converter()
    if tool == 'afconvert':
        command = ['afconvert', '-f', 'WAVE', '-d', f'LEI16@{rate}']
        if mono:
            command += ['-c', '1']
        command += [str(source), str(dest)]
    elif tool == 'ffmpeg':
        command = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(source), '-vn',
                   '-acodec', 'pcm_s16le', '-ar', str(rate)]
        if mono:
            command += ['-ac', '1']
        command += [str(dest)]
    else:
        raise RuntimeError("No audio converter found - this needs macOS (afconvert) or ffmpeg.")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not dest.is_file():
        raise RuntimeError((result.stderr or result.stdout or "conversion failed").strip())


def normalize(path: Path, peak: float = NORMALIZE_PEAK) -> float:
    """Scale a 16-bit WAV in place so its loudest sample reaches `peak` of full scale.
    Returns the gain applied (1.0 = unchanged, e.g. a silent file)."""
    with wave.open(str(path), 'rb') as w:
        params = w.getparams()
        samples = array.array('h', w.readframes(w.getnframes()))
    if sys.byteorder == 'big':
        samples.byteswap()
    loudest = max((max(samples), -min(samples)), default=0) if samples else 0
    if loudest == 0:
        return 1.0
    gain = peak * 32767 / loudest
    samples = array.array('h', (max(-32768, min(32767, int(s * gain))) for s in samples))
    if sys.byteorder == 'big':
        samples.byteswap()
    with wave.open(str(path), 'wb') as w:
        w.setparams(params)
        w.writeframes(samples.tobytes())
    return gain


def prepare_track(source: Path, rate: int = 44100, mono: bool = True,
                  normalize_peak: Optional[float] = NORMALIZE_PEAK) -> Path:
    """Convert (and optionally normalize) `source` into a temporary WAV ready to place."""
    temp_dir = Path(tempfile.mkdtemp(prefix="cfx_track_"))
    dest = temp_dir / "track.wav"
    convert(source, dest, rate, mono)
    if normalize_peak:
        normalize(dest, normalize_peak)
    return dest


def apply_order(folder: Path, ordered: List[Path]) -> None:
    """Rename the given track files to track1.wav, track2.wav, ... in that order. Done in
    two steps (via temporary names) so swapping two tracks never overwrites one."""
    temporary = []
    for i, path in enumerate(ordered):
        temp = folder / f".renumber_{i}_{path.name}"
        path.rename(temp)
        temporary.append(temp)
    for i, temp in enumerate(temporary, start=1):
        temp.rename(folder / f"track{i}.wav")
