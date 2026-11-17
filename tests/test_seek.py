#!/usr/bin/env python3
"""Frame-exact seeks and frame clocks, on videos whose pixels encode their own frame number. No raea needed: measure.py and
slot_track.py, font_id.py, measure.py and film_diff.py all fetch "frame f" through one helper, and each tool's own
fetch is checked here directly.

  python tests/test_seek.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import film_diff  # noqa: E402

W, H = 320, 180


def numbered(path, fps, n=120, pts=None):
    """Three bands, each a base-7 digit of the frame number (levels 20 + 33 * digit). pts, an ffmpeg expression in N,
    gives the frames their own times instead of a constant rate."""
    vf = ["-vf", f"setpts='{pts}/TB'", "-fps_mode", "vfr"] if pts else []
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", *vf,
                          "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for i in range(n):
        f = np.zeros((H, W), np.uint8)
        for k, d in enumerate((i // 49, (i // 7) % 7, i % 7)):
            f[:, k * W // 3:(k + 1) * W // 3] = 20 + d * 33
        p.stdin.write(f.tobytes())
    p.stdin.close()
    p.wait()
    return str(path)


def index_of(grey):
    grey = cv2.resize(np.asarray(grey, np.uint8), (W, H), interpolation=cv2.INTER_AREA)
    d = [int(round((float(np.median(grey[20:-20, k * W // 3 + 8:(k + 1) * W // 3 - 8])) - 20) / 33)) for k in range(3)]
    return d[0] * 49 + d[1] * 7 + d[2]


def grab(video, ss):
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{ss:.6f}", "-i", video, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return index_of(np.frombuffer(raw, np.uint8).reshape(H, W))


def first_of(frames):
    """The first frame of a stream, with the stream closed, so its ffmpeg lets go of the file (Windows can't delete it otherwise)."""
    try:
        return index_of(next(frames))
    finally:
        frames.close()


def test_every_tool_lands_on_frame_f(tmp):
    # broke: a seek to f / fps printed to 3 or 4 decimals (0.0167 for 1/60 s) lies just after frame f, and ffmpeg
    # returned frame f + 1 one time in three, in fit.py, film_diff, slot_track, font_id and measure's stills
    import measure
    for fps in (30, 60):
        video = numbered(tmp / f"num{fps}.mp4", fps)
        times = film_diff.clock(video)
        wrong = [f for f in range(120) if grab(video, film_diff.seek_to(times, f / fps)[0]) != f]
        assert not wrong, f"seek_to at {fps} fps: frames {wrong[:6]} came back as other frames"
        wrong = [f for f in range(120) if film_diff.seek_to(times, round(f / fps, 3))[1] != f]
        assert not wrong, f"a time rounded to 3 decimals, as measure.json writes them, is still frame f: {wrong[:6]}"
        for f in range(1, 31):
            t4, t3 = round(f / fps, 4), round(f / fps, 3)
            got = {
                "measure.grab": index_of(cv2.cvtColor(measure.grab(video, t3, times), cv2.COLOR_RGB2GRAY)),
                "film_diff.full_frame": index_of(np.asarray(film_diff.full_frame(video, t4, times=times).convert("L"))),
                "film_diff.stream --from": first_of(film_diff.stream(video, t4, 0.1, float(fps), times)),
            }
            bad = {k: v for k, v in got.items() if v != f}
            assert not bad, f"frame {f} at {fps} fps came back as {bad}"


def test_zero_rate_is_not_a_crash(tmp):
    # broke: an avg_frame_rate of 0/0 divided by zero in measure.probe, film_diff.probe and rebuild_score
    assert film_diff.rate("0/0") == 0.0 and film_diff.rate("30000/1001") == 30000 / 1001
    assert film_diff.fps_of({"avg_frame_rate": "0/0", "r_frame_rate": "25/1"}) == 25.0, "falls back to the other rate"
    try:
        film_diff.fps_of({"avg_frame_rate": "0/0", "r_frame_rate": "0/0"})
        raise AssertionError("no rate at all should be refused with a message")
    except SystemExit as e:
        assert "0/0" in str(e) and "-fps_mode cfr" in str(e), e


def test_variable_rate(tmp):
    # broke: sheet, motion, slot_track and swap_sheet turned frame numbers into times with r_frame_rate, so on a
    # variable-rate file a frame shown at 2.0 s was stamped 3.0 s
    vfr = numbered(tmp / "vfr.mp4", 60, n=90, pts="if(lt(N,30),N/30,1+(N-30)/60)")
    times = film_diff.frame_times(vfr)
    assert len(times) == 90 and abs(times[30] - 1.0) < 1e-3 and abs(times[89] - (1 + 59 / 60)) < 1e-3, f"each frame's own time: {times[28:33]}"
    assert film_diff.variable_rate(times) and not film_diff.variable_rate(film_diff.frame_times(numbered(tmp / "cfr.mp4", 30, n=40)))
    assert grab(vfr, film_diff.seek_to(times, 1.5)[0]) == 60, "the frame shown at 1.5 s is frame 60, 30 frames in at 60 a second"


def test_a_phone_clip_is_its_shown_shape(tmp):
    # broke: ffprobe() gave a phone clip's stored size, a landscape frame, while ffmpeg decodes it turned upright, so the
    # tools that size their frames from it read a portrait picture squashed into landscape
    stored = tmp / "stored.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=320x180:r=30:d=1", "-vf", "drawbox=x=0:y=0:w=160:h=180:c=black:t=fill",
                    "-pix_fmt", "yuv420p", str(stored)], check=True)                     # left half black
    phone = tmp / "phone.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-display_rotation", "90", "-i", str(stored), "-c", "copy", str(phone)], check=True)
    raw = film_diff.ffprobe(phone)
    assert (raw["w"], raw["h"]) == (180, 320), f"the size it is shown at: {raw}"
    assert film_diff.ffprobe(stored)["w"] == 320, "and a clip with no rotation keeps its own"
    # the older rotate tag, and a turn the other way, as other phones and older ffmpeg write them
    assert film_diff.shown_size({"width": 1920, "height": 1080, "tags": {"rotate": "270"}}) == (1080, 1920)
    assert film_diff.shown_size({"width": 1920, "height": 1080, "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}) == (1080, 1920)
    assert film_diff.shown_size({"width": 1920, "height": 1080, "side_data_list": [{"rotation": 180}]}) == (1920, 1080)


def card(path, step, seconds=1.0, fps=30):
    """A textured card sliding right `step` px a frame on a flat ground. Its left edge on frame n is 100 + step * n."""
    rng = np.random.default_rng(5)
    tex = cv2.GaussianBlur(rng.integers(0, 255, (120, 200)).astype(np.float32), (0, 0), 2)
    tex = cv2.normalize(tex, None, 30, 230, cv2.NORM_MINMAX).astype(np.uint8)
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "640x360", "-r", str(fps), "-i", "-",
                          "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for n in range(int(seconds * fps)):
        f = np.full((360, 640), 60, np.uint8)
        f[100:220, 100 + step * n:300 + step * n] = tex
        p.stdin.write(f.tobytes())
    p.stdin.close()
    p.wait()
    return str(path)


def peak_mb(cmd):
    """Run a tool; its exit code, its output and the most private memory it held, in MB."""
    if os.name != "nt":
        # Off Windows the peak comes from a go-between with this one child. The figure for all of this process's children
        # is the largest of every tool run so far, so a later, smaller run would read as an earlier one's peak.
        cmd = [sys.executable, "-c", "import resource, subprocess, sys\nr = subprocess.run(sys.argv[1:])\n"
               "print('\\npeak-rss', resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, file=sys.stderr)\nsys.exit(r.returncode)", *map(str, cmd)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(k, ctypes.c_size_t) for k in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.kernel32.K32GetProcessMemoryInfo(wintypes.HANDLE(int(p._handle)), ctypes.byref(c), c.cb)
        peak = c.PeakPagefileUsage
    else:
        err, _, rss = err.rpartition("\npeak-rss ")
        peak = int(rss) * (1 if sys.platform == "darwin" else 1024)      # macOS counts in bytes, Linux in kilobytes
    return p.returncode, out + err, peak / 2 ** 20


def removed(folder, wait=5.0):
    """Remove a test's folder, waiting up to `wait` seconds for a file another process holds: on the hosted Windows
    runners num60.mp4 was still held when the folder was removed (2 runs in 5), after every ffmpeg here had exited and
    been waited on (most likely a virus scanner reading the new file; not confirmed). A file still held after that is a
    real leak, and fails."""
    import shutil
    import time
    end = time.monotonic() + wait
    while True:
        try:
            shutil.rmtree(folder)
            return
        except PermissionError:
            if time.monotonic() > end:
                raise
            time.sleep(0.25)


def main():
    for t in (test_zero_rate_is_not_a_crash, test_every_tool_lands_on_frame_f, test_variable_rate, test_a_phone_clip_is_its_shown_shape):
        tmp = tempfile.mkdtemp()
        try:
            t(Path(tmp))
        finally:
            removed(tmp)
        print("ok", t.__name__)
    print("seek checks passed")


if __name__ == "__main__":
    main()
