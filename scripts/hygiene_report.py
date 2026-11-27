#!/usr/bin/env python3
"""hygiene_report.py — shared finding collector for the data-hygiene checks.

Each check records findings here instead of only printing them. The collector
owns the three things the checks previously did inconsistently or not at all:

  1. Emits the GitHub Actions ``::warning`` annotation, in the same shape the
     checks emitted before.
  2. Appends a section to ``$GITHUB_STEP_SUMMARY`` when that variable is set,
     so findings render on the run's front page rather than living only as
     inline annotations. Written on clean runs too, so the summary always
     states the current position instead of going quiet when there is nothing
     to report.
  3. Decides the exit code. Default is 0 (advisory). Strict mode returns 1,
     optionally scoped to a set of paths, so a push can be judged on the files
     it actually touched rather than on the state of the whole repo.

A warn-only check that annotates a green run has no reader: the annotations sit
behind a check mark nobody clicks. The summary is the record and the exit code
is the notification; this module is where both are decided.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import os
from pathlib import Path


def _norm(path):
    return str(Path(path)) if path else None


def owner_names(root=None):
    """The names in config.yaml's site.owner_name, as a list (empty when unset).

    One name or a list of names. Checks that keep a person's name out of code
    read it from here so the name itself never has to appear in a script.
    """
    import re
    cfg = Path(root or Path(__file__).resolve().parent.parent) / "config.yaml"
    if not cfg.exists():
        return []
    text = cfg.read_text(encoding="utf-8")
    try:
        import yaml
        val = ((yaml.safe_load(text) or {}).get("site") or {}).get("owner_name")
    except ImportError:
        m = re.search(r"^\s+owner_name:\s*([^#\n]*)", text, re.M)
        val = m.group(1).strip().strip("\"'[]") if m else None
        if val and "," in val:
            val = [v.strip().strip("\"'") for v in val.split(",")]
    if isinstance(val, str):
        val = [val]
    return [str(v).strip() for v in (val or []) if str(v).strip()]


class Report:
    """Collects findings for one check and decides how they are delivered."""

    def __init__(self, name):
        self.name = name
        self.findings = []  # list of (path, line, message)

    # ---- recording -------------------------------------------------------

    def warn(self, message, path=None, line=None):
        """Record a finding and emit its annotation immediately."""
        self.findings.append((_norm(path), line, message))
        loc = ""
        if path:
            loc = " file=" + str(path) + (f",line={line}" if line else "")
        print(f"::warning{loc}::{message}")

    @property
    def count(self):
        return len(self.findings)

    def in_scope(self, paths):
        """Findings whose file is in ``paths``. None means 'everything'.

        Findings with no file attached (whole-repo observations, e.g. a
        duplicate alias key) are never scoped in: a push cannot be blamed for
        them, so they stay advisory even under a scoped --strict.
        """
        if paths is None:
            return list(self.findings)
        want = {_norm(p) for p in paths}
        return [f for f in self.findings if f[0] in want]

    # ---- delivery --------------------------------------------------------

    def _markdown(self):
        lines = [f"### {self.name}", ""]
        if not self.findings:
            lines += ["No findings.", ""]
            return "\n".join(lines)
        lines += [f"**{self.count} finding(s)**", "",
                  "| File | Line | Finding |", "| --- | --- | --- |"]
        for path, line, message in self.findings:
            cell = message.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {path or '-'} | {line or '-'} | {cell} |")
        lines.append("")
        return "\n".join(lines)

    def write_summary(self):
        """Append this check's section to the job summary, if running in CI."""
        dest = os.environ.get("GITHUB_STEP_SUMMARY")
        if not dest:
            return False
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(self._markdown() + "\n")
        return True

    def finish(self, strict=False, scope=None):
        """Write the summary, print the tally, and return the exit code."""
        self.write_summary()
        print(f"{self.name}: {self.count} warning(s)." if self.findings
              else f"{self.name}: clean.")
        if not strict:
            return 0
        blocking = self.in_scope(scope)
        if not blocking:
            if self.findings:
                print(f"{self.name}: --strict satisfied "
                      f"({self.count} advisory finding(s) outside the checked scope).")
            return 0
        print(f"::error::{self.name}: {len(blocking)} blocking finding(s) — "
              f"see the annotations above.")
        return 1


def scope_from_args(files):
    """Normalize a --strict file list. Empty list means 'the whole repo'."""
    return None if not files else [_norm(f) for f in files]
