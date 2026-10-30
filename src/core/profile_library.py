# src/core/profile_library.py
"""The card's shared profile libraries - blade profiles in config.txt ([profile=N]) and
color profiles in colors.txt ([color=N]) - and the operations that move fonts and profiles
around between them:

  * finding exact duplicate profiles and merging them (every font that used a removed
    profile is pointed at the one that's kept, and later profiles are renumbered),
  * keeping the "//3-LIGHT, 7-ROGUE" comment above each profile - the fonts that use it -
    up to date,
  * importing a soundfont from another CFX card, bringing its profiles along (reusing
    identical ones already here) and any GraFx / Accents / Pixies resources they link to.

A font "uses" a profile the way the board picks one at boot: start_blade / start_color
from its font_config.txt, or - when that's -1 - the last-used one saved for it in
prefs.txt ([font=N] is 0-based: folder 1-XXX is [font=0]). The used_profiles_* masks in
font_config.txt only filter what Spectrum can browse to; character 0 is profile 0.

Every file is edited line by line, so comments, ordering and line endings stay as they were.
"""
import filecmp
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

MAX_PROFILES = 32           # per the manual: up to 32 color and 32 blade profiles
NAME_KEYS = {'pname', 'cname'}

# Blade-profile keys that link to an indexed '<n>-name' folder under /extra.
RESOURCE_KEYS = {
    'style_grafx1': 'GRAFX', 'style_grafx2': 'GRAFX', 'style_grafx3': 'GRAFX',
    'style_accents': 'ACCENTS',
    'style_pixies': 'PIXIES', 'style_auxpixies': 'PIXIES',
}

_KEY_LINE_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*=(.*)$')
_FONT_LIST_ITEM_RE = re.compile(r'^\d+-\S.*$')


@dataclass(frozen=True)
class LibraryKind:
    filename: str          # config.txt / colors.txt
    section: str           # profile / color
    font_key: str          # start_blade / start_color
    mask_key: str          # used_profiles_blade / used_profiles_color
    prefs_key: str         # profile / color  (in prefs.txt)
    label: str

    @property
    def header_re(self):
        return re.compile(r'^\s*\[' + self.section + r'\s*=\s*(\d+)\s*\]\s*$', re.IGNORECASE)


BLADE = LibraryKind('config.txt', 'profile', 'start_blade', 'used_profiles_blade', 'profile',
                    'blade profile')
COLOR = LibraryKind('colors.txt', 'color', 'start_color', 'used_profiles_color', 'color',
                    'color profile')
KINDS = (BLADE, COLOR)


# ---------------------------------------------------------------------- line files

class LineFile:
    """A text file as a list of lines (no endings) that's written back with its own
    dominant line ending. Undecodable bytes survive the round trip."""

    def __init__(self, path: Path):
        self.path = Path(path)
        raw = self.path.read_bytes().decode('utf-8', errors='surrogateescape') \
            if self.path.exists() else ''
        self.newline = '\r\n' if raw.count('\r\n') * 2 >= raw.count('\n') and '\r\n' in raw \
            else '\n'
        self.lines = raw.splitlines()

    def save(self):
        text = self.newline.join(self.lines) + (self.newline if self.lines else '')
        self.path.write_bytes(text.encode('utf-8', errors='surrogateescape'))


def _is_prose_comment(line: str) -> bool:
    """A // or # comment line that isn't a disabled ##key=value setting."""
    s = line.strip()
    if s.startswith('//'):
        return True
    if s.startswith('#'):
        return not _KEY_LINE_RE.match(s.lstrip('#'))
    return False


@dataclass
class Section:
    number: int
    header: int                     # line index of [profile=N]
    comment_start: int              # first line of the prose comments right above it
    end: int                        # exclusive: where the next section's comments begin
    values: Dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.values.get('pname') or self.values.get('cname') or ''

    def settings(self) -> Dict[str, str]:
        """The values that decide what the profile does - everything but its name."""
        return {k: v for k, v in self.values.items() if k not in NAME_KEYS}


