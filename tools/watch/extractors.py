"""
extractors.py - per-site page parsing for the watch system.

Two things live here: a small dependency-free HTML-to-visible-text helper
(visible_lines), used by every "artist"-kind watch and by any "venue"-kind
extractor that wants a starting point; and the EXTRACTORS registry, keyed by
the string a watches.tsv row's `extractor` column names.

An EXTRACTORS entry is a dict:
    {
        "extract": fn(html_text) -> [{"date": "YYYY-MM-DD", "title": str,
                                       "status": str}, ...],
        "offprofile": fn(title) -> bool,   # optional - a fast, free, source-
                                            # specific negative signal, checked
                                            # before any scoring API call
    }

Adding a new venue-kind site means adding one function here and one row in
watches.tsv - see tools/playbooks/skills/watch-manager/SKILL.md for the
conversational path. An "artist"-kind site (a single-subject tour page) needs
no entry here at all - watch_diff.py diffs its cleaned text directly.
"""

import re
from datetime import date
from html import unescape
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "div", "p", "tr", "td", "th", "li", "ul", "ol", "h1", "h2", "h3", "h4",
    "h5", "h6", "section", "article", "header", "footer", "nav", "table",
    "br", "hr", "main", "aside", "form",
}


class _TextExtractor(HTMLParser):
    """Visible-text-with-line-breaks, stdlib only.

    Not CSS-aware - display:none content is still extracted, and there is no
    concept of reading order beyond document order. Good enough for a page
    whose event listing is a flat, repeating block structure; a page that
    fails against this (heavy client-side rendering, a shuffled DOM) is a
    real signal this surface may not be a good headless-watch candidate at
    all, not just a parser bug to patch around.
    """

    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.chunks.append(data)


def visible_lines(html_text):
    """html_text -> list of non-empty, whitespace-collapsed visible lines."""
    p = _TextExtractor()
    p.feed(html_text or "")
    text = unescape("".join(p.chunks))
    lines = (re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines())
    return [ln for ln in lines if ln]


# ---- Blues Alley (InstantSeats venue listing) ------------------------------
#
# Calibrated from the historical changedetection diff evidence rather than a
# live fetch (not reachable this session) - e.g. a block reading roughly:
#
#   Fri
#   09.18
#   Claudia Acuna "Queen of Chilean Jazz"- Chilean Jazz Series
#   Event Info
#   Get Tickets
#   Off Sale        (or "Sold Out", or absent when on sale)
#   7:00 PM
#   9:30 PM
#
# Day-of-week and MM.DD anchor each block; "Event Info"/"Get Tickets" are
# reliable boilerplate; a status word and one or two showtimes close it out.
# Because those email snippets were truncated previews, not full bodies, some
# evidence fragments were missing their date line entirely - treat this as a
# best-effort first pass, not verified ground truth. It logs a warning when it
# parses suspiciously few events (see watch_diff.py's sanity floor), and its
# first real run's output belongs in front of a human before being trusted.

_DAY_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$", re.I)
_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*[AP]M$", re.I)
_BOILERPLATE = {"event info", "get tickets"}
_STATUS_WORDS = {"off sale", "sold out"}


def _year_for(month, day, today=None):
    """Assume the nearer of this year / next year to today - a venue listing
    only ever shows near-future dates, so a month well behind today's means
    the calendar rolled into next year."""
    today = today or date.today()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return year
    if (today - candidate).days > 180:
        year += 1
    return year


def blues_alley(html_text):
    lines = visible_lines(html_text)
    events = []
    cur_date = None
    title_buf = []
    status = None

    def flush():
        nonlocal title_buf, status
        if cur_date and title_buf:
            title = " ".join(title_buf).strip(" -\u2013\u2014")
            if title:
                events.append({"date": cur_date, "title": title, "status": status or ""})
        title_buf, status = [], None

    for ln in lines:
        low = ln.lower()
        if _DAY_RE.match(ln):
            continue
        m = _DATE_RE.match(ln)
        if m:
            flush()
            mm, dd = int(m.group(1)), int(m.group(2))
            cur_date = "%04d-%02d-%02d" % (_year_for(mm, dd), mm, dd)
            continue
        if low in _BOILERPLATE:
            continue
        if low in _STATUS_WORDS:
            status = ln
            continue
        if _TIME_RE.match(ln):
            continue
        if cur_date:
            title_buf.append(ln)
    flush()
    return events


_OFFPROFILE_MARKERS = (
    "jazz series", "jazz month", "jazz camp", "jazz society",
    "chilean jazz", "brazilian jazz", "hispanic heritage jazz",
)


def blues_alley_offprofile(title):
    """Fast, free, zero-API negative signal from the venue's own labeling.

    Deliberately narrow phrases (not a bare "jazz" or "livestream") so a
    genuinely relevant show that happens to mention either word in passing
    isn't silently dropped before it ever reaches real scoring.
    """
    low = title.lower()
    return any(marker in low for marker in _OFFPROFILE_MARKERS)


EXTRACTORS = {
    "blues_alley": {"extract": blues_alley, "offprofile": blues_alley_offprofile},
}
