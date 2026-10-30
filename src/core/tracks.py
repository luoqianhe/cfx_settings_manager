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


DECODE_TIMEOUT_MS = 300_000


def _decode(source: Path, rate: int = 0, channels: int = 0, first_buffer_only: bool = False):
    """Decode `source` with Qt's audio decoder (FFmpeg-based, so MP3, M4A/AAC, AIFF, FLAC,
    WAV, ... on every platform) into 16-bit samples. Qt converts to `rate`/`channels`
    itself; with either left 0 it returns the file's own format. Returns
    (bytes, rate, channels) - with first_buffer_only, just (b'', rate, channels) of the
    file's own format. Needs a running Q(Core)Application."""
    from PySide6 import QtCore, QtMultimedia

    if QtCore.QCoreApplication.instance() is None:
        raise RuntimeError("Audio conversion needs the app to be running.")
    if not Path(source).is_file():
        raise RuntimeError(f"{Path(source).name} doesn't exist.")
    decoder = QtMultimedia.QAudioDecoder()
    wanted = QtMultimedia.QAudioFormat()
    wanted.setSampleFormat(QtMultimedia.QAudioFormat.Int16)
    wanted.setSampleRate(rate)
    wanted.setChannelCount(channels)
    decoder.setAudioFormat(wanted)
    decoder.setSource(QtCore.QUrl.fromLocalFile(str(source)))

    chunks, formats, errors = [], set(), []
    loop = QtCore.QEventLoop()

    def on_buffer():
        buffer = decoder.read()
        if not buffer.isValid():
            return
        fmt = buffer.format()
        formats.add((fmt.sampleRate(), fmt.channelCount(), fmt.sampleFormat()))
        chunks.append(bytes(buffer.constData()))
        if first_buffer_only:
            decoder.stop()
            loop.quit()

    decoder.bufferReady.connect(on_buffer)
    decoder.finished.connect(loop.quit)
    decoder.error.connect(lambda _e: (errors.append(decoder.errorString()), loop.quit()))
    timer = QtCore.QTimer.singleShot
    # Start from inside the loop: an unreadable file reports its error straight away, which
    # would otherwise arrive before loop.exec() and leave it waiting forever.
    timer(0, decoder.start)
    timer(DECODE_TIMEOUT_MS, lambda: (errors.append("Decoding took too long."), loop.quit()))
    loop.exec(QtCore.QEventLoop.ExcludeUserInputEvents)
    decoder.stop()

    if errors and not (first_buffer_only and chunks):
        raise RuntimeError(f"Couldn't read {Path(source).name}: {errors[0]}")
    if not chunks:
        raise RuntimeError(f"No audio found in {Path(source).name}.")
    if len(formats) != 1:
        raise RuntimeError(f"Couldn't convert {Path(source).name} (mixed formats).")
    got_rate, got_channels, sample_format = formats.pop()
    if first_buffer_only:           # just probing the file's own format
        return b'', got_rate, got_channels
    if sample_format != QtMultimedia.QAudioFormat.Int16 or (rate and got_rate != rate) \
            or (channels and got_channels != channels):
        raise RuntimeError(f"Couldn't convert {Path(source).name} to {rate} Hz, "
                           f"{channels} channel(s).")
    return b''.join(chunks), got_rate, got_channels


def convert(source: Path, dest: Path, rate: int = 44100, mono: bool = True) -> None:
    """Convert any audio file Qt's decoder reads (MP3, M4A, AIFF, FLAC, WAV, ...) into the
    board's format: 16-bit PCM WAV at `rate`, mono unless told otherwise (then it keeps the
    source's channels). Uses no outside tools, so it works the same on macOS and Windows."""
    channels = 1
    if not mono:
        _data, _rate, channels = _decode(source, first_buffer_only=True)
        channels = min(channels, 2)
    data, rate, channels = _decode(source, rate, channels)
    with wave.open(str(dest), 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)


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
