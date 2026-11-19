#!/usr/bin/env python3
"""tools/timecheck.py: a picture that stops is found where it stopped, and a film that keeps moving isn't accused.

  python tests/test_timecheck.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

TOOL = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools" / "timecheck.py"
FPS, W, H, SECONDS = 24, 320, 180, 8


def film(path, held=None):
    frames = []
    for i in range(FPS * SECONDS):
        at = held[0] if held and held[0] <= i < held[1] else i
        f = np.full((H, W, 3), 40, np.uint8)
        x = int((at * 7) % (W - 40))
        f[60:120, x:x + 40] = 230
        f[:, :, 1] = np.clip(f[:, :, 1].astype(int) + (at * 3) % 60, 0, 255)
        frames.append(f.tobytes())
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)], input=b"".join(frames), check=True)


def thin_line(path):
    """A two-pixel line draws itself across the frame: a tiny part of the picture, changing the whole time."""
    frames = []
    for i in range(FPS * SECONDS):
        f = np.full((H, W, 3), 20, np.uint8)
        f[88:90, 10:10 + int(i * 1.4)] = 235
        frames.append(f.tobytes())
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)], input=b"".join(frames), check=True)


def findings(path):
    p = subprocess.run([sys.executable, "-X", "utf8", str(TOOL), str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout)["findings"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        clean, stopped = Path(tmp) / "clean.mp4", Path(tmp) / "stopped.mp4"
        film(clean)
        film(stopped, held=(FPS * 3, FPS * 5))
        assert not [f for f in findings(clean) if f["kind"] == "freeze"], "a film that keeps moving isn't accused of stopping"
        line = Path(tmp) / "line.mp4"
        thin_line(line)
        accused = [f for f in findings(line) if f["kind"] in ("freeze", "stutter")]
        assert not accused, f"a thin line being drawn isn't a picture that stopped: {accused}"
        hits = [f for f in findings(stopped) if f["kind"] == "freeze"]
        assert len(hits) == 1 and abs(hits[0]["start"] - 3) < 0.2 and abs(hits[0]["end"] - 5) < 0.2, f"the stop is found where it happened: {hits}"
        sys.path.insert(0, str(TOOL.parent))
        import see
        import timecheck
        from unittest.mock import patch
        unused = []
        real_lap, real_mt = timecheck.cv2.Laplacian, timecheck.cv2.matchTemplate
        with patch.object(timecheck.cv2, "Laplacian", side_effect=lambda *a, **kw: (unused.append("Laplacian"), real_lap(*a, **kw))[1]), \
                patch.object(timecheck.cv2, "matchTemplate", side_effect=lambda *a, **kw: (unused.append("matchTemplate"), real_mt(*a, **kw))[1]):
            got = see.timecheck_findings(stopped, [{"id": 1, "t0": 0.0, "t1": 8.0}])
        assert not unused, f"see.timecheck_findings ran unused detail/correlation passes: {unused[:4]} ({len(unused)} calls)"
        assert got["ran"] and len(got["findings"]) == 1 and got["findings"][0]["shot"] == 1, got
        for clip in (clean, stopped, line):
            full = [f for f in timecheck.detect(timecheck.scan(str(clip))) if f["kind"] in ("freeze", "stutter")]
            fast = timecheck.detect(timecheck.scan(str(clip), motion_only=True))
            assert fast == full, f"{clip.name}: motion_only={fast} != full={full}"
        # Bb2: probe and scan pass NO_WINDOW, and scan calls stop_decoder on early decode error
        import film_diff
        import io
        real_run, real_popen = timecheck.subprocess.run, timecheck.subprocess.Popen
        run_flags, popen_flags = [], []
        with patch.object(timecheck.subprocess, "run", side_effect=lambda *a, **kw: (run_flags.append(kw.get("creationflags")), real_run(*a, **kw))[1]), \
                patch.object(timecheck.subprocess, "Popen", side_effect=lambda *a, **kw: (popen_flags.append(kw.get("creationflags")), real_popen(*a, **kw))[1]):
            timecheck.scan(str(clean), motion_only=True)
        assert run_flags and all(f == film_diff.NO_WINDOW for f in run_flags), run_flags
        assert popen_flags and all(f == film_diff.NO_WINDOW for f in popen_flags), popen_flags

        class FakeProc:
            returncode = 0
            def __init__(self):
                self.stdout = io.BytesIO(b"short")
                self.stderr = io.BytesIO(b"")
            def wait(self, timeout=None):
                return 0
            def kill(self):
                pass
        stopped_procs = []
        with patch.object(timecheck, "probe", lambda p: (64, 64, 64, 64, 24.0)), \
                patch.object(timecheck.subprocess, "Popen", lambda *a, **kw: FakeProc()), \
                patch.object(film_diff, "stop_decoder", side_effect=lambda p, *a, **kw: stopped_procs.append(p)):
            try:
                timecheck.scan(str(clean))
                raise AssertionError("truncated frame should raise ValueError")
            except ValueError as e:
                assert "truncated" in str(e), e
        assert len(stopped_procs) == 1, f"stop_decoder should be called on early exit: {stopped_procs}"
    print("timecheck checks passed")


if __name__ == "__main__":
    main()
