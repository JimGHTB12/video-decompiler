#!/usr/bin/env python3
"""Every Python file the skill ships parses on Python 3.10, the minimum vd doctor accepts.

  python tests/test_min_python.py

pack.py once reused double quotes inside a double-quoted f-string's replacement field (`{"s" if n != 1 else ""}`), which
only Python 3.12 reads (PEP 701): on 3.10 and 3.11 the first `vd pack` stopped with a SyntaxError, and doctor said ready.
Three checks, so the rule holds on any machine the suite runs on:
  1. ast.parse(feature_version=(3, 10)): the grammar newer than 3.10 that the parser knows to refuse (except*, type X,
     def f[T]).
  2. on 3.12 and later, the tokens of every f-string: a quote of the f-string's own kind, a backslash or a comment inside a
     replacement field (PEP 701's three additions; feature_version does not refuse them).
  3. when a 3.10 or 3.11 is on this machine (VD_TEST_OLD_PYTHON, else python3.10 / python3.11 on PATH), it compiles them all.
"""
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(p for d in (ROOT / "skills", ROOT / "tests") for p in d.rglob("*.py") if "__pycache__" not in p.parts)


def quote_of(tok):
    """The quote a string token opens with: ' " ''' or \"\"\" (its prefix letters dropped)."""
    s = tok.lstrip("rRbBuUfF")
    return s[:3] if s[:3] in ('"""', "'''") else s[:1]


def pep701(src, name="<src>"):
    """[(line, what)] for each f-string construct only 3.12 reads. Needs a 3.12+ tokenizer (FSTRING_START tokens)."""
    found, stack = [], []        # stack: [quote, brace depth] for each f-string open around here
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        inside = stack and stack[-1][1] > 0
        if inside and t.type in (tokenize.STRING, tokenize.FSTRING_START):
            outer, q = stack[-1][0], quote_of(t.string)
            if (outer in q) if len(outer) == 3 else (q[:1] == outer):
                found.append((t.start[0], f"the quote {outer} reused inside an f-string's replacement field"))
            if t.type == tokenize.STRING and "\\" in t.string:
                found.append((t.start[0], "a backslash inside an f-string's replacement field"))
        if inside and t.type == tokenize.COMMENT:
            found.append((t.start[0], "a comment inside an f-string's replacement field"))
        if t.type == tokenize.FSTRING_START:
            stack.append([quote_of(t.string), 0])
        elif t.type == tokenize.FSTRING_END and stack:
            stack.pop()
        elif stack and t.type == tokenize.OP and t.string in "{}":
            stack[-1][1] += 1 if t.string == "{" else -1
    return found


def old_python():
    given = os.environ.get("VD_TEST_OLD_PYTHON")
    if given:
        return given
    for name in ("python3.10", "python3.11"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def main():
    assert FILES, "found the skill's Python files"
    bad = []
    for f in FILES:
        src = f.read_text(encoding="utf-8")
        try:
            ast.parse(src, str(f), feature_version=(3, 10))
        except SyntaxError as e:
            bad.append(f"{f.relative_to(ROOT)}:{e.lineno}: {e.msg}")
        if hasattr(tokenize, "FSTRING_START"):
            bad += [f"{f.relative_to(ROOT)}:{line}: {what}" for line, what in pep701(src, str(f))]
    # the check itself: each construct it is there for is caught, and what 3.10 reads is not
    if hasattr(tokenize, "FSTRING_START"):
        assert pep701('x = f"{"s" if n else ""}"\n'), "a reused double quote is caught"
        assert pep701("x = f'{'s'}'\n"), "a reused single quote is caught"
        assert pep701('x = f"{"\\n".join(a)}"\n'), "a backslash in a replacement field is caught"
        assert pep701('x = f"""{"a"}"""\n') == [], "a single quote inside a triple-quoted f-string is 3.10 syntax"
        assert pep701("x = f\"{'s' if n else ''}\"\n") == [], "the other quote is 3.10 syntax"
        assert pep701('x = f"{a:{w}}" + f"{ {1: 2}[1] }"\n') == [], "nested format fields and a dict are 3.10 syntax"
    assert not bad, "syntax newer than Python 3.10:\n  " + "\n  ".join(bad)
    checked = "feature_version 3.10" + (" and the f-string tokens" if hasattr(tokenize, "FSTRING_START") else "")
    old = old_python()
    if old:
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "files.txt"
            listing.write_text("\n".join(map(str, FILES)), encoding="utf-8")
            p = subprocess.run([old, "-c", "import ast,sys\nbad=[]\nfor f in open(sys.argv[1],encoding='utf-8').read().splitlines():\n"
                                "    try: ast.parse(open(f,encoding='utf-8').read(), f)\n    except SyntaxError as e: bad.append(f'{f}:{e.lineno}: {e.msg}')\n"
                                "print(sys.version.split()[0]); print('\\n'.join(bad)); sys.exit(1 if bad else 0)", str(listing)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert p.returncode == 0, f"{old} cannot parse:\n{p.stdout}{p.stderr}"
        checked += f", and parsed by Python {p.stdout.split()[0]} ({old})"
    print(f"min python checks passed: {len(FILES)} files, {checked}")


if __name__ == "__main__":
    main()