def parse_sections(lf: LineFile, kind: LibraryKind) -> List[Section]:
    header_re = kind.header_re
    headers = [(i, int(m.group(1))) for i, line in enumerate(lf.lines)
               for m in [header_re.match(line)] if m]
    sections = []
    for idx, (h, number) in enumerate(headers):
        start = h
        while start > 0 and _is_prose_comment(lf.lines[start - 1]):
            start -= 1
        sections.append(Section(number, h, start, len(lf.lines)))
    for prev, nxt in zip(sections, sections[1:]):
        prev.end = nxt.comment_start
    for s in sections:
        for line in lf.lines[s.header + 1:s.end]:
            m = _KEY_LINE_RE.match(line)
            if m:
                s.values[m.group(1).strip().lower()] = m.group(2).strip()
    return sections


def _body_lines(lf: LineFile, s: Section) -> List[str]:
    """The section's setting lines (after the header), without trailing blank lines."""
    body = lf.lines[s.header + 1:s.end]
    while body and not body[-1].strip():
        body.pop()
    return body


# ---------------------------------------------------------------------- fonts & usage

def font_folders(root: Path) -> List[Tuple[int, str, Path]]:
    """[(number, name, path)] of the card's numbered font folders, by number."""
    fonts = []
    if root.is_dir():
        for item in root.iterdir():
            if item.is_dir() and item.name[:1].isdigit():
                number, _, name = item.name.partition('-')
                if number.isdigit():
                    fonts.append((int(number), name, item))
    return sorted(fonts)


def read_keys(path: Path) -> Dict[str, str]:
    """Active key=value lines of a flat file (font_config.txt)."""
    values = {}
    if path.is_file():
        for line in LineFile(path).lines:
            s = line.strip()
            if s.startswith('//') or s.startswith('#'):
                continue
            m = _KEY_LINE_RE.match(s)
            if m:
                values[m.group(1).lower()] = m.group(2).strip()
    return values


def read_prefs(root: Path) -> Dict[int, Dict[str, str]]:
    prefs, current = {}, None
    path = root / 'prefs.txt'
    if path.is_file():
        for line in LineFile(path).lines:
            s = line.strip()
            m = re.match(r'^\[font\s*=\s*(\d+)\]$', s, re.IGNORECASE)
            if m:
                current = int(m.group(1))
                prefs[current] = {}
            elif current is not None and not s.startswith('//'):
                km = _KEY_LINE_RE.match(s)
                if km:
                    prefs[current][km.group(1).lower()] = km.group(2).strip()
    return prefs


def _int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def active_profile(font_config: Dict[str, str], font_prefs: Dict[str, str],
                   kind: LibraryKind) -> Optional[int]:
    """The profile the board boots this font with: start_* unless it's -1 (or missing),
    else the last-used one prefs.txt stored for the font."""
    start = _int(font_config.get(kind.font_key), -1)
    if start is not None and start >= 0:
        return start
    return _int(font_prefs.get(kind.prefs_key))


def profile_usage(root: Path, kind: LibraryKind) -> Dict[int, List[str]]:
    """{profile number: ['3-LIGHT', ...]} - which fonts boot with each profile."""
    prefs = read_prefs(root)
    usage: Dict[int, List[str]] = {}
    for number, name, path in font_folders(root):
        config = read_keys(path / 'font_config.txt')
        profile = active_profile(config, prefs.get(number - 1, {}), kind)
        if profile is not None:
            usage.setdefault(profile, []).append(f"{number}-{name}")
    return usage


# ---------------------------------------------------------------------- font comments

def _is_font_list_comment(line: str) -> bool:
    s = line.strip()
    if not s.startswith('//'):
        return False
    items = [item.strip() for item in s[2:].split(',')]
    return bool(items) and all(_FONT_LIST_ITEM_RE.match(item) for item in items)


def _apply_font_comments(lf: LineFile, kind: LibraryKind, usage: Dict[int, List[str]]) -> bool:
    """Make the comment line right above each [profile=N] list the fonts using it
    ("//3-LIGHT, 7-ROGUE"), or drop it when no font does. Other comments are left alone.
    Works bottom-up so earlier line numbers stay valid. Returns True if anything changed."""
    changed = False
    for s in reversed(parse_sections(lf, kind)):
        fonts = usage.get(s.number, [])
        wanted = "//" + ", ".join(fonts) if fonts else None
        existing = next((i for i in range(s.comment_start, s.header)
                         if _is_font_list_comment(lf.lines[i])), None)
        if existing is not None:
            if wanted is None:
                del lf.lines[existing]
                changed = True
            elif lf.lines[existing].strip() != wanted:
                lf.lines[existing] = wanted
                changed = True
        elif wanted is not None:
            lf.lines.insert(s.header, wanted)
            changed = True
    return changed


