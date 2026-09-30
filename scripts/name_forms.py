#!/usr/bin/env python3
"""
name_forms.py — the one place that knows when two artist strings mean the same thing.

Before this module the rule lived in three copies (build_recommend_index.surface_forms,
app.js _goalBillKeys, audit_goal_badges.bill_keys) and was missing from a fourth consumer
(spotify_cache), which is how bill-named cache entries ended up with a null Last.fm block
(see docs/ISSUE_LOG.md).

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
                         hat-eligible artist on this bill?". Never feed these into
                         clustering.

  lookup_forms(raw)      surface_forms | bill_components. Fallbacks to try against a
                         third-party API that matches names EXACTLY (Last.fm), where the
                         exact string misses, a retry is free, and a wrong fold shows up
                         in the log rather than corrupting a join.

  identity_keys(raw)     variant_keys plus the hand-maintained alias table. The one to
                         use for any join against the tracking files — see its docstring.

  ArtistResolver         WHICH IDENTITY a name belongs to, WHAT to call it, and WHICH
                         ACTS an appearance credits. The layer above the four functions
                         above; see the "Artist identity" section below.

TWO NORMALIZERS, for the same reason: norm() is used WITH a surface_forms expansion
(recommend index), goal_norm() WITHOUT one (goal badges), so the article de-inversion has
to live in different places. See each docstring.

Separators are explicit — no fuzzy matching. The trailing-" Band" rule is the long-standing
house convention (recommend_aliases.tsv's header documents it by name).

JS TWINS (app.js/recommend.js can't import Python — keep them in step by hand):
  _goalNorm()     in app.js        <-> goal_norm()
  _goalBillKeys() in app.js        <-> goal_norm() + bill_components()
  recNorm()       in recommend.js  <-> norm()

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import csv
import re
import unicodedata
from pathlib import Path

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


# ── Alias-table identity ─────────────────────────────────────────────────────
# The rules above are derivable from the string. recommend_aliases.tsv holds the
# pairs that are NOT — "Billy F Gibbons" / "Billy Gibbons", "Trombone Shorty" /
# "Trombone Shorty & Orleans Avenue". Any join that skips it reports long-tracked
# artists as untracked, which reads as a finding rather than a bug.

_ALIASES_PATH = Path(__file__).resolve().parents[1] / "data" / "recommend_aliases.tsv"
_alias_cache = None


def _alias_pairs(path=None):
    """[(alias_keys, canonical_keys)] from recommend_aliases.tsv.

    Resolved relative to this file, not the cwd, so a caller run from anywhere
    gets the table rather than silently getting none. An absent file is a valid
    state (a fork may have no aliases) and yields no pairs.
    """
    global _alias_cache
    if path is None:
        if _alias_cache is None:
            _alias_cache = _read_alias_pairs(_ALIASES_PATH)
        return _alias_cache
    return _read_alias_pairs(Path(path))


def _read_alias_pairs(path):
    if not path.exists():
        return []
    pairs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        alias, canon = parts[0].strip(), parts[1].strip()
        if alias.lower() == "alias" or not alias or not canon:
            continue
        pairs.append((variant_keys(alias), variant_keys(canon)))
    return pairs


def identity_keys(name, path=None):
    """Every normalized form one artist name can legitimately be spelled under.

    variant_keys() plus the alias table, expanded in BOTH directions so a match
    works whichever side of an alias row the caller happens to hold.

    Identity only — never splits a bill. See the module docstring.

    A caller resolving a lookup through this can match SEVERAL keys at once, and
    they may carry different values: "Lone Bellow, The" normalizes to both
    `lone bellow` and `lone bellow the`. Resolve such a collision deterministically
    (strongest tier, earliest date) rather than taking the first match off the set.

    >>> "billy gibbons" in identity_keys("Billy F Gibbons")
    True
    >>> "trombone shorty" in identity_keys("Trombone Shorty & Orleans Avenue")
    True
    >>> sorted(identity_keys("Robert Cray Band")) [:2]
    ['robert cray', 'robert cray band']
    """
    keys = variant_keys(name)
    if not keys:
        return keys
    for alias_keys, canon_keys in _alias_pairs(path):
        if keys & alias_keys:
            keys = keys | canon_keys
        elif keys & canon_keys:
            keys = keys | alias_keys
    return keys


# ── Artist identity ──────────────────────────────────────────────────────────
# identity_keys() answers "could these two strings be the same artist?". The
# resolver answers the questions a consumer actually has to settle:
#
#   canonical(name)      which identity a name belongs to, as the one name every
#                        consumer uses for it (None for an unknown name)
#   credits(date, bill)  which acts one appearance on the ledger credits, in
#                        which role, when data/bill_annotations.tsv says the
#                        ledger's headliner/support reading is not the whole story
#   is_non_artist(name)  a billing that is an event, not an act
#
# Inputs, all data rather than code:
#   data/recommend_aliases.tsv   hand-made spelling pairs (alias -> canonical)
#   data/artist_relations.tsv    same-as / member-of / not-an-artist
#   data/bill_annotations.tsv    per-show exceptions: joint sets, alternating
#                                co-bills, separate sets, guests
#   the ledger                   history/*.tsv, attended rows of
#                                live_shows_current.tsv, seen_with.tsv
#
# GROUPING. Every surface form of an attested name (de-inverted "X, The", a
# dropped trailing " Band") shares one group, as identity_keys() already
# implies. Alias rows and same-as / member-of rows join groups explicitly.
#
# DERIVED DEFAULT. A name with no appearance of its own, which LEADS exactly
# ONE act that has been seen (the act's first bill component, or a
# leading-word prefix of its name), joins that act's group: "Nick Lowe" ->
# "Nick Lowe & Los Straitjackets", "James Hunter" -> "The James Hunter Six".
# A trailing component never qualifies: "The Wooten Brothers" is an act of
# its own, not a member folded into "Victor Wooten & The Wooten Brothers". An
# appearance of its own (a ledger row, a seen_with row, or an annotation row
# naming it) splits it back out on the next build. Two or more candidate acts
# is ambiguous and stays split.
#
# CANONICAL NAME of a group, first rule that applies:
#   1. an explicit target: the canonical side of an alias row, or the Target of
#      a same-as / member-of row
#   2. an eponymous act: the group holds "X Band" (or "The X Band") and the
#      plain "X" is attested on its own, so the person's name wins
#      ("Ally Venable Band" -> "Ally Venable")
#   3. the act a derived default folded the group into
#   4. otherwise the attested name with the most appearances, then the
#      shortest, then alphabetical, so the choice never depends on set order
#
# Two acts one person fronts stay two groups: nothing here reads
# related_acts.tsv, so Oliver Wood and The Wood Brothers never fold.

RELATIONS_PATH = "data/artist_relations.tsv"
ANNOTATIONS_PATH = "data/bill_annotations.tsv"

RELATION_KINDS = ("same-as", "member-of", "not-an-artist")
ANNOTATION_ROLES = ("principal", "guest")
ANNOTATION_SHAPES = ("joint-set", "alternating", "separate-sets", "-")
ANNOTATION_STATUSES = ("confirmed", "assumed")

# multi-support separators in the ledger's support column (not commas)
SUPPORT_SPLIT = re.compile(r"\s*[;/]\s*|\s+w/\s+")


def identity_key(raw):
    """The one normalized key a group is indexed by (goal_norm: de-inverts inline)."""
    return goal_norm(raw)


def _surface_keys(raw):
    return {k for k in (goal_norm(f) for f in surface_forms(raw)) if k}


def _read_rows(path):
    """TSV rows as dicts; blank lines and '#' comment lines skipped; values stripped."""
    path = Path(path)
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").split("\n")
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)]


def _cell(v):
    v = (v or "").strip()
    return "" if v == "-" else v


def split_support(cell):
    cell = _cell(cell)
    return [p.strip() for p in SUPPORT_SPLIT.split(cell) if p.strip() and p.strip() != "-"] if cell else []


def read_relations(root="."):
    return [{"name": r.get("Name", ""), "kind": r.get("Kind", ""),
             "target": _cell(r.get("Target")), "notes": _cell(r.get("Notes"))}
            for r in _read_rows(Path(root) / RELATIONS_PATH) if r.get("Name")]


def read_annotations(root="."):
    return [{"date": r.get("Show Date", ""), "billing": r.get("Billing", ""),
             "act": r.get("Act", ""), "role": r.get("Role", ""),
             "shape": r.get("Shape", "") or "-", "status": r.get("Status", ""),
             "review_after": _cell(r.get("Review After")), "notes": _cell(r.get("Notes"))}
            for r in _read_rows(Path(root) / ANNOTATIONS_PATH) if r.get("Act")]


def read_aliases(root="."):
    out = []
    path = Path(root) / "data" / "recommend_aliases.tsv"
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        alias, canon = parts[0].strip(), parts[1].strip()
        if alias.lower() == "alias" or not alias or not canon:
            continue
        out.append((alias, canon))
    return out


def ledger_bills(root="."):
    """[(date, headliner, [support...])] for every show that happened.

    history/*.tsv in full, plus live_shows_current.tsv rows whose Status is
    attended. Values are stripped, so a padded cell cannot break a join.
    """
    root = Path(root)
    out = []
    hist = root / "data" / "history"
    for f in sorted(hist.glob("*.tsv")) if hist.is_dir() else []:
        for r in _read_rows(f):
            if r.get("Show Date") and _cell(r.get("Artist")):
                out.append((r["Show Date"], r["Artist"], split_support(r.get("Supporting Acts"))))
    for r in _read_rows(root / "data" / "live_shows_current.tsv"):
        if (r.get("Status") or "").lower() == "attended" and _cell(r.get("Artist")):
            out.append((r["Show Date"], r["Artist"], split_support(r.get("Supporting Artist"))))
    return out


def upcoming_bills(root="."):
    """[(date, headliner, [support...])] for current rows not yet attended."""
    out = []
    for r in _read_rows(Path(root) / "data" / "live_shows_current.tsv"):
        if (r.get("Status") or "").lower() != "attended" and _cell(r.get("Artist")):
            out.append((r["Show Date"], r["Artist"], split_support(r.get("Supporting Artist"))))
    return out


def _attested_names(root):
    """Every artist name any tracking file uses, raw. Attestation is what lets
    rule 2 prefer "Jesse Williams" over "The Jesse Williams Band": the plain
    name has to be used somewhere, even if only by a hat signature."""
    root = Path(root)
    names = []
    # Curated files first: the first spelling seen for a key is the one kept, so
    # artists.tsv casing ("Doug MacLeod") beats a ledger or follows variant.
    for r in _read_rows(root / "data" / "artists.tsv"):
        if _cell(r.get("Artist")):
            names.append(r["Artist"])
    for d, head, sup in ledger_bills(root) + upcoming_bills(root):
        names.append(head)
        names.extend(sup)
    sources = [
        ("data/live_shows_potential.tsv", ("Artist", "Supporting Artist")),
        ("data/fast_track.tsv", ("Artist",)),
        ("data/seen_with.tsv", ("Seen With",)),
        ("data/show_goals/hat_signatures.tsv", ("signer",)),
        ("data/show_goals/book_signatures.tsv", ("signer",)),
        ("data/show_goals/hat_eligibility.tsv", ("Artist",)),
        ("data/show_goals/autograph_books_eligibility.tsv", ("Artist",)),
        ("tools/research/follows/follows_master.tsv", ("Artist",)),
    ]
    for rel, cols in sources:
        for r in _read_rows(root / rel):
            for c in cols:
                v = _cell(r.get(c))
                if not v:
                    continue
                names.extend(split_support(v) if c == "Supporting Artist" else [v])
    return [n for n in names if n]


class ArtistResolver:
    """Identity resolution over the tracking data. Build once per run:

        r = ArtistResolver.from_repo(".")
        r.canonical("Ally Venable Band")         -> "Ally Venable"
        r.credits("2023-12-05", "The Allman Betts Band")
            -> [{"act": "Tal Wilkenfeld", "role": "guest", ...}, ...]

    Construction takes plain lists, so a test can build a synthetic world
    without touching the repo (see scripts/check_identity.py).
    """

    def __init__(self, names, appearances=(), aliases=(), relations=(), annotations=()):
        self._parent = {}
        self._explicit = {}          # target key -> (name, why), rule 1
        self._folded_into = {}       # key -> act name, from the derived default
        self.relations = list(relations)
        self.annotations = list(annotations)
        self._non_artist = {identity_key(r["name"]) for r in self.relations
                            if r["kind"] == "not-an-artist"}

        # own appearances, per key: ledger rows, seen_with rows, annotation acts
        self._own = {}
        for name in appearances:
            k = identity_key(name)
            if k:
                self._own[k] = self._own.get(k, 0) + 1
        for a in self.annotations:
            k = identity_key(a["act"])
            if k:
                self._own[k] = self._own.get(k, 0) + 1

        # attested names: every raw spelling, keyed; first spelling of a key wins
        self._spelling = {}
        all_names = list(names) + [a for a, _ in aliases] + [c for _, c in aliases]
        for r in self.relations:
            all_names.append(r["name"])
            if r["target"]:
                all_names.append(r["target"])
        all_names += [a["act"] for a in self.annotations]
        for n in all_names:
            n = (n or "").strip()
            k = identity_key(n)
            if k and k not in self._spelling:
                self._spelling[k] = n
            if k:
                self._find(k)

        # grouping: surface forms of every attested name
        for k, n in list(self._spelling.items()):
            for sk in _surface_keys(n):
                self._union(k, sk)

        # explicit joins (rule 1 names the survivor)
        explicit = [(a, c, "alias") for a, c in aliases]
        explicit += [(r["name"], r["target"], r["kind"]) for r in self.relations
                     if r["kind"] in ("same-as", "member-of") and r["target"]]
        for a, c, why in explicit:
            ka, kc = identity_key(a), identity_key(c)
            if ka and kc:
                self._union(ka, kc)
        # keyed by the target's own key, never by a union-find root: roots move
        # when the derived default merges groups later
        for a, c, why in explicit:
            kc = identity_key(c)
            if kc:
                self._explicit.setdefault(kc, (c.strip(), why))

        self._apply_derived_default()

    # -- union-find --------------------------------------------------------
    def _find(self, k):
        self._parent.setdefault(k, k)
        while self._parent[k] != k:
            self._parent[k] = self._parent[self._parent[k]]
            k = self._parent[k]
        return k

    def _union(self, a, b):
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            self._parent[hi] = lo

    def _groups(self):
        g = {}
        for k in self._parent:
            g.setdefault(self._find(k), set()).add(k)
        return g

    def _group_own(self, members):
        return sum(self._own.get(k, 0) for k in members)

    # -- derived default ---------------------------------------------------
    def _apply_derived_default(self):
        groups = self._groups()
        seen_roots = {r for r, m in groups.items() if self._group_own(m) > 0}
        # candidate acts: every attested spelling in a seen group
        acts = []
        for r in sorted(seen_roots):
            for k in sorted(groups[r]):
                if k in self._spelling:
                    acts.append((r, k, self._spelling[k]))
        self.derived = []
        for root, members in sorted(groups.items()):
            if self._group_own(members) > 0 or any(k in self._explicit for k in members):
                continue
            if any(k in self._non_artist for k in members):
                continue
            hits = set()
            for k in members:
                for r, ak, aname in acts:
                    if r == root:
                        continue
                    lead = goal_norm(_BILL_SEP.split(aname)[0])
                    if k == lead or ak.startswith(k + " "):
                        hits.add(r)
            if len(hits) == 1:
                target = hits.pop()
                self.derived.append((self._spelling.get(root, root), target))
                for k in members:
                    self._folded_into[k] = target
                self._union(root, target)

    # -- queries -----------------------------------------------------------
    def known(self, name):
        k = identity_key(name)
        return bool(k) and k in self._parent

    def group(self, name):
        """Every key in name's group (empty set for an unknown name)."""
        k = identity_key(name)
        if not k or k not in self._parent:
            return set()
        r = self._find(k)
        return {m for m in self._parent if self._find(m) == r}

    def canonical(self, name):
        """The canonical name for name's group, or None if the name is unknown."""
        k = identity_key(name)
        if not k or k not in self._parent:
            return None
        return self._canonical_for_root(self._find(k))

    def _canonical_for_root(self, root):
        cache = self.__dict__.setdefault("_canon_cache", {})
        if root in cache:
            return cache[root]
        members = {m for m in self._parent if self._find(m) == root}
        name = None
        # rule 1: an explicit target in this group
        for m in sorted(members):
            ex = self._explicit.get(m)
            if ex:
                name = ex[0]
                break
        # rule 2: an eponymous act whose plain name is attested on its own
        if name is None:
            plains = []
            for m in members:
                sp = self._spelling.get(m)
                if not sp:
                    continue
                mm = _TRAILING_BAND.match(re.sub(r"^\s*the\s+", "", sp, flags=re.I))
                if mm:
                    pk = goal_norm(mm.group(1))
                    if pk in members and pk in self._spelling \
                            and not _TRAILING_BAND.match(self._spelling[pk]):
                        plains.append(self._spelling[pk])
            if plains:
                name = sorted(plains)[0]
        # rule 3: the act a derived default folded this group into
        if name is None:
            folded = [m for m in members if m in self._folded_into]
            if folded:
                act_members = [m for m in members if m not in self._folded_into
                               and m in self._spelling]
                if act_members:
                    name = self._pick(act_members)
        # rule 4: most appearances, then shortest, then alphabetical
        if name is None:
            spelled = [m for m in members if m in self._spelling]
            name = self._pick(spelled) if spelled else root
        # natural article order for the name every consumer shows ("Wood Brothers,
        # The" is a filing form in some tracking files, never a display form)
        m = _INVERTED_ARTICLE.match(name)
        if m:
            name = "%s %s" % (m.group(2).capitalize(), m.group(1))
        cache[root] = name
        return name

    def _pick(self, keys):
        best = sorted(keys, key=lambda m: (-self._own.get(m, 0),
                                           len(self._spelling[m]), self._spelling[m]))
        return self._spelling[best[0]]

    def spellings(self):
        """Every attested raw spelling, one per key, sorted."""
        return sorted(self._spelling.values())

    def is_non_artist(self, name):
        return bool(self.group(name) & self._non_artist)

    def credits(self, date, billing):
        """Annotation rows for one bill entry on one date (billing matched by key)."""
        bk = identity_key(billing)
        return [a for a in self.annotations
                if a["date"] == date and identity_key(a["billing"]) == bk]

    def explain(self, name):
        """A one-line account of how name resolves, for fixtures and debugging."""
        c = self.canonical(name)
        if c is None:
            return "%s: unknown" % name
        k = identity_key(name)
        explicit = [self._explicit[m] for m in sorted(self.group(name)) if m in self._explicit]
        if explicit:
            why = explicit[0][1]
        elif k in self._folded_into:
            why = "derived default"
        else:
            why = "surface form" if identity_key(c) != k else "self"
        return "%s -> %s (%s)" % (name, c, why)

    # -- construction from the repo ----------------------------------------
    @classmethod
    def from_repo(cls, root="."):
        root = Path(root)
        appearances = []
        for d, head, sup in ledger_bills(root):
            appearances.append(head)
            appearances.extend(sup)
        for r in _read_rows(root / "data" / "seen_with.tsv"):
            if _cell(r.get("Seen With")):
                appearances.append(r["Seen With"])
        return cls(names=_attested_names(root), appearances=appearances,
                   aliases=read_aliases(root), relations=read_relations(root),
                   annotations=read_annotations(root))
