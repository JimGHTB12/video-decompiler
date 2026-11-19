#!/usr/bin/env python3
"""vd.py doctor runs on a Python with none of the skill's packages, and says what to install.

  python tests/test_bare_python.py

doctor is the first thing a new user runs, and how they learn what to install. vd.py imported film_diff at the top, and
film_diff needs numpy, so on a fresh Python doctor stopped with "No module named 'numpy'" before it printed anything.
The packages are hidden here by setting their sys.modules entries to None, so `import` fails as if they weren't installed.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

VD = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools" / "vd.py"
BARE = ("import runpy, sys\n"
        "for m in ('numpy', 'cv2', 'PIL', 'psutil'): sys.modules[m] = None\n"
        "sys.argv = [sys.argv[1]] + sys.argv[2:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n")


def bare(*args, cwd=None, env=None):
    import os
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", BARE, str(VD), *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, **(env or {})})
    return p.returncode, p.stdout + p.stderr


def main():
    with tempfile.TemporaryDirectory() as hub:
        code, out = bare("doctor", env={"HF_HUB_CACHE": hub})
    assert "Traceback" not in out, f"doctor runs without the packages: {out}"
    # the transcriber is optional: listed, with when it is needed, and never a reason doctor fails
    line = next((l for l in out.splitlines() if "transcriber (optional" in l), "")
    assert line.startswith("  --   transcriber (optional, not here") and "vd measure and vd pin" in line and "not transcribed" in line, out
    assert "MISS transcriber" not in out and "transcriber:" not in out.split("To fix:")[-1], out
    sys.path.insert(0, str(VD.parent))
    import vd
    assert "raea.exe" in vd.raea_fix("nt") and ".exe" not in vd.raea_fix("posix"), "the missing-raea fix names the executable each system has"
    assert code == 1, f"and fails, as they are missing: {code} {out}"
    for m in ("numpy", "cv2", "PIL", "psutil"):
        assert f"MISS {m}" in out, f"{m} is listed as missing: {out}"
    assert "pip install -r" in out or "-m venv" in out, f"and it says how to install them: {out}"
    code, out = bare("--help")
    assert code == 0 and "Traceback" not in out and "doctor" in out, f"--help needs no packages either: {out}"
    with tempfile.TemporaryDirectory() as tmp:
        code, out = bare("look", cwd=tmp)
        assert "Traceback" not in out and "score.json" in out, f"nor does look outside a film folder, which says what it needs: {out}"
    # E8: vd doctor's optional_tools reads voice_clean.FILTERS without importing numpy
    p_vc = subprocess.run([sys.executable, "-X", "utf8", "-c",
                           f"import sys; sys.modules['numpy'] = None; sys.path.insert(0, r'{VD.parent}'); import vd; vd.optional_tools()"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p_vc.returncode == 0 and "vd audio --clean-voice" in p_vc.stdout, (p_vc.returncode, p_vc.stdout, p_vc.stderr)
    print("bare python checks passed")


if __name__ == "__main__":
    main()
