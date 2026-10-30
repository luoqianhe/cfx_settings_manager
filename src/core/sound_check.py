# src/core/sound_check.py
"""Check the card's WAV files for things that make the board skip a sound, or that may
make it stall reading one (an audio glitch or beep, with the blade animation pausing).

The board plays 16-bit PCM WAV at 22,050 or 44,100 Hz straight from the SD card; any other
format is skipped. Within that, mono files with a plain 44-byte header are the safest:
stereo files, a font that mixes sample rates, editor metadata (bext/LIST/cue/id3/JUNK
chunks) in front of the audio, and the "._name.wav" files macOS writes onto FAT cards are
all flagged. The headers are parsed by hand (not with the wave module) so files wave
can't open - e.g. WAVE_FORMAT_EXTENSIBLE ones - are still described.

Fixes are lossless where possible: metadata is stripped and stereo is mixed down to mono
in pure Python; only a sample-rate/bit-depth change needs core.tracks.convert.
"""
import array
import os
import struct
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from core.tracks import SAMPLE_RATES, convert, converter

PCM, EXTENSIBLE = 0x0001, 0xFFFE
MACOS_JUNK_FOLDERS = ('.Spotlight-V100', '.fseventsd', '.Trashes', '.TemporaryItems')

ERROR, WARNING = 'error', 'warning'


@dataclass
class WavInfo:
    tag: int = 0
    channels: int = 0
    rate: int = 0
    bits: int = 0
    block_align: int = 0
    data_offset: Optional[int] = None
    data_size: int = 0
    file_size: int = 0
    chunks: List[str] = field(default_factory=list)   # every chunk id, in file order

    @property
    def is_pcm16(self) -> bool:
        return self.tag in (PCM, EXTENSIBLE) and self.bits == 16

    @property
    def extra_chunks(self) -> List[str]:
        return [c for c in self.chunks if c not in ('fmt', 'data')]

    @property
    def ms(self) -> int:
        frames = self.data_size // max(1, self.block_align)
        return round(frames * 1000 / max(1, self.rate))


def read_header(path: Path) -> Optional[WavInfo]:
    """Parse a RIFF/WAVE file's chunks. None if it isn't one."""
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b'RIFF' or head[8:12] != b'WAVE':
                return None
            info = WavInfo(file_size=os.fstat(f.fileno()).st_size)
            pos = 12
            while pos + 8 <= info.file_size:
                f.seek(pos)
                cid, size = struct.unpack('<4sI', f.read(8))
                name = cid.decode('latin-1').strip()
                info.chunks.append(name)
                if cid == b'fmt ' and size >= 16:
                    (info.tag, info.channels, info.rate, _rate_bytes, info.block_align,
                     info.bits) = struct.unpack('<HHIIHH', f.read(16))
                elif cid == b'data':
                    info.data_offset, info.data_size = pos + 8, size
                pos += 8 + size + (size & 1)
            return info
    except (OSError, struct.error):
        return None


@dataclass
class Problem:
    severity: str            # ERROR (the board skips the file) or WARNING
    code: str                # not_wav / format / rate / truncated / stereo / mixed_rate / metadata
    message: str


@dataclass
class FileReport:
    path: Path
    info: Optional[WavInfo]
    problems: List[Problem] = field(default_factory=list)

    @property
    def fixable(self) -> bool:
        return any(fix_actions(self))


@dataclass
class FolderReport:
    folder: Path
    files: List[FileReport] = field(default_factory=list)
    main_rate: Optional[int] = None
    wav_count: int = 0

    @property
    def problem_files(self) -> List[FileReport]:
        return [f for f in self.files if f.problems]


def _check_file(path: Path, main_rate: Optional[int]) -> FileReport:
    info = read_header(path)
    report = FileReport(path, info)
    p = report.problems
    if info is None or info.data_offset is None or not info.rate:
        p.append(Problem(ERROR, 'not_wav', "Not a readable WAV file - the board will skip it."))
        return report
    if not info.is_pcm16:
        what = f"{info.bits}-bit" if info.tag in (PCM, EXTENSIBLE) else f"format {info.tag:#06x}"
        p.append(Problem(ERROR, 'format', f"{what} - the board needs 16-bit PCM, so it skips it."))
    if info.rate not in SAMPLE_RATES:
        p.append(Problem(ERROR, 'rate', f"{info.rate} Hz - the board needs 22,050 or 44,100 Hz, "
                                        f"so it skips it."))
    if info.data_offset + info.data_size > info.file_size:
        p.append(Problem(ERROR, 'truncated',
                         "The file is shorter than its header says (truncated copy?)."))
    if info.channels != 1:
        p.append(Problem(WARNING, 'stereo',
                         f"{info.channels} channels - the board's sounds are mono (one speaker)."))
    if main_rate and info.rate in SAMPLE_RATES and info.rate != main_rate:
        p.append(Problem(WARNING, 'mixed_rate',
                         f"{info.rate} Hz while the rest of this folder is {main_rate} Hz."))
    if info.tag == EXTENSIBLE or info.extra_chunks:
        extras = ", ".join(info.extra_chunks) or "extended format header"
        p.append(Problem(WARNING, 'metadata',
                         f"Editor metadata before/after the audio ({extras}); the audio starts at "
                         f"byte {info.data_offset} instead of 44."))
    return report


