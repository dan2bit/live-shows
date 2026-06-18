#!/usr/bin/env python3
"""
pre-commit-staleness.py

Pre-commit hook: warns if live_shows_current.tsv or live_shows_potential.tsv
were last fetched from GitHub more than STALE_MINUTES ago.

Staleness is measured by comparing the file's mtime against now.
A file touched locally (e.g. by the MCP or a script) resets its mtime,
so a fresh fetch always clears the warning.

Install via:
    python scripts/install-hooks.py
or manually:
    cp scripts/pre-commit-staleness.py .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
"""

import sys
import os
import time
from pathlib import Path

STALE_MINUTES = 30
WATCHED = [
    "live_shows_current.tsv",
    "live_shows_potential.tsv",
]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    now = time.time()
    warnings = []

    for filename in WATCHED:
        path = repo_root / filename
        if not path.exists():
            continue
        # Only warn if the file is staged for this commit
        staged = os.popen(f"git diff --cached --name-only").read().splitlines()
        if filename not in staged:
            continue
        age_seconds = now - path.stat().st_mtime
        age_minutes = age_seconds / 60
        if age_minutes > STALE_MINUTES:
            warnings.append(
                f"  {filename}: last modified {age_minutes:.0f} min ago "
                f"(threshold: {STALE_MINUTES} min)"
            )

    if warnings:
        print("\n⚠  STALENESS WARNING — committing potentially stale TSV files:")
        for w in warnings:
            print(w)
        print(
            "\n   If you fetched a fresh copy this session, touch the file to reset mtime:\n"
            "     touch live_shows_current.tsv\n"
            "   To skip this check for this commit:\n"
            "     git commit --no-verify\n"
        )
        return 1  # Block the commit

    return 0


if __name__ == "__main__":
    sys.exit(main())
