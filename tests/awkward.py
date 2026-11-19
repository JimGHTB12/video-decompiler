"""Awkward video files for every tool that turns times into frames, and an oracle to read them.

Each file shows its own frame number in eight bands across the picture (band b white when bit b is set), so a tool's
picture can be named without trusting the tool's clock. `shown(path)` is the oracle: the numbers a plain decode from
the start shows, in order, with no seek and no rate change. Built with ffmpeg; a file is made once per folder.

  numbered(folder)   150 frames, 30 fps, H.264 in MP4: the plain case
  raw_h264(folder)   the same pictures as a raw H.264 elementary stream: no packet times, no seek index
  preroll(folder)    the same packets remuxed 0.1 s early with negative times kept: three packets before 0 that a
                     decode from the start does not show
  vfr_late(folder)   30 frames at 30 fps then 60 at 60 fps, starting 2.5 s into the file's clock
"""
import subprocess
from pathlib import Path

import numpy as np

W, H, BANDS = 128, 72, 8


def picture(k, w=W, h=H):
    """Frame k's picture: band b of the width white when bit b of k is set, dark otherwise (grey, as RGB)."""
    f = np.full((h, w), 24, np.uint8)
    step = w // BANDS
    for b in range(BANDS):
        if k >> b & 1:
            f[:, b * step:(b + 1) * step] = 232
    return np.stack([f, f, f], -1)


def number(rgb):
    """The frame number a picture shows (any size; read from the middle row of each band)."""
    g = np.asarray(rgb, np.float32)
    g = g.mean(axis=2) if g.ndim == 3 else g
    h, w = g.shape
    step = w / BANDS
    return sum(1 << b for b in range(BANDS) if g[h // 3:2 * h // 3, int(b * step + step / 4):int((b + 1) * step - step / 4)].mean() > 128)


def _ff(*args, data=None):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], input=data, check=True)


def _encode(path, numbers, fps):
    _ff("-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "12", "-g", "30",
        "-pix_fmt", "yuv420p", path, data=b"".join(picture(k).tobytes() for k in numbers))


def numbered(folder):
    p = Path(folder) / "numbered.mp4"
    if not p.exists():
        _encode(p, range(150), 30)
    return p


def raw_h264(folder):
    p = Path(folder) / "raw.h264"
    if not p.exists():
        _ff("-i", numbered(folder), "-c:v", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "h264", p)
    return p


def preroll(folder):
    p = Path(folder) / "preroll.mp4"
    if not p.exists():
        _ff("-i", numbered(folder), "-c", "copy", "-output_ts_offset", "-0.1", "-avoid_negative_ts", "disabled", p)
    return p


def vfr_late(folder):
    p = Path(folder) / "vfr_late.mp4"
    if not p.exists():
        a, b, listing = Path(folder) / "_vfr_a.mp4", Path(folder) / "_vfr_b.mp4", Path(folder) / "_vfr.txt"
        _encode(a, range(30), 30)
        _encode(b, range(30, 90), 60)
        listing.write_text(f"file '{a.as_posix()}'\nfile '{b.as_posix()}'\n", encoding="utf-8")
        _ff("-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", "-output_ts_offset", "2.5", p)
    return p


def shown_at(path):
    """[(time, number)] of every picture a plain decode from the start shows, its time counted from the file's start_time
    (the clock the tools use)."""
    import re
    start = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0", str(path)],
                                 capture_output=True, text=True).stdout.strip() or 0)
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", f"scale={W}:{H},showinfo", "-fps_mode", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    pts = [float(x) for x in re.findall(r"showinfo.*?pts_time:\s*(-?[\d.]+)", p.stderr.decode("utf-8", "replace"))]
    n = W * H * 3
    nums = [number(np.frombuffer(p.stdout[i:i + n], np.uint8).reshape(H, W, 3)) for i in range(0, len(p.stdout) - n + 1, n)]
    assert len(pts) == len(nums), (len(pts), len(nums))
    return [(t - start, k) for t, k in zip(pts, nums)]


def shown(path):
    """The frame numbers a plain decode from the start shows, in order: the oracle every tool's pick is checked against."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={W}:{H}", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    n = W * H * 3
    return [number(np.frombuffer(raw[i:i + n], np.uint8).reshape(H, W, 3)) for i in range(0, len(raw) - n + 1, n)]
