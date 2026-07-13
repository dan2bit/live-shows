#!/usr/bin/env python3
"""
name_forms.py — the one place that knows when two artist strings mean the same thing.

Before this module the rule lived in three copies (build_recommend_index.surface_forms,
app.js _goalBillKeys, audit_goal_badges.bill_keys) and was missing from a fourth consumer
(spotify_cache), which is how bill-named cache entries ended up with a null Last.fm block
(#160).

TWO QUESTIONS, DELIBERATELY KEPT APART
--------------------------------------
They look similar and must never be merged:

  surface_forms(raw)     "spelled differently — SAME entity"
                         de-invert "X, The"; drop a trailing " Band".
                         Used for IDENTITY. build_recommend_index unions any two records
                         that share a variant key, so this must NOT split a bill into its
                         members: "Tab Benoit & Anders Osborne" -> {tab benoit,
                         anders osborne} would fuse three separate artists into a single
                         recommendation cluster. Likewise TajMo would fuse Taj Mahal and
                         Keb' Mo'.

  bill_components(raw)   "this bill CONTAINS that entity"
                         split on & / and / w/ / feat / with / colon; strip a trailing
                         parenthetical. Used for MEMBERSHIP — the goal badges ask "is a
                         hat-eligible artist on this bill?" (#150). Never feed these into
                         clustering.

  lookup_forms(raw)      surface_forms | bill_components. Fallbacks to try against a
                         third-party API that matches names EXACTLY (Last.fm), where the
                         exact string misses, a retry is free, and a wrong fold shows up
                         in the log rather than corrupting a join.

TWO NORMALIZERS, for the same reason: norm() is used WITH a surface_forms expansion
(recommend index), goal_norm() WITHOUT one (goal badges), so the article de-inversion has
to live in different places. See each docstring.

Separators are explicit — no fuzzy matching. The trailing-" Band" rule is the long-standing
house convention (recommend_aliases.tsv's header documents it by name).

JS TWINS (app.js/recommend.js can't import Python — keep them in step by hand):
  _goalNorm()     in app.js        <-> goal_norm()
  _goalBillKeys() in app.js        <-> goal_norm() + bill_components()
  recNorm()       in recommend.js  <-> norm()
"""

import re
import unicodedata

# Explicit separators only. Ordered so "and his"/"and her" win over bare "and".
_BILL_SEP = re.compile(
    r"\s+(?:&|and his|and her|and|w/|feat\.?|featuring|with)\s+|\s*:\s*", re.I)
_TRAILING_BAND = re.compile(r"^(.*\S)\s+band$", re.I)
_INVERTED_ARTICLE = re.compile(r"^(.*),\s*(the|a|an)$", re.I)
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def norm(s):
    """INDEX normalization: lowercase, de-accent, drop one leading article, strip punctuation.

    Deliberately does NOT de-invert "X, The" — surface_forms() emits the de-inverted
    spelling as a separate variant instead, and the whole variant set is indexed.
    JS TWIN: recNorm() in recommend.js, which carries the same contract in a comment.
    Changing this without changing recNorm silently breaks the recommend lookup.
    """
    s = strip_accents(s or "").lower()
    s = re.sub(r"^\s*(the|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def goal_norm(s):
    """GOAL-BADGE normalization: as norm(), but de-inverts "X, The" inline.

    The goal join normalizes eligibility keys DIRECTLY — there is no surface_forms()
    expansion step — and hat_eligibility.tsv stores "War and Treaty, The". Without the
    inline de-inversion that row never matches the show billed "The War and Treaty".
    JS TWIN: _goalNorm() in app.js.

    Yes, this is a second normalizer. The two are not redundant: one is used with a variant
    expansion and one without, and folding either into the other breaks its consumer.
    """
    s = str(s or "").strip()
    m = _INVERTED_ARTICLE.match(s)
    if m:
        s = "%s %s" % (m.group(2), m.group(1))
    return norm(s)


def surface_forms(raw):
    """All legitimate spellings of ONE entity, pre-normalization.

    Identity only — see the module docstring. Does not split bills.
    """
    raw = (raw or "").strip()
    if not raw:
        return set()
    forms = {raw}
    # de-invert "X, The" / "X, A" / "X, An" -> "The X" and bare "X"
    m = _INVERTED_ARTICLE.match(raw)
    if m:
        forms.add("%s %s" % (m.group(2), m.group(1)))
        forms.add(m.group(1))
    # drop a trailing " Band" (Ally Venable Band -> Ally Venable)
    for f in list(forms):
        m2 = _TRAILING_BAND.match(f)
        if m2:
            forms.add(m2.group(1))
    return forms


def variant_keys(raw):
    """Normalized surface_forms — the identity keys."""
    return {k for k in (norm(f) for f in surface_forms(raw)) if k}


def bill_components(raw):
    """The entities named inside a bill, pre-normalization, in BILL ORDER.

    "Victor Wooten & The Wooten Brothers" -> [Victor Wooten, The Wooten Brothers, ...]
    "Yola (DJ)"                           -> [Yola]
    A plain name yields nothing, so this is a no-op for the common case. The raw string
    itself is NOT included — callers try the exact name first.

    Returns a LIST, left-to-right: consumers report "matched via component X", and a set
    would make that read differently run to run.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    out, seen = [], set()

    def _add(candidate):
        for f in sorted(surface_forms(candidate), key=lambda x: (-len(x), x)):
            k = goal_norm(f)
            if f and k and f != raw and k not in seen:
                seen.add(k)
                out.append(f)

    for part in _BILL_SEP.split(raw):
        part = (part or "").strip()
        if not part:
            continue
        _add(part)
        stripped = _TRAILING_PAREN.sub("", part).strip()
        if stripped and stripped != part:
            _add(stripped)
    # a trailing parenthetical on the whole string, with no separator to split on
    bare = _TRAILING_PAREN.sub("", raw).strip()
    if bare and bare != raw:
        _add(bare)
    return out


def lookup_forms(raw):
    """Ordered fallbacks for a third-party lookup keyed on exact names.

    The exact string first, then spelling variants, then bill members — longest first so
    the most specific match is tried before a broader one.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    seen, out = set(), []
    for f in [raw] + sorted(surface_forms(raw), key=lambda x: (-len(x), x)) + bill_components(raw):
        k = goal_norm(f)
        if f and k and k not in seen:
            seen.add(k)
            out.append(f)
    return out
