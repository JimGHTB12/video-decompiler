#!/usr/bin/env python3
"""tests/test_upstream.py fails when git fails, tells git grep's "no match" from an error, and names the commit it read.
No git is run here: git's answers are planted, as the ones a checkout git refuses gives ("dubious ownership").

  python tests/test_upstream_errors.py

With git refusing the checkout, every search came back empty and the check printed "upstream checks passed" having read
nothing.
"""
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_upstream as up  # noqa: E402


def answers(table):
    """subprocess.run as git would answer: table maps git's subcommand to (exit status, stdout, stderr)."""
    def run(cmd, **k):
        code, out, err = table[cmd[3]]
        return subprocess.CompletedProcess(cmd, code, out, err)
    return run


def check(table):
    """(exit, what it printed) of the check, with git answering from `table`, in a folder that is a checkout."""
    buf = io.StringIO()
    with patch.object(up.subprocess, "run", answers(table)), patch.object(up, "ROOT", Path(__file__).resolve().parent.parent), \
            patch.object(Path, "exists", lambda self: True if self.name == ".git" else Path.is_file(self) or Path.is_dir(self)), redirect_stdout(buf):
        try:
            with patch.object(sys, "argv", ["test_upstream.py", "HEAD"]):
                up.main()
            return 0, buf.getvalue()
        except SystemExit as e:
            return (e.code if isinstance(e.code, int) else 1), buf.getvalue() + str(e.code)


def main():
    refused = (128, "", "fatal: detected dubious ownership in repository at '/x'")
    sha = (0, "f59c174ba4fbf93e7d96610bf857e9426f23beef\n", "")
    files = (0, "README.md\nskills/video-decompiler/SKILL.md\n", "")
    code, said = check({"rev-parse": refused, "grep": refused, "ls-tree": refused})
    assert code != 0 and "dubious ownership" in said and "passed" not in said, f"git refusing the checkout fails the check: {code} {said}"
    code, said = check({"rev-parse": sha, "grep": refused, "ls-tree": files})
    assert code != 0 and "git grep" in said and "exited 128" in said, f"a search git refuses fails the check: {code} {said}"
    code, said = check({"rev-parse": sha, "grep": (1, "", ""), "ls-tree": files})
    assert code == 0 and "passed at HEAD (f59c174ba4fbf93e7d96610bf857e9426f23beef): 2 committed files" in said, f"grep's 1 is no match, and the commit is named: {said}"
    code, said = check({"rev-parse": sha, "grep": (1, "", ""), "ls-tree": (0, "", "")})
    assert code != 0 and "lists no files" in said, f"a commit with no files is no check: {said}"
    planted = "HEAD:README.md:3:see interface" "lineage.com/p/x\n"   # in two pieces, so this file does not itself hold what the check forbids
    code, said = check({"rev-parse": sha, "grep": (0, planted, ""), "ls-tree": files})
    assert code == 1 and "a link to one of its pages" in said, said
    print("upstream error checks passed")


if __name__ == "__main__":
    main()
