#!/usr/bin/env python3
"""Each worked film in library/films, copied by `vd new NAME --like FILM`, draws with a bare `vd look` (no --composition)
and its tiles carry the film's own times: both films run at 60 frames a second, and the plusone copy's tiles once said
"4.00 s f120". One look per film through raea and the machine's render queue; skipped when raea is not installed.

  python tests/test_worked_films.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
VD = [sys.executable, "-X", "utf8", str(TOOLS / "vd.py")]


def raea_here():
    import raea_run
    try:
        raea_run.checked_binary(say=False)
        return True
    except SystemExit:
        return False


def main():
    import lean
    if not raea_here():
        print("skipped: raea is not installed, so no worked film can be drawn")
        return
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "VD_OUT": str(Path(tmp) / "out")}
        for name in lean.worked_films():
            p = subprocess.run([*VD, "new", name, "--like", name], cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            assert p.returncode == 0, p.stdout + p.stderr
            d = Path(tmp) / name
            p = subprocess.run([*VD, "look", "--at", "2,9"], cwd=d, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            said = p.stdout + p.stderr
            assert p.returncode == 0 and "FAILED" not in said, f"{name}: the copy draws as it is\n{said[-2000:]}"
            assert (Path(tmp) / "out" / name / "look.jpg").is_file(), said
            assert "drawn as film-look" in said, f"{name}: the film without its grain, found with no --composition typed\n{said[-800:]}"
            assert "tile 1:   2.00 s  frame  120" in said and "tile 2:   9.00 s  frame  540" in said, f"{name}: the time is the frame over 60\n{said[-1500:]}"
            print(f"ok {name}: copied, drawn, its tiles at 2.00 s and 9.00 s")


if __name__ == "__main__":
    import utf8  # noqa: F401
    main()
