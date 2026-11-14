#!/usr/bin/env python3
"""Run every test in this folder and say what passed, what failed and what was skipped.

  python tests/run.py [NAME ...] [--timeout 900]

Each test file is a script: it builds small inputs with known answers (a video with a planted stutter, a kit with a
planted leak), runs one tool on them, and exits 0 if the tool found what was planted. This runs them one after another, each
in its own process, so a list of tests in a README can never fall behind the folder. Tests that need raea or bun say
"skipped" when it isn't installed, and that is counted as skipped, not passed. Give names to run only some of them:
`python tests/run.py scan pack`. A name that is a test's own name runs that test alone (`queue` is test_queue.py, not
test_render_queue.py); any other name runs every test whose name contains it.

Needs ffmpeg and the packages in skills/video-decompiler/requirements.txt.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="run only these tests: a test's own name, or part of several names")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds one test file may take")
    a = ap.parse_args()
    every = sorted(HERE.glob("test_*.py"))
    stems = {f.stem for f in every}

    def named(f):
        # `queue` is test_queue.py and nothing else; only a name that is no test's own name picks every test containing it
        return any(f.stem in (n, "test_" + n) if {n, "test_" + n} & stems else n in f.stem for n in a.names)

    files = [f for f in every if not a.names or named(f)]
    if not files:
        raise SystemExit("no test matches " + ", ".join(a.names))
    passed, failed, skipped, started = [], [], [], time.time()
    for f in files:
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, "-X", "utf8", str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=a.timeout)
            code, out = p.returncode, (p.stdout + p.stderr)
        except subprocess.TimeoutExpired as e:
            code, out = 124, f"took longer than {a.timeout:.0f} s\n" + str(e.stdout or "")[-2000:]
        took = time.time() - t0
        if code != 0:
            failed.append(f.name)
            print(f"FAIL     {f.name}  ({took:.0f} s)")
            print("         " + "\n         ".join(out.strip().splitlines()[-25:]), flush=True)
        elif "skipped" in out.lower():
            skipped.append(f.name)
            why = next((l.strip() for l in out.splitlines() if "skipped" in l.lower()), "")
            print(f"skipped  {f.name}  ({why})", flush=True)
        else:
            passed.append(f.name)
            print(f"ok       {f.name}  ({took:.0f} s)", flush=True)
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped, in {time.time() - started:.0f} s.")
    if failed:
        print("failed: " + ", ".join(failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
