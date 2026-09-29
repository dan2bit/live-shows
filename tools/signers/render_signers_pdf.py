#!/usr/bin/env python3
"""Render the single-page print PDF for the signers page.

Reads signers/index.html (built by render_signers.py) and writes
signers/<print_pdf> - the file the web page links as "Print" - with
WeasyPrint, applying the page's own @media print rules. It is the same
layout a browser prints, but built in one place with known fonts, so the
sheet Dan carries to a show does not depend on whose browser made it.

Two guarantees, both learned by testing rather than assumed:

  * Reproducible. WeasyPrint stamps the current time into the PDF, so two
    builds of an unchanged page differ byte for byte and CI would commit a
    new binary on every run. SOURCE_DATE_EPOCH is pinned to the newest
    signature date instead (a deterministic function of the data), so an
    unchanged page gives an identical file and git sees nothing to commit.
  * One page. The print layout is tuned to fit exactly one sheet. If the
    list grows past that this exits non-zero rather than quietly writing a
    two-page file; the fix is print_column_count / the print font sizes in
    tools/signers/.

Usage (repo root, after render_signers.py):
    pip install weasyprint
    python3 tools/signers/render_signers_pdf.py
"""
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_signers as rs  # shared paths, TSV loader and config validation


def source_epoch(rows):
    """Newest show_date at 00:00 UTC, as SOURCE_DATE_EPOCH wants it."""
    newest = max(r["show_date"] for r in rows)
    day = datetime.datetime.strptime(newest, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    return str(int(day.timestamp()))


def main():
    cfg = rs.load_config()
    rows = rs.load_tsv(rs.HAT_SIGNATURES_TSV)
    if not rows:
        sys.exit("hat_signatures.tsv has no rows - nothing to print.")
    if not rs.OUTPUT_HTML.is_file():
        sys.exit(f"{rs.OUTPUT_HTML} does not exist - run render_signers.py first.")

    os.environ["SOURCE_DATE_EPOCH"] = source_epoch(rows)
    try:
        from weasyprint import HTML
    except ImportError:
        sys.exit("weasyprint is required for the print PDF: pip install weasyprint")

    document = HTML(filename=str(rs.OUTPUT_HTML)).render()
    pages = len(document.pages)
    if pages != 1:
        sys.exit(f"print layout is {pages} pages, must be exactly 1 - raise print_column_count "
                  f"in tools/signers/signers.yaml or tighten the print font sizes in "
                  f"tools/signers/signers.template.html, then rebuild.")

    out = rs.OUTPUT_HTML.parent / cfg["print_pdf"]
    document.write_pdf(str(out))
    print(f"wrote {out} ({out.stat().st_size} bytes, 1 page)")


if __name__ == "__main__":
    main()