def update_font_comments(root: Path, kinds=KINDS) -> List[Path]:
    """Refresh the font-name comments in config.txt and colors.txt. Returns the files changed."""
    changed = []
    for kind in kinds:
        path = root / kind.filename
        if not path.is_file():
            continue
        lf = LineFile(path)
        if _apply_font_comments(lf, kind, profile_usage(root, kind)):
            lf.save()
            changed.append(path)
    return changed


def font_comment_changes(root: Path, kind: LibraryKind) -> bool:
    """Whether update_font_comments would change this kind's file."""
    path = root / kind.filename
    if not path.is_file():
        return False
    return _apply_font_comments(LineFile(path), kind, profile_usage(root, kind))


# ---------------------------------------------------------------------- duplicates

@dataclass
class DuplicateGroup:
    kind: LibraryKind
    numbers: List[int]                  # ascending; numbers[0] is the one kept
    names: Dict[int, str]
    usage: Dict[int, List[str]]

    @property
    def keep(self) -> int:
        return self.numbers[0]

    @property
    def remove(self) -> List[int]:
        return self.numbers[1:]


def find_duplicates(root: Path, kind: LibraryKind) -> List[DuplicateGroup]:
    """Groups of profiles whose settings are exactly the same (names don't count)."""
    path = root / kind.filename
    if not path.is_file():
        return []
    sections = parse_sections(LineFile(path), kind)
    by_settings: Dict[tuple, List[Section]] = {}
    for s in sections:
        by_settings.setdefault(tuple(sorted(s.settings().items())), []).append(s)
    usage = profile_usage(root, kind)
    groups = []
    for same in by_settings.values():
        numbers = sorted({s.number for s in same})
        if len(numbers) > 1:
            groups.append(DuplicateGroup(kind, numbers, {s.number: s.name for s in same},
                                         {n: usage.get(n, []) for n in numbers}))
    return sorted(groups, key=lambda g: g.keep)


def _remap_mask(mask: str, mapping: Dict[int, int], old_count: int, new_count: int) -> str:
    """Rebuild a used_profiles_* bit-field after renumbering: a kept profile is browsable
    if any of the profiles merged into it were. Bits past the last profile keep their
    order; the end is padded with 1 (the manual's default)."""
    bits = mask.strip()
    new = ['0'] * new_count
    for old, target in mapping.items():
        if old >= len(bits) or bits[old] == '1':
            new[target] = '1'
    return (''.join(new) + bits[old_count:]).ljust(MAX_PROFILES, '1')[:MAX_PROFILES]


def set_keys(path: Path, updates: Dict[str, str]) -> None:
    """Replace active key=value lines (added at the end when missing)."""
    lf = LineFile(path)
    remaining = dict(updates)
    for i, line in enumerate(lf.lines):
        s = line.strip()
        if s.startswith('//') or s.startswith('#'):
            continue
        m = _KEY_LINE_RE.match(s)
        if m and m.group(1).lower() in remaining:
            key = m.group(1).lower()
            lf.lines[i] = f"{m.group(1)}={remaining.pop(key)}"
    lf.lines.extend(f"{k}={v}" for k, v in remaining.items())
    lf.save()


_PREFS_FONT_RE = re.compile(r'^\[font\s*=\s*(\d+)\]$', re.IGNORECASE)


