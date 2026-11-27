#!/usr/bin/env python3
"""check_evergreen.py — warn-only drift scan for the evergreen-comment convention.

Forker-facing code comments must stand on their own: no issue-number references
(#NNN) and no incident dates — that history lives in docs/ISSUE_LOG.md. The
write-time rule is in the data-write playbook; this is the backstop that catches
drift from any author or forgetful session.

Scans COMMENT/DOCSTRING CONTENT per filetype (Python via tokenize + ast, JS/CSS
via a small string-aware scanner, YAML header comments, HTML comments plus
delegated inline <style>/<script> blocks). Code tokens are never scanned, so hex
colors, DOM ids, and route hashes cannot false-positive. tools/ playbooks are
exempt (owner-facing working shorthand), except the artist-graph research page
which is forker-visible.

PYTHON STRING LITERALS in scripts/ are also scanned, for issue references only.
Program output is a forker-facing surface — arguably the most forker-facing one
— and a comment-only scan cannot see it: a stale issue pointer printed in a
script's next-steps block survived exactly that blind spot. Literals are checked
for #NNN and NOT for leading dates, because a date in a string is usually data
(a default, a cutoff, a format example) rather than a changelog artifact.

OWNER NAME. A fork has a different owner, so a script that explains itself in
terms of one named person is as stale for a forker as an issue number. Every
.py file in the repo is scanned - comments, docstrings and string literals - for
the name in config.yaml's site.owner_name, as a whole word, possessive included.
The name is read from the config so it never has to appear in this script, and
with none configured the rule is off. Prefer an impersonal rewrite; say "the
owner" where a person has to be mentioned. Where the name is the data being
matched, end that line with the comment  # evergreen: owner-name-is-data

Modes:
  (default)  warn only, exit 0 — annotations plus a job-summary section.
  --strict   exit 1 if anything is found. Scoped form, --strict FILE..., counts
             only findings in those files: a new reference in a file the push
             touched is unambiguous, while demanding the whole repo be evergreen
             before anything can promote turns unrelated work into a hunt.
  --self-test  run the owner-name rule against built-in samples and exit.
"""

import argparse
import ast
import glob
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hygiene_report import Report, owner_names, scope_from_args  # noqa: E402

REF = re.compile(r"#\d{2,3}\b")
# A date at the START of a comment is the changelog signature ("2026-06-27:
# fixed ..."). Dates mid-sentence are usually legitimate format examples in a
# date-heavy pipeline, so only the leading position is flagged.
DATE = re.compile(r"^[\s#/*!<>—-]*20\d\d-\d\d(-\d\d)?\b")

JS_FILES = ["app.js", "recommend.js", "artist-modal.js"]
CSS_FILES = ["styles.css"]
HTML_FILES = ["index.html", "tools/research/graph/artist-graph.html"]
YML_GLOB = ".github/workflows/*.yml"
PY_GLOB = "scripts/*.py"
YAML_FILES = ["config.yaml"]

OWNER_ALLOW = "evergreen: owner-name-is-data"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

report = Report("check_evergreen")


def owner_pattern(names):
    """Whole-word match for any of `names`, possessive included; None when empty."""
    names = [n for n in names if n]
    if not names:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in names) + r")(?:'s)?(?![\w])")


def owner_findings(src, pattern):
    """(line, where, text) for each line of Python source that names the owner.

    Comments, docstrings and string literals are all read. A line carrying the
    OWNER_ALLOW marker is skipped, as is a string literal that starts on one.
    """
    if pattern is None:
        return []
    lines = src.split("\n")
    allowed = {i + 1 for i, ln in enumerate(lines) if OWNER_ALLOW in ln}
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT and tok.start[0] not in allowed and pattern.search(tok.string):
            out.append((tok.start[0], "comment", tok.string))
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
               isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        where = "docstring" if id(node) in docstrings else "string literal"
        start = node.lineno or 0
        if start in allowed:
            continue
        for k, part in enumerate(node.value.split("\n")):
            if start + k not in allowed and pattern.search(part):
                out.append((start + k, where, part))
    return sorted(set(out))


def python_files():
    """Every tracked .py file; a plain walk when git is not available."""
    try:
        got = subprocess.run(["git", "ls-files", "*.py"], capture_output=True, text=True, check=True)
        files = [f for f in got.stdout.splitlines() if f]
        if files:
            return sorted(files)
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(str(p) for p in Path(".").rglob("*.py")
                  if not SKIP_DIRS & set(p.parts))


def scan_owner(pattern):
    for f in python_files():
        try:
            src = Path(f).read_text(encoding="utf-8")
            found = owner_findings(src, pattern)
        except (SyntaxError, UnicodeDecodeError, tokenize.TokenError):
            continue
        for line, where, text in found:
            warn(f, line, "owner named", text, where=where)


