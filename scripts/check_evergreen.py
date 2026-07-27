#!/usr/bin/env python3
"""check_evergreen.py — warn-only drift scan for the evergreen-comment convention.

Forker-facing code comments must stand on their own: no issue-number references
(#NNN) and no incident dates — that history lives in docs/ISSUE_LOG.md. The
write-time rule is in the data-write playbook; this is the backstop that catches
drift from any author or forgetful session.

Scans COMMENT/DOCSTRING CONTENT ONLY, per filetype (Python via tokenize + ast,
JS/CSS via a small string-aware scanner, YAML header comments, HTML comments plus
delegated inline <style>/<script> blocks). Code tokens and string literals are
never scanned, so hex colors, DOM ids, and route hashes cannot false-positive.
tools/ playbooks are exempt (owner-facing working shorthand), except the
artist-graph research page which is forker-visible.

Always exits 0 — warns, never blocks.
"""

import ast
import glob
import io
import re
import sys
import tokenize
from pathlib import Path

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

warned = 0


def warn(path, line, kind, text):
    global warned
    warned += 1
    print(f"::warning file={path},line={line}::{kind} in comment: {text.strip()[:100]}")


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
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
               isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                for k, part in enumerate(body[0].value.value.split("\n")):
                    check_comment(path, body[0].lineno + k, part)


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


def main() -> int:
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
    print(f"check_evergreen: {warned} warning(s)." if warned
          else "check_evergreen: clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
