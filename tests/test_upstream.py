#!/usr/bin/env python3
"""What leaves this machine: principles in our own words, and nothing else from the sources we learned them from.

  python tests/test_upstream.py [REF]

Checks what's committed at REF, default HEAD, and says which commit that was. Interface Lineage's writing is all rights
reserved and its access token is personal. The skill may carry ideas learned there, credited once, and no page of it. A
failure means the text should change, not this list. Git failing is a failure too: with git refusing the checkout ("dubious
ownership") every search came back empty and this said "passed" having read nothing. A copy that is no git checkout at all
has nothing committed to check, and says skipped.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = "tests/test_upstream.py"
CREDIT_FILE = "skills/video-decompiler/EYES.md"   # where a credit would go; LENS.md, which held it, was cut
STAYS_LOCAL = ("skills/video-decompiler/LENS.local.md", "skills/video-decompiler/taste.local.json")
FORBIDDEN = {
    "a link to one of its pages": r"interfacelineage\.com/[a-z0-9]",
    "its MCP tools": r"mcp__interface-lineage|\b(list_catalog|get_lineage|show_lineage|find_related|get_stills|show_demo)\b",
    "an access token": r"Bearer\s+[A-Za-z0-9_-]{20,}|\b[a-f0-9]{64}\b",
}


def git(*args, ok=(0,)):
    """git's output; any exit status outside `ok` stops the check with git's own words (git grep exits 1 for no match)."""
    try:
        p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise SystemExit(f"upstream check could not run git ({e}): nothing was checked")
    if p.returncode not in ok:
        raise SystemExit(f"upstream check failed: `git {' '.join(args[:2])}` exited {p.returncode}: {(p.stderr or p.stdout).strip()[:400]} (nothing was checked)")
    return p.stdout


def found(pattern, ref):
    out = git("grep", "-I", "-n", "-i", "-E", pattern, ref, "--", ".", f":!{HERE}", ok=(0, 1))
    return [line.split(":", 1)[1] for line in out.splitlines()]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ref = argv[0] if argv else "HEAD"
    if not (ROOT / ".git").exists():
        print(f"skipped: {ROOT} is not a git checkout, so there is nothing committed to check")
        return
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    faults = [f"{what}: {hit[:150]}" for what, pattern in FORBIDDEN.items() for hit in found(pattern, ref)]
    named = found(r"interface ?lineage", ref)
    credits = [h for h in named if h.startswith(CREDIT_FILE + ":")]
    faults += [f"the source is named outside its one credit: {h[:150]}" for h in named if h not in credits[:1]]
    if len(credits) > 1:
        faults.append(f"{CREDIT_FILE} should credit the source at most once, and has {len(credits)}")
    tracked = set(git("ls-tree", "-r", "--name-only", ref).splitlines())
    if not tracked:
        raise SystemExit(f"upstream check failed: git lists no files at {ref} ({commit}), so nothing was checked")
    faults += [f"this file stays on this machine and is committed: {f}" for f in STAYS_LOCAL if f in tracked]
    if faults:
        print(f"Not going upstream ({ref}, {commit}). Only principles in our own words may leave this machine:")
        print("\n".join(f"  - {f}" for f in faults))
        sys.exit(1)
    print(f"upstream checks passed at {ref} ({commit}): {len(tracked)} committed files searched")


if __name__ == "__main__":
    main()