def _set_prefs(root: Path, updates: Dict[int, Dict[str, str]]) -> None:
    """{font index: {key: value}} into prefs.txt; missing keys and [font=N] sections are added."""
    lf = LineFile(root / 'prefs.txt')
    headers = [(i, int(m.group(1))) for i, line in enumerate(lf.lines)
               for m in [_PREFS_FONT_RE.match(line.strip())] if m]
    found = set()
    for idx in range(len(headers) - 1, -1, -1):        # bottom-up keeps indices valid
        start, number = headers[idx]
        if number not in updates:
            continue
        found.add(number)
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lf.lines)
        pending = dict(updates[number])
        for i in range(start + 1, end):
            m = _KEY_LINE_RE.match(lf.lines[i].strip())
            if m and m.group(1).lower() in pending:
                lf.lines[i] = f"{m.group(1)}={pending.pop(m.group(1).lower())}"
        insert = end
        while insert > start + 1 and not lf.lines[insert - 1].strip():
            insert -= 1
        lf.lines[insert:insert] = [f"{k}={v}" for k, v in pending.items()]
    missing = [n for n in sorted(updates) if n not in found]
    if missing:
        while lf.lines and not lf.lines[-1].strip():
            lf.lines.pop()
        for n in missing:
            lf.lines += ['', f"[font={n}]"] + [f"{k}={v}" for k, v in updates[n].items()]
    lf.save()


def merge_duplicates(root: Path, groups: List[DuplicateGroup]) -> Dict[LibraryKind, Dict[int, int]]:
    """Remove the duplicate profiles in `groups`, renumber the rest so there are no gaps,
    and point every font (start_* in font_config.txt, the used_profiles_* masks, and the
    last-used profiles in prefs.txt) at the new numbers. Then refresh the font comments.
    Returns {kind: {old number: new number}}."""
    result = {}
    for kind in KINDS:
        kind_groups = [g for g in groups if g.kind == kind]
        if not kind_groups:
            continue
        lf = LineFile(root / kind.filename)
        sections = parse_sections(lf, kind)
        numbers = sorted({s.number for s in sections})
        merged_into = {n: g.keep for g in kind_groups for n in g.remove}
        kept = [n for n in numbers if n not in merged_into]
        new_number = {old: i for i, old in enumerate(kept)}
        mapping = {old: new_number[merged_into.get(old, old)] for old in numbers}

        for s in reversed(sections):
            if s.number in merged_into:
                del lf.lines[s.comment_start:s.end]
            elif mapping[s.number] != s.number:
                lf.lines[s.header] = f"[{kind.section}={mapping[s.number]}]"
        lf.save()

        old_count = (max(numbers) + 1) if numbers else 0
        prefs = read_prefs(root)
        prefs_updates = {}
        for number, _name, path in font_folders(root):
            config_path = path / 'font_config.txt'
            config = read_keys(config_path)
            updates = {}
            start = _int(config.get(kind.font_key), -1)
            if start is not None and start in mapping:
                updates[kind.font_key] = str(mapping[start])
            if kind.mask_key in config:
                remapped = _remap_mask(config[kind.mask_key], mapping, old_count, len(kept))
                if remapped != config[kind.mask_key]:
                    updates[kind.mask_key] = remapped
            if updates and config_path.is_file():
                set_keys(config_path, updates)
            stored = _int(prefs.get(number - 1, {}).get(kind.prefs_key))
            if stored is not None and stored in mapping and mapping[stored] != stored:
                prefs_updates[number - 1] = {kind.prefs_key: str(mapping[stored])}
        if prefs_updates:
            _set_prefs(root, prefs_updates)
        result[kind] = mapping
    update_font_comments(root)
    return result


# ---------------------------------------------------------------------- resources

def resource_root(card_root: Path, kind: str) -> Path:
    """/extra/<KIND>, matched case-insensitively (cards differ: GRAFX vs grafx)."""
    extra = card_root / 'extra'
    if extra.is_dir():
        for item in extra.iterdir():
            if item.is_dir() and item.name.lower() == kind.lower():
                return item
    return extra / kind


def resource_folders(card_root: Path, kind: str) -> Dict[int, Path]:
    folders = {}
    base = resource_root(card_root, kind)
    if base.is_dir():
        for item in base.iterdir():
            number, _, _name = item.name.partition('-')
            if item.is_dir() and number.isdigit():
                folders.setdefault(int(number), item)
    return folders


def _same_tree(a: Path, b: Path) -> bool:
    """Whether two folders hold the same files with the same contents (names of the
    folders themselves don't matter; .DS_Store and ._ files are ignored)."""
    def files(root):
        return {p.relative_to(root).as_posix().lower(): p for p in root.rglob('*')
                if p.is_file() and not p.name.startswith('.')}
    fa, fb = files(a), files(b)
    return fa.keys() == fb.keys() and all(filecmp.cmp(fa[k], fb[k], shallow=False) for k in fa)


