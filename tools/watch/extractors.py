"""
extractors.py - per-site page parsing for the watch system.

Three things live here: a small dependency-free HTML-to-visible-text helper
(visible_lines), used by every "artist"-kind watch by default and by any
"venue"-kind extractor that wants a starting point; a generic image-URL
extractor (image_urls) for the rare "artist"-kind site whose real signal is
which image is referenced rather than any visible text; and the EXTRACTORS
registry, keyed by the string a watches.tsv row's `extractor` column names.

An EXTRACTORS entry is a dict with either or both of:
    {
        "extract": fn(html_text) -> [{"date": "YYYY-MM-DD", "title": str,
                                       "status": str}, ...],
        "offprofile": fn(title) -> bool,   # optional - a fast, free, source-
                                            # specific negative signal, checked
                                            # before any scoring API call
        "lines": fn(html_text) -> [str, ...],
    }

"extract" (+ optional "offprofile") is read by watch_diff.py for a
"venue"-kind row - structured event records, diffed as a set. "lines" is read
for an "artist"-kind row that names an extractor explicitly - a whole-page
diff over whatever this function returns instead of the default
visible_lines() output. An "artist"-kind row with no extractor named (the
common case) needs no entry here at all - watch_diff.py calls visible_lines()
directly.

Adding a new venue-kind site means adding one function here and one row in
watches.tsv - see tools/playbooks/skills/watch-manager/SKILL.md for the
conversational path.
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


# ---- Hamilton Live (calendar page) -----------------------------------------
#
# Confirmed against the live page (not just historical evidence, unlike Blues
# Alley) via Claude-for-Chrome DOM inspection 2026-09-19: real, semantic,
# class-named markup, fully server-rendered - no JS gap at all. Each event is
# anchored by a stable class name (detail_seetickets_eventtitle); fields are
# extracted by their human-readable <div class="label">...</div> text rather
# than by field position or by the optional-field wrapper's own class name,
# since not every event carries every field (Loft Late Night shows omit Min
# Ticket Price; most omit Opener and Age). Cross-checked two independent ways
# against the real live page (a DOM query walk and this exact regex-chunking
# approach, run in the browser) - both agreed exactly (48 events, same data)
# before this was committed.

_HAM_TITLE_RE = re.compile(r'<div class="detail_seetickets_eventtitle">.*?<h1>(.*?)</h1>', re.S)
_HAM_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
               "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
_HAM_DATE_RE = re.compile(r"^\w{3}\s+(\w{3})\s+(\d{1,2})$")


def _strip_tags(s):
    return unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _hamilton_date(s):
    m = _HAM_DATE_RE.match(s.strip())
    if not m:
        return None
    mon = _HAM_MONTHS.get(m.group(1))
    if not mon:
        return None
    return "%04d-%02d-%02d" % (_year_for(mon, int(m.group(2))), mon, int(m.group(2)))


def hamilton_live(html_text):
    events = []
    matches = list(_HAM_TITLE_RE.finditer(html_text))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else start + 6000
        chunk = html_text[start:end]
        title = _strip_tags(m.group(1))

        def field(label, chunk=chunk):
            fm = re.search(
                r'<div class="label">\s*%s\s*</div>\s*<div class="name">(.*?)</div>'
                % re.escape(label), chunk, re.S)
            return _strip_tags(fm.group(1)) if fm else None

        date_str = field("Event Date")
        if not title or not date_str:
            continue
        iso_date = _hamilton_date(date_str)
        if not iso_date:
            continue
        events.append({"date": iso_date, "title": title, "status": field("Status") or ""})
    return events


# ---- Generic: image URLs on a page, as pseudo-text-lines -------------------
#
# For an "artist"-kind watch whose real signal lives in which image is
# referenced rather than in any visible text - a small venue that posts its
# calendar as a flyer image with the month baked into the filename (e.g. JV's
# Restaurant: JV_NEW_FLYER_DESIGN_SEPT_2026_...) rather than running a real
# ticketing platform. This never reads the image itself - OCR is out of scope
# for this system - it only diffs which image URL the page currently
# references, which is enough to answer "did a new one go up" without ever
# seeing what is on it. Pair with the row's own ignore_contains to exclude a
# static image on the same page that never signals anything (a logo, a "how
# to book us" flyer) and would otherwise fire a spurious mail if it changed.
#
# Reads the raw HTML only - not visible_lines() output, since some sites swap
# an <img> tag's src to an inline data: URI via client-side JS after load
# (confirmed on JV's Restaurant's own calendar page, 2026-09-19); that JS
# never runs against a plain fetch, so the raw HTML this function sees always
# carries the real, informative filename regardless.

def image_urls(html_text):
    return re.findall(r'<img[^>]+src="([^"]+)"', html_text)


EXTRACTORS = {
    "blues_alley": {"extract": blues_alley, "offprofile": blues_alley_offprofile},
    "hamilton_live": {"extract": hamilton_live},
    "image_urls": {"lines": image_urls},
}
