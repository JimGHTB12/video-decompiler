#!/usr/bin/env python3
"""What a tool prints is UTF-8 when it is read through a pipe, as an agent reads it, whatever the system's code page.

  python tests/test_output.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"


def test_a_name_with_an_arrow_is_said_back():
    # broke: on Windows a vd command wrote its record, then stopped with UnicodeEncodeError as it printed a note with an
    # arrow back. A pipe there takes the system's code page, which has no arrow
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}       # what a pipe gets on a Western Windows, here on any system
    env.pop("PYTHONUTF8", None)
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run([sys.executable, str(TOOLS / "vd.py"), "new", "pile→beat", "--kind", "launch"], cwd=d, env=env, capture_output=True)
        said = p.stdout.decode("utf-8") + p.stderr.decode("utf-8", "replace")
        assert p.returncode == 0 and "Traceback" not in said and "pile→beat" in said, f"a character outside the code page is printed, in UTF-8: {said}"


def test_every_tool_sets_its_output_as_it_starts():
    # one tool was where it showed. Any tool that prints a film's words, a transcript or a path can meet the same character
    missing = []
    for tool in sorted(TOOLS.glob("*.py")):
        text = tool.read_text(encoding="utf-8")
        guard = re.search(r"^if __name__ == [\"']__main__[\"']:\n(.*)\n", text, re.M)
        if guard and guard.group(1).strip() != "import utf8  # noqa: F401":
            missing.append(tool.name)
    assert not missing, f"these tools start without `import utf8` as the first line under their `if __name__` line: {missing}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("output checks passed")
