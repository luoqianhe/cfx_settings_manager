# src/core/grafx_timing_fix.py
"""Fixes for the GraFx warnings the validation pass finds - the timing problems
core.grafx_timing.check_resource reports, plus grafx_reader.many_problems:

  * many_mismatch - a section's many= doesn't match its BMP files (the board only loads the
    files many= declares; a missing many= means none). Fix by setting many= to the files
    that are numbered 1..N.

  * too_many_stages - a synced animation has more stages than its sound / qon / qoff can
    show at the blade's refreshfx, so the board never reaches the end. Fix by squashing it
    to the number of stages that fit (it then plays to the end, in the same time), or by
    lowering refreshfx so every stage gets its turn (only when that stays >= 6 ms).
  * delay_too_fast - delay is below refreshfx, so the animation runs slower than intended.
    Fix by setting delay to refreshfx and squashing the stages in proportion (same length
    as intended), or by lowering refreshfx to the delay.

The same BMP can be checked against several fonts (each with its own sounds/refreshfx), so
warnings are grouped per file - or, for delay fixes, per grafx1.txt section, since delay is
shared by every variant of a state - and a fix satisfies all of them at once.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6 import QtGui

from core import grafx_reader
from core.grafx_timing import resample_stages
from core.grafx_writer import save_bmp, update_config_section
from core.profile_library import BLADE, set_keys, set_profile_value

MIN_REFRESH_MS = 6       # the manual's lower bound for refreshfx

SHRINK, RETIME, REFRESH, SET_MANY, SKIP = 'shrink', 'retime', 'refresh', 'set_many', 'skip'


@dataclass
class TimingFix:
    kind: str                         # too_many_stages / delay_too_fast / many_mismatch
    folder: Path
    state: str
    files: List[Tuple[Path, int, int]]     # (bmp, current stages, stages after SHRINK/RETIME)
    warnings: List[dict]
    new_delay: Optional[int] = None        # RETIME: the section's new delay
    new_many: Optional[int] = None         # SET_MANY: the section's new many=
    new_refresh: Optional[int] = None      # REFRESH: refreshfx that would fix it
    refresh_targets: List[Tuple[str, object]] = field(default_factory=list)  # ('blade', n) / ('font', path)

    @property
    def fonts(self) -> List[str]:
        return sorted({f"{w['font_num']}-{w['font_name']}" for w in self.warnings},
                      key=lambda s: int(s.split('-')[0]))

    @property
    def section(self) -> str:
        return grafx_reader.GRAFX_STATES[self.state][0]

    def options(self) -> List[Tuple[str, str]]:
        """[(action, label)] in order of preference; the first is the default."""
        options = []
        if self.kind == 'many_mismatch':
            return [(SET_MANY, f"Set many={self.new_many} in grafx1.txt"),
                    (SKIP, "Leave as it is")]
        if self.kind == 'too_many_stages':
            path, stages, target = self.files[0]
            options.append((SHRINK, f"Squash to {target} stages (plays to the end)"))
        else:
            options.append((RETIME, f"Set delay to {self.new_delay} ms and squash to "
                                    + ", ".join(str(t) for _p, _s, t in self.files)
                                    + " stages (same length)"))
        if self.new_refresh is not None:
            options.append((REFRESH, f"Lower refreshfx to {self.new_refresh} ms ("
                                     + self._refresh_target_text() + ")"))
        options.append((SKIP, "Leave as it is"))
        return options

    def _refresh_target_text(self) -> str:
        parts = []
        for kind, target in self.refresh_targets:
            parts.append(f"blade profile {target}" if kind == 'blade' else f"{Path(target).name} font_config.txt")
        return ", ".join(parts) + " - affects every animation and font using it"


def _refresh_targets(warnings: List[dict]) -> Optional[List[Tuple[str, object]]]:
    """Where to lower refreshfx so every warned font picks it up - None if any font's
    refreshfx comes from somewhere this can't edit (config.txt's global header)."""
    targets = []
    for w in warnings:
        source = w.get('refresh_source')
        if source == 'blade' and w.get('blade_profile') is not None:
            target = ('blade', w['blade_profile'])
        elif source == 'font':
            target = ('font', Path(w['font_path']) / 'font_config.txt')
        else:
            return None
        if target not in targets:
            targets.append(target)
    return targets


def plan_fixes(warnings: List[dict]) -> List[TimingFix]:
    fixes = []
    by_file: Dict[Path, List[dict]] = {}
    by_section: Dict[Tuple[Path, str], List[dict]] = {}
    by_many: Dict[Tuple[Path, str], List[dict]] = {}
    for w in warnings:
        if w.get('kind') == 'many_mismatch':
            by_many.setdefault((Path(w['folder']), w['state']), []).append(w)
        elif w.get('kind') == 'too_many_stages':
            by_file.setdefault(Path(w['path']), []).append(w)
        elif w.get('kind') == 'delay_too_fast':
            by_section.setdefault((Path(w['folder']), w['state']), []).append(w)

    for path, group in by_file.items():
        stages = group[0]['stages']
        target = min(w['fits'] for w in group)
        fix = TimingFix('too_many_stages', Path(group[0]['folder']), group[0]['state'],
                        [(path, stages, target)], group)
        refresh = int(min(w['needed_ms'] for w in group))
        targets = _refresh_targets(group)
        if refresh >= MIN_REFRESH_MS and targets:
            fix.new_refresh, fix.refresh_targets = refresh, targets
        fixes.append(fix)

    for (folder, state), group in by_section.items():
        old_delay = group[0]['delay']
        new_delay = max(w['refresh'] for w in group)
        files = []
        for entry in grafx_reader.list_grafx_files(folder):
            if entry.state == state:
                stages = QtGui.QImageReader(str(entry.path)).size().height()
                files.append((entry.path, stages, max(1, round(stages * old_delay / new_delay))))
        fix = TimingFix('delay_too_fast', folder, state, files, group, new_delay=new_delay)
        targets = _refresh_targets(group)
        if old_delay >= MIN_REFRESH_MS and targets:
            fix.new_refresh, fix.refresh_targets = old_delay, targets
        fixes.append(fix)
    for (folder, state), group in by_many.items():
        if group[0]['available'] < 1:
            continue            # no <prefix>1.bmp - renaming files is beyond a config fix
        files = [(entry.path, 0, 0) for entry in grafx_reader.list_grafx_files(folder)
                 if entry.state == state and entry.variant <= group[0]['available']]
        fixes.append(TimingFix('many_mismatch', folder, state, files, group,
                               new_many=group[0]['available']))
    # Missing files first - they stop an animation playing at all.
    return sorted(fixes, key=lambda f: (f.kind != 'many_mismatch', f.folder.name, f.state,
                                        str(f.files[0][0]) if f.files else ''))


def apply_fixes(card_root: Path, choices: List[Tuple[TimingFix, str]],
                backup: Optional[Callable[[Path, str], None]] = None) -> List[str]:
    """Apply (fix, action) pairs in place, backing each file up first with
    backup(path, label). Returns a line per change made."""
    done = []
    refresh_changes: Dict[Tuple[str, object], int] = {}

    def back_up(path: Path, label: str):
        if backup is not None:
            backup(path, label)

    for fix, action in choices:
        label = f"extra/GRAFX/{fix.folder.name}"
        if action == SET_MANY:
            txt = fix.folder / 'grafx1.txt'
            back_up(txt, label)
            update_config_section(txt, fix.section, {'many': str(fix.new_many)})
            done.append(f"{fix.folder.name}/grafx1.txt [{fix.section}]: many={fix.new_many}")
        elif action in (SHRINK, RETIME):
            for path, stages, target in fix.files:
                if target == stages:
                    continue
                image = QtGui.QImage(str(path))
                if image.isNull():
                    raise OSError(f"Couldn't read {path.name}")
                back_up(path, label)
                if not save_bmp(resample_stages(image, target), path):
                    raise OSError(f"Couldn't write {path.name}")
                done.append(f"{fix.folder.name}/{path.name}: {stages} → {target} stages")
            if action == RETIME:
                txt = fix.folder / 'grafx1.txt'
                back_up(txt, label)
                update_config_section(txt, fix.section, {'delay': str(fix.new_delay)})
                done.append(f"{fix.folder.name}/grafx1.txt [{fix.section}]: delay={fix.new_delay}")
        elif action == REFRESH:
            for target in fix.refresh_targets:
                current = refresh_changes.get(target)
                refresh_changes[target] = fix.new_refresh if current is None else min(current, fix.new_refresh)

    for (kind, target), value in refresh_changes.items():
        if kind == 'blade':
            back_up(card_root / 'config.txt', "(root)")
            set_profile_value(card_root, BLADE, target, 'refreshfx', str(value))
            done.append(f"config.txt [profile={target}]: refreshfx={value}")
        else:
            back_up(Path(target), Path(target).parent.name)
            set_keys(Path(target), {'refreshfx': str(value)})
            done.append(f"{Path(target).parent.name}/font_config.txt: refreshfx={value}")
    return done