# ---------------------------------------------------------------------- import

@dataclass
class ProfilePlan:
    kind: LibraryKind
    source_number: int
    name: str
    target_number: int
    reused: bool                         # an identical profile was already on the card
    body: List[str] = field(default_factory=list)   # setting lines to write (when new)
    comments: List[str] = field(default_factory=list)  # its own comments, e.g. "//Lime"


@dataclass
class ResourcePlan:
    kind: str                            # GRAFX / ACCENTS / PIXIES
    source_number: int
    source: Optional[Path]
    target_number: int
    reused: bool
    dest: Optional[Path] = None


@dataclass
class ImportPlan:
    source_font: Path
    target_root: Path
    dest_font: Path
    font_number: int
    profiles: List[ProfilePlan] = field(default_factory=list)
    resources: List[ResourcePlan] = field(default_factory=list)
    font_config: Dict[str, str] = field(default_factory=dict)
    prefs: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def source_card_root(font_folder: Path) -> Path:
    return Path(font_folder).parent


def check_source(font_folder: Path) -> List[str]:
    """Why a folder can't be imported (empty if it can)."""
    font_folder = Path(font_folder)
    problems = []
    if not (font_folder / 'font_config.txt').is_file():
        problems.append(f"{font_folder.name} has no font_config.txt.")
    root = source_card_root(font_folder)
    for name in ('config.txt', 'colors.txt'):
        if not (root / name).is_file():
            problems.append(f"Its card folder ({root.name}) has no {name}.")
    return problems


def mask_profiles(mask: Optional[str], available: Set[int]) -> List[int]:
    if not mask:
        return sorted(available)
    return sorted(n for n in available if n < len(mask.strip()) and mask.strip()[n] == '1')


