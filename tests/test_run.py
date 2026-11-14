#!/usr/bin/env python3
"""tests/run.py prints each test's line as that test finishes, even when its output goes to a pipe.

  python tests/test_run.py

An agent runs the suite through a pipe. Python holds a pipe's output until it has a block of it, so a run of about ten
minutes printed nothing until the end, and looked hung.

This runs a copy of run.py over two stand-in tests. The second waits for a file that this test makes only once it has read
the first test's line, so the check doesn't depend on how fast the machine is: if run.py held its output, the first line
would never come while the second test waits, and the second would give up and fail.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix="O'Connor ") as tmp:  # the user's temp folder can hold a quote
        d = Path(tmp)
        shutil.copy(HERE / "run.py", d / "run.py")
        flag = d / "first line read"
        (d / "test_a.py").write_text("print('a done')\n", encoding="utf-8")
        (d / "test_b.py").write_text(
            "import sys, time\nfrom pathlib import Path\n"
            f"flag = Path({str(flag)!r})\n"  # repr, so a temp folder with a quote in it (O'Connor) is still a string
            "for _ in range(600):\n    if flag.exists():\n        print('b done'); sys.exit(0)\n    time.sleep(0.1)\n"
            "print('the first line never came while this test ran'); sys.exit(1)\n", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(d / "run.py")], stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        first = p.stdout.readline()
        flag.write_text("")
        rest = p.stdout.read()
        p.wait()
    assert "test_a.py" in first, f"the first test's line comes first: {first!r}"
    assert p.returncode == 0 and "ok       test_b.py" in rest, f"and it came while the second test still ran: {first!r} {rest[-300:]!r}"
    print("run checks passed")


if __name__ == "__main__":
    main()
