# src/core/flat_config.py
"""Read and edit "flat" key=value files with no [sections] - special.txt in particular,
which the manual describes as "totally manually edited": every setting comes with its own
explanatory ## comment, and disabled settings are kept as ##key=value lines. So, as with
grafx1.txt (core/grafx_writer.update_config_section), changes are made line by line:
comments, disabled settings, ordering and line endings all stay as they were.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

_KEY_RE = re.compile(r'^(?P<hashes>#*)\s*(?P<key>[A-Za-z][\w-]*)\s*=(?P<value>.*)$')


def parse_flat(path: Path) -> List[dict]:
    """Every setting line, active or ##-disabled, in file order:
    [{'key', 'value', 'enabled', 'comment'}] - 'comment' is the block of ## prose lines
    right above it (the file's own explanation of the setting), joined into one string.
    A key that appears more than once is listed once: the active line wins."""
    try:
        lines = path.read_text(errors='replace').splitlines()
    except OSError:
        return []
    entries: Dict[str, dict] = {}
    order: List[str] = []
    comment: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            comment = []
            continue
        m = _KEY_RE.match(line)
        if m and len(m.group('hashes')) <= 2:
            key, value = m.group('key').lower(), m.group('value').strip()
            enabled = m.group('hashes') == ''
            entry = {'key': key, 'value': value, 'enabled': enabled,
                     'comment': " ".join(comment)}
            if key not in entries:
                order.append(key)
                entries[key] = entry
            elif enabled and not entries[key]['enabled']:
                entry['comment'] = entry['comment'] or entries[key]['comment']
                entries[key] = entry
            comment = []
        elif line.startswith('#'):
            comment.append(line.lstrip('#').strip())
        elif line.startswith('//'):
            comment = []
    return [entries[key] for key in order]


def update_flat(path: Path, updates: Dict[str, Optional[str]]) -> None:
    """Apply {key: value or None} line by line. A value replaces the active line, or
    re-enables a ##key= line, or is added before a closing "## End..." line (else at the
    end). None disables the key by commenting its active line out with ##."""
    raw = path.read_bytes().decode('utf-8', errors='replace') if path.exists() else ''
    newline = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.splitlines()

    def find(key, active):
        for i, line in enumerate(lines):
            m = _KEY_RE.match(line.strip())
            if m and m.group('key').lower() == key and (m.group('hashes') == '') == active \
                    and len(m.group('hashes')) <= 2:
                return i
        return None

    for key, value in updates.items():
        key = key.lower()
        active = find(key, True)
        if value is None:
            if active is not None:
                lines[active] = '##' + lines[active].strip()
            continue
        if active is not None:
            lines[active] = f"{key}={value}"
            continue
        disabled = find(key, False)
        if disabled is not None:
            lines[disabled] = f"{key}={value}"
            continue
        end = next((i for i, line in enumerate(lines)
                    if line.strip().lower().startswith('## end')), len(lines))
        lines.insert(end, f"{key}={value}")

    path.write_bytes((newline.join(lines) + newline).encode('utf-8'))