def check_folder(folder: Path, recursive: bool = False) -> FolderReport:
    """Check every .wav in a folder (font folders are flat; /extra has subfolders). macOS's
    "._" files are left to macos_junk."""
    sounds = sorted(p for p in (folder.rglob('*') if recursive else folder.iterdir())
                    if p.is_file() and p.suffix.lower() == '.wav' and not p.name.startswith('._'))
    rates = Counter()
    for p in sounds:
        info = read_header(p)
        if info and info.rate in SAMPLE_RATES:
            rates[info.rate] += 1
    # In /extra the UI sounds are 22 kHz on purpose, so mixed rates only matter per font.
    main_rate = rates.most_common(1)[0][0] if rates and not recursive else None
    report = FolderReport(folder, main_rate=main_rate, wav_count=len(sounds))
    report.files = [_check_file(p, main_rate) for p in sounds]
    return report


def macos_junk(root: Path) -> List[Path]:
    """Hidden macOS folders at the card root plus every '._*' file on the card."""
    junk = [root / name for name in MACOS_JUNK_FOLDERS if (root / name).exists()]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in MACOS_JUNK_FOLDERS]
        junk += [Path(dirpath) / n for n in filenames if n.startswith('._')]
    return junk


# ---------------------------------------------------------------------- fixes

def fix_actions(report: FileReport) -> List[str]:
    """What fix_file would do: 'convert', 'mono', 'strip'."""
    codes = {p.code for p in report.problems}
    if codes & {'not_wav', 'truncated'}:
        return []
    if codes & {'format', 'rate', 'mixed_rate'}:
        return ['convert'] if converter() else []
    actions = []
    if 'stereo' in codes:
        actions.append('mono')
    if 'metadata' in codes:
        actions.append('strip')
    return actions


def describe_actions(actions: List[str], rate: Optional[int]) -> str:
    text = {'mono': "mix down to mono", 'strip': "strip the metadata",
            'convert': f"convert to 16-bit {rate or 44100} Hz mono"}
    return ", ".join(text[a] for a in actions)


def _write_pcm(path: Path, channels: int, rate: int, data: bytes) -> None:
    """Write a plain 44-byte-header 16-bit PCM WAV atomically (temp file + replace)."""
    block = channels * 2
    header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + len(data), b'WAVE', b'fmt ', 16,
                         PCM, channels, rate, rate * block, block, 16, b'data', len(data))
    fd, temp = tempfile.mkstemp(prefix='.cfxfix_', suffix='.wav', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(header)
            f.write(data)
            if len(data) & 1:
                f.write(b'\0')
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def _mix_to_mono(data: bytes, channels: int) -> bytes:
    samples = array.array('h')
    samples.frombytes(data[:len(data) - len(data) % (2 * channels)])
    if sys.byteorder == 'big':
        samples.byteswap()
    lanes = [samples[c::channels] for c in range(channels)]
    mono = array.array('h', (sum(frame) // channels for frame in zip(*lanes)))
    if sys.byteorder == 'big':
        mono.byteswap()
    return mono.tobytes()


def fix_file(report: FileReport, target_rate: Optional[int] = None) -> List[str]:
    """Apply fix_actions(report) in place. Returns the actions done."""
    actions = fix_actions(report)
    path, info = report.path, report.info
    if not actions:
        return []
    if 'convert' in actions:
        fd, temp = tempfile.mkstemp(prefix='.cfxfix_', suffix='.wav', dir=path.parent)
        os.close(fd)
        try:
            convert(path, Path(temp), target_rate or 44100, mono=True)
            converted = read_header(Path(temp))
            if converted and converted.extra_chunks:     # e.g. afconvert's FLLR padding
                with open(temp, 'rb') as f:
                    f.seek(converted.data_offset)
                    data = f.read(converted.data_size)
                _write_pcm(Path(temp), 1, converted.rate, data)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return actions
    with open(path, 'rb') as f:
        f.seek(info.data_offset)
        data = f.read(info.data_size)
    data = data[:len(data) - len(data) % max(1, info.block_align)]
    channels = info.channels
    if 'mono' in actions:
        data, channels = _mix_to_mono(data, channels), 1
    _write_pcm(path, channels, info.rate, data)
    return actions