def self_test():
    """The owner-name rule against samples, with an invented name."""
    pat = owner_pattern(["Robin"])
    cases = [
        ("# Robin picks the seat\n", 1, "comment"),
        ("# Robin's pins win\n", 1, "possessive"),
        ('def f():\n    """What Robin owns."""\n', 1, "docstring"),
        ('x = "sold by Robin"\n', 1, "string literal"),
        ('x = f"per Robin: {1}"\n', 1, "f-string"),
        ("# Robinson Crusoe\n", 0, "longer word"),
        ("# robin the bird\n", 0, "lower case"),
        ('x = "per Robin"  # ' + OWNER_ALLOW + "\n", 0, "allow marker on a string"),
        ("# matches Robin in data  # " + OWNER_ALLOW + "\n", 0, "allow marker on a comment"),
        ("robin = 1\n", 0, "identifier"),
    ]
    bad = 0
    for src, want, label in cases:
        got = len(owner_findings(src, pat))
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got} finding(s), expected {want}")
    off = owner_findings("# Robin\n", owner_pattern([]))
    print(f"  {'ok  ' if not off else 'FAIL'} no name configured: rule off")
    bad += bool(off)
    print("self-test: " + ("all passed" if not bad else f"{bad} FAILED"))
    return 1 if bad else 0


def warn(path, line, kind, text, where="comment"):
    report.warn(f"{kind} in {where}: {text.strip()[:100]}", path=path, line=line)


def check_comment(path, line, text):
    for m in REF.finditer(text):
        warn(path, line, f"issue reference {m.group(0)}", text)
    m = DATE.match(text)
    if m:
        warn(path, line, "leading date (changelog artifact)", text)


def scan_js_css(path, src, base_line=1):
    """String-aware scan for // and /* */ comments."""
    i, n, line = 0, len(src), base_line
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in "'\"`":
            q = c
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "\n":
                    line += 1
                if src[i] == q:
                    i += 1
                    break
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            check_comment(path, line, src[i:j])
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            block = src[i:j]
            for k, part in enumerate(block.split("\n")):
                check_comment(path, line + k, part)
            line += block.count("\n")
            i = j
        else:
            i += 1


def scan_python(path):
    src = Path(path).read_text(encoding="utf-8")
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            check_comment(path, tok.start[0], tok.string)
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
               isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
                for k, part in enumerate(body[0].value.value.split("\n")):
                    check_comment(path, body[0].lineno + k, part)
    check_string_literals(path, tree, docstrings)


def check_string_literals(path, tree, docstrings):
    """Issue references in non-docstring string literals (program output).

    Refs only, never dates: a literal date is normally data, not a changelog
    line. Hex colors and route hashes are unaffected because the pattern
    requires digits immediately after the '#'.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        for k, part in enumerate(node.value.split("\n")):
            for m in REF.finditer(part):
                warn(path, (node.lineno or 0) + k,
                     f"issue reference {m.group(0)}", part, where="string literal")


def scan_yaml(path):
    for i, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        # crude quote-strip so a '#' inside a quoted value isn't a comment
        stripped = re.sub(r'"[^"]*"', '""', raw)
        stripped = re.sub(r"'[^']*'", "''", stripped)
        if "#" in stripped:
            check_comment(path, i, stripped[stripped.index("#"):])


def scan_html(path):
    src = Path(path).read_text(encoding="utf-8")
    for m in re.finditer(r"<!--.*?-->", src, re.S):
        line = src[:m.start()].count("\n") + 1
        for k, part in enumerate(m.group(0).split("\n")):
            check_comment(path, line + k, part)
    for tag in ("style", "script"):
        for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", src, re.S):
            line = src[:m.start(1)].count("\n") + 1
            scan_js_css(path, m.group(1), base_line=line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", nargs="*", metavar="FILE", default=None,
                    help="exit 1 on findings; with FILEs, only those files block")
    ap.add_argument("--self-test", action="store_true",
                    help="run the owner-name rule against built-in samples")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    for f in JS_FILES + CSS_FILES:
        if Path(f).exists():
            scan_js_css(f, Path(f).read_text(encoding="utf-8"))
    for f in HTML_FILES:
        if Path(f).exists():
            scan_html(f)
    for f in YAML_FILES:
        if Path(f).exists():
            scan_yaml(f)
    for f in sorted(glob.glob(YML_GLOB)):
        scan_yaml(f)
    for f in sorted(glob.glob(PY_GLOB)):
        scan_python(f)
    pattern = owner_pattern(owner_names())
    if pattern is None:
        print("check_evergreen: owner-name rule is off (no site.owner_name in config.yaml)")
    else:
        scan_owner(pattern)
    return report.finish(strict=args.strict is not None,
                         scope=scope_from_args(args.strict))


if __name__ == "__main__":
    sys.exit(main())