def plan_import(source_font: Path, target_root: Path, include_browsable: bool = False) -> ImportPlan:
    """Work out everything an import would do, without writing anything."""
    source_font, target_root = Path(source_font), Path(target_root)
    source_root = source_card_root(source_font)
    fonts = font_folders(target_root)
    number = (fonts[-1][0] + 1) if fonts else 1
    _, _, name = source_font.name.partition('-')
    if not source_font.name[:1].isdigit() or not name:
        name = source_font.name
    plan = ImportPlan(source_font, target_root, target_root / f"{number}-{name}", number)
    plan.errors += check_source(source_font)
    if plan.errors:
        return plan
    if plan.dest_font.exists():
        plan.errors.append(f"{plan.dest_font.name} already exists on this card.")
    if any(n.upper() == name.upper() for _, n, _ in fonts):
        plan.warnings.append(f"This card already has a font called {name}.")
    try:
        if source_root.resolve() == target_root.resolve():
            plan.errors.append("That font is already on this card.")
    except OSError:
        pass

    config = read_keys(source_font / 'font_config.txt')
    source_number = _int(source_font.name.partition('-')[0], 0)
    source_prefs = read_prefs(source_root).get(source_number - 1, {})
    allocated: Dict[str, Set[int]] = {}

    def map_resource(kind: str, source_index: int) -> int:
        for r in plan.resources:
            if r.kind == kind and r.source_number == source_index:
                return r.target_number
        source = resource_folders(source_root, kind).get(source_index)
        target = resource_folders(target_root, kind)
        if source is None:
            plan.warnings.append(
                f"{kind} resource {source_index} isn't on the source card; the profile keeps "
                f"pointing at {source_index}"
                + (f" ({target[source_index].name} here)." if source_index in target else "."))
            plan.resources.append(ResourcePlan(kind, source_index, None, source_index, True))
            return source_index
        for index in sorted(target):
            if _same_tree(source, target[index]):
                plan.resources.append(ResourcePlan(kind, source_index, source, index, True,
                                                   target[index]))
                return index
        used = set(target) | allocated.setdefault(kind, set())
        index = 0
        while index in used:
            index += 1
        allocated[kind].add(index)
        _, _, rest = source.name.partition('-')
        dest = resource_root(target_root, kind) / f"{index}-{rest or kind}"
        plan.resources.append(ResourcePlan(kind, source_index, source, index, False, dest))
        return index

    for kind in KINDS:
        source_lf = LineFile(source_root / kind.filename)
        source_sections = {s.number: s for s in parse_sections(source_lf, kind)}
        target_path = target_root / kind.filename
        target_sections = parse_sections(LineFile(target_path), kind) if target_path.is_file() else []
        by_settings = {}
        for s in target_sections:
            by_settings.setdefault(tuple(sorted(s.settings().items())), s.number)
        next_number = (max((s.number for s in target_sections), default=-1) + 1)

        active = active_profile(config, source_prefs, kind)
        if active not in source_sections:
            fallback = min(source_sections, default=None)
            if fallback is None:
                plan.errors.append(f"The source {kind.filename} has no {kind.label}s.")
                continue
            plan.warnings.append(
                f"The font's {kind.label} ({active}) isn't in the source {kind.filename}; "
                f"using {kind.label} {fallback} instead.")
            active = fallback
        wanted = [active]
        if include_browsable:
            wanted += [n for n in mask_profiles(config.get(kind.mask_key), set(source_sections))
                       if n != active]

        mapping = {}
        for n in wanted:
            section = source_sections[n]
            body = _body_lines(source_lf, section)
            if kind is BLADE:
                for i, line in enumerate(body):
                    m = _KEY_LINE_RE.match(line)
                    key = m.group(1).lower() if m else None
                    value = _int(m.group(2)) if m else None
                    if key in RESOURCE_KEYS and value is not None and value >= 0:
                        new_index = map_resource(RESOURCE_KEYS[key], value)
                        body[i] = f"{m.group(1)}={new_index}"
            values = {}
            for line in body:
                m = _KEY_LINE_RE.match(line.strip())
                if m:
                    values[m.group(1).strip().lower()] = m.group(2).strip()
            settings = tuple(sorted((k, v) for k, v in values.items() if k not in NAME_KEYS))
            if settings in by_settings:
                target = by_settings[settings]
                plan.profiles.append(ProfilePlan(kind, n, section.name, target, True))
            else:
                target = next_number
                next_number += 1
                by_settings[settings] = target
                comments = [line for line in source_lf.lines[section.comment_start:section.header]
                            if not _is_font_list_comment(line)]
                plan.profiles.append(ProfilePlan(kind, n, section.name, target, False, body,
                                                 comments))
            mapping[n] = target
        if next_number > MAX_PROFILES:
            plan.errors.append(
                f"This would take {kind.filename} to {next_number} {kind.label}s - the board "
                f"allows {MAX_PROFILES}. Use Check Duplicate Profiles to free some up, or "
                f"untick the extra profiles.")

        plan.font_config[kind.font_key] = str(mapping[active])
        if include_browsable:
            mask = ['0'] * MAX_PROFILES
            for target in mapping.values():
                if target < MAX_PROFILES:
                    mask[target] = '1'
            plan.font_config[kind.mask_key] = ''.join(mask)
        else:
            plan.font_config[kind.mask_key] = '1' * MAX_PROFILES
        plan.prefs[kind.prefs_key] = str(mapping[active])
    return plan


def run_import(plan: ImportPlan) -> Path:
    """Carry out a plan from plan_import (which must have no errors)."""
    if plan.errors:
        raise ValueError("; ".join(plan.errors))
    root = plan.target_root
    shutil.copytree(plan.source_font, plan.dest_font,
                    ignore=shutil.ignore_patterns('.DS_Store', '._*'))
    for r in plan.resources:
        if not r.reused and r.source is not None:
            r.dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(r.source, r.dest, ignore=shutil.ignore_patterns('.DS_Store', '._*'))
    for kind in KINDS:
        new = [p for p in plan.profiles if p.kind == kind and not p.reused]
        if not new:
            continue
        lf = LineFile(root / kind.filename)
        while lf.lines and not lf.lines[-1].strip():
            lf.lines.pop()
        for p in sorted(new, key=lambda p: p.target_number):
            lf.lines += ['', ''] + p.comments + [f"[{kind.section}={p.target_number}]"] + p.body
        lf.save()
    set_keys(plan.dest_font / 'font_config.txt', plan.font_config)
    _set_prefs(root, {plan.font_number - 1: plan.prefs})
    update_font_comments(root)
    return plan.dest_font
