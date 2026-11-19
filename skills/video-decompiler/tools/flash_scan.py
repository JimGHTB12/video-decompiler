#!/usr/bin/env python3
"""WCAG 2.3.1 general & saturated-red flash scanner and WCAG 2.1 4.5:1 contrast verifier, ported from legible-film.

  python flash_scan.py FILM.mp4 [--json flash.json] [--width 192] [--start S] [--end E]

WCAG 2.3.1 fails content that flashes more than three times (> 6 opposing transitions) in any one second when the
flashing area exceeds 25% of a 10-degree visual field (approximated by overlapping 1/3 x 1/3 windows in both area
and point sampling):
  - General flash: >= 25% of window pixels change by >= 0.10 IEC 61966-2-1 relative luminance in the same direction
    with darker endpoint < 0.80, reversed in the same pixels within 1.0 s.
  - Red flash: >= 25% of window pixels change in saturated-red amount (R - G - B) * 320 by >= 20 where R/(R+G+B) >= 0.8,
    reversed in the same pixels within 1.0 s.
Also provides IEC 61966-2-1 relative luminance and WCAG 2.1 contrast ratio `(L_max + 0.05) / (L_min + 0.05)` (4.5:1
for normal text, 3.0:1 for large text >= 24 px) used by `look.py` to catch figure-ground collisions (Test 5).
"""
import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

PTS = re.compile(r"pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)")
PTS_TICKS = re.compile(r"\bpts:\s*(-?\d+)\s+pts_time:")
TIME_BASE = re.compile(r"config in time_base:\s*(\d+)/(\d+)")
DUR = re.compile(r"duration_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)")

WCAG_NORMAL_RATIO = 4.5
WCAG_LARGE_RATIO = 3.0


def _srgb_linear_float(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# 256-entry uint8 table built by the float formula itself: every byte decodes to the same float32 bits without pow(2.4) per pixel
_SRGB_LUT = _srgb_linear_float(np.arange(256, dtype=np.float32) / 255.0)


def srgb_to_linear(c8):
    """IEC 61966-2-1 exact piecewise sRGB to linear light conversion for uint8 (0..255) or float (0..1) arrays."""
    raw = np.asarray(c8)
    if raw.dtype == np.uint8:
        return _SRGB_LUT[raw]
    c = raw.astype(np.float32)
    # whole numbers are 0..255 always: guessed from the largest value, near-black #010101 was read as 0..1, so white
    if np.issubdtype(raw.dtype, np.integer) or (c.size and float(c.max()) > 1.001):
        c = c / 255.0
    return _srgb_linear_float(c)


def red_amount(lin):
    """Saturated-red amount (R - G - B) * 320 where R/(R+G+B) >= 0.8, per pixel of linear-light RGB."""
    s = lin.sum(axis=2) + 1e-9
    return np.asarray(
        np.where(lin[..., 0] / s >= 0.8, np.maximum(0.0, (lin[..., 0] - lin[..., 1] - lin[..., 2]) * 320.0), 0.0),
        dtype=np.float32,
    )


RED_THRESHOLD = 20.0


def _red_floor():
    """The lowest red byte whose pure red (G = B = 0) reaches RED_THRESHOLD, read from the table the scan uses."""
    pure = np.zeros((1, 256, 3), dtype=np.uint8)
    pure[0, :, 0] = np.arange(256)
    return int(np.flatnonzero(red_amount(srgb_to_linear(pure))[0] >= RED_THRESHOLD)[0])


# Byte 71 (20.16; byte 70 gives 19.60). Green or blue only lower the amount, so a pixel whose red byte is under the
# floor, or not above its green and blue, never counts as red: the scan may skip a frame with too few other pixels.
RED_FLOOR = _red_floor()


def relative_luminance(rgb):
    """WCAG 2.1 / ITU-R BT.709 relative luminance Y in 0..1."""
    lin = srgb_to_linear(rgb)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def wcag_contrast_ratio(luma_a, luma_b):
    """WCAG 2.1 contrast ratio (L_bright + 0.05) / (L_dark + 0.05), in 1.0..21.0."""
    la = np.asarray(luma_a, dtype=np.float32)
    lb = np.asarray(luma_b, dtype=np.float32)
    hi = np.maximum(la, lb)
    lo = np.minimum(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@functools.lru_cache(maxsize=4)
def passthrough(ffmpeg):   # asked of ffmpeg once a process: its version doesn't change while we run
    try:
        head = subprocess.run([ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    except OSError:
        head = ""
    m = re.search(r"version n?(\d+)\.(\d+)", head)
    old = m is not None and (int(m.group(1)), int(m.group(2))) < (5, 1)
    return ["-vsync" if old else "-fps_mode", "passthrough"]


class Frames:
    """Decode each frame of the first video stream once, in order, with its presentation timestamp."""

    def __init__(self, ffmpeg, path, vf, frame_bytes, start=None, end=None):
        window = (["-ss", f"{start:.6f}"] if start else []) + (
            ["-t", f"{end - (start or 0.0):.6f}"] if end is not None else []
        )
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-nostats", *window, "-i", str(path), "-map", "0:v:0",
            "-vf", vf + ",showinfo", *passthrough(ffmpeg), "-f", "rawvideo", "pipe:1",
        ]
        self.size, self.pts, self.dur, self.log = frame_bytes, [], [], []
        self.time_base = None
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        self.reader = threading.Thread(target=self._read_log, daemon=True)
        self.reader.start()

    def _read_log(self):
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            config = TIME_BASE.search(line) if "showinfo" in line else None
            if config:
                self.time_base = Fraction(int(config.group(1)), int(config.group(2)))
            m = PTS.search(line) if "showinfo" in line else None
            if m:
                ticks = PTS_TICKS.search(line)
                if ticks and self.time_base is not None:
                    self.pts.append(float(int(ticks.group(1)) * self.time_base))
                else:
                    self.pts.append(float(m.group(1)))
                d = DUR.search(line)
                self.dur.append(float(d.group(1)) if d else None)
            elif line:
                self.log = self.log[-4:] + [line]

    def close(self, kill_live=False):
        if not self.proc.stdout.closed:
            self.proc.stdout.close()
        if kill_live and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        else:
            self.proc.wait()
        self.reader.join()
        if not self.proc.stderr.closed:
            self.proc.stderr.close()

    def __iter__(self):
        eof = False
        try:
            while True:
                buf = self.proc.stdout.read(self.size)
                if len(buf) < self.size:
                    eof = True
                    break
                yield buf
        finally:
            self.close(kill_live=not eof)

    def times(self, count):
        if self.proc.returncode or count == 0:
            raise RuntimeError("ffmpeg could not decode the video" + (f": {self.log[-1]}" if self.log else ""))
        if len(self.pts) != count:
            raise RuntimeError(f"decoded {count} frames but read {len(self.pts)} timestamps")
        return list(self.pts)

    def end(self):
        last = self.dur[-1] if self.dur else None
        if last and last > 0:
            return self.pts[-1] + last
        return self.pts[-1] + (self.pts[-1] - self.pts[-2] if len(self.pts) > 1 else 0.0)


def timing(times):
    steps = np.diff(times) if len(times) > 1 else np.zeros(1)
    typical = float(np.median(steps))
    variable = len(times) > 2 and typical > 0 and float(steps.max() - steps.min()) > 0.25 * typical
    return ("variable" if variable else "constant"), typical


def probe(ffprobe, path):
    return probe_order(ffprobe, path)[:3]


def probe_order(ffprobe, path):
    """(width, height, rate, field_order) in one ffprobe: field_order says at once whether the picture is interlaced
    where the stream states it (interlaced() decodes 30 frames to find out otherwise)."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,field_order", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, creationflags=NO_WINDOW,
    ).stdout
    streams = json.loads(out).get("streams") or []
    if not streams:
        raise RuntimeError("no video stream")
    s = streams[0]
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = s.get(key, "0/0").partition("/")
        if float(den or 1) and float(num):
            return int(s["width"]), int(s["height"]), float(num) / float(den or 1), s.get("field_order", "")
    raise RuntimeError("could not read the frame rate")


def interlaced(ffprobe, path):
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#30", "-show_entries", "stream=field_order:frame=interlaced_frame", "-of", "json", str(path)],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    )
    data = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    order = ((data.get("streams") or [{}])[0]).get("field_order", "")
    return order in ("tt", "bb", "tb", "bt") or any(f.get("interlaced_frame") == 1 for f in data.get("frames", []))


def translated(values, motion, fill):
    dy, dx = motion
    height, width = values.shape
    out = fill.copy()
    y0, y1 = max(0, dy), min(height, height + dy)
    x0, x1 = max(0, dx), min(width, width + dx)
    if y1 > y0 and x1 > x0:
        out[y0:y1, x0:x1] = values[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


def unique_translation(previous, current):
    height, width = previous.shape
    first = np.fft.rfft2(previous - np.mean(previous))
    autocorrelation = np.fft.irfft2(first * np.conj(first), s=previous.shape).real
    zero = float(autocorrelation[0, 0])
    if zero <= 1e-9:
        return None
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            autocorrelation[dy % height, dx % width] = 0
    if float(np.max(autocorrelation)) >= 0.5 * zero:
        return None
    second = np.fft.rfft2(current - np.mean(current))
    cross = second * np.conj(first)
    correlation = np.fft.irfft2(cross / np.maximum(np.abs(cross), 1e-9), s=previous.shape).real
    peak_y, peak_x = np.unravel_index(np.argmax(correlation), correlation.shape)
    peak = float(correlation[peak_y, peak_x])
    rest = correlation.copy()
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            rest[(peak_y + dy) % height, (peak_x + dx) % width] = 0
    runner_up = float(np.max(rest))
    dy = int(peak_y if peak_y <= height // 2 else peak_y - height)
    dx = int(peak_x if peak_x <= width // 2 else peak_x - width)
    if not (dx or dy) or abs(dx) > width // 6 or abs(dy) > height // 6 or peak < 0.12 or peak < 2 * max(runner_up, 1e-9):
        return None
    aligned = translated(previous, (dy, dx), current)
    residual = float(np.mean(np.abs(aligned - current)))
    unaligned = float(np.mean(np.abs(previous - current)))
    return (dy, dx) if residual < 0.025 and residual < unaligned * 0.25 else None


class CoherentZig:
    def __init__(self, threshold=0.10, area=0.25, darker_below=0.80, ambiguous_patterns=True, paired=True, pair_window=1.0):
        self.threshold = threshold
        self.area = area
        self.darker_below = darker_below
        self.ambiguous_patterns = ambiguous_patterns
        self.paired = paired
        self.pair_window = pair_window
        self.pivot = None
        self.extreme = None
        self.extreme_time = None
        self.direction = 0
        self.ends = []
        self.ambiguous_ends = []
        self.coherent_ends = []
        self.swings = []

    def moved(self, earlier, later, direction):
        moved = (later - earlier) * direction >= self.threshold
        if self.darker_below is not None:
            moved &= np.minimum(earlier, later) < self.darker_below
        return moved

    def changed(self, earlier, later, direction):
        return np.count_nonzero(self.moved(earlier, later, direction)) >= self.area * earlier.size

    def push(self, when, values, motion=None):
        image = np.asarray(values, dtype=np.float32)
        pixels = image.ravel()
        if self.pivot is None:
            self.pivot = pixels.copy()
            self.extreme = pixels.copy()
            self.extreme_time = when
            return
        if motion is not None and image.ndim == 2:
            self.pivot = translated(self.pivot.reshape(image.shape), motion, image).ravel()
            self.extreme = translated(self.extreme.reshape(image.shape), motion, image).ravel()
        if not self.direction:
            for direction in (1, -1):
                if self.changed(self.pivot, pixels, direction):
                    self.direction = direction
                    self.extreme = pixels.copy()
                    self.extreme_time = when
                    break
            return
        if self.changed(self.extreme, pixels, -self.direction):
            self.record_extreme()
            self.pivot = self.extreme
            self.extreme = pixels.copy()
            self.extreme_time = when
            self.direction = -self.direction
        elif (float(np.mean(pixels)) - float(np.mean(self.extreme))) * self.direction > 0 and self.changed(self.pivot, pixels, self.direction):
            self.extreme = pixels.copy()

    def finish(self):
        if self.direction:
            self.record_extreme()
            self.direction = 0
        self.resolve()

    def record_extreme(self):
        moved = self.moved(self.pivot, self.extreme, self.direction)
        if np.count_nonzero(moved) < self.area * moved.size:
            return
        classic = not (self.ambiguous_patterns and self.changed(self.pivot, self.extreme, -self.direction))
        (self.coherent_ends if classic else self.ambiguous_ends).append(self.extreme_time)
        if self.paired:
            self.swings.append((self.extreme_time, self.direction, np.packbits(moved), moved.size, classic))
        elif classic:
            self.ends.append(self.extreme_time)

    def resolve(self, clock=None):
        if not self.paired:
            return
        clock = clock or (lambda when: when)
        kept = [False] * len(self.swings)
        for i, (when, direction, moved, size, _) in enumerate(self.swings):
            for k in range(i - 1, -1, -1):
                other_when, other_direction, other_moved, _, _ = self.swings[k]
                if clock(when) - clock(other_when) > self.pair_window + 1e-9:
                    break
                if other_direction == -direction and int(np.unpackbits(moved & other_moved).sum()) >= self.area * size:
                    kept[i] = kept[k] = True
        self.ends = [swing[0] for swing, keep in zip(self.swings, kept) if keep and swing[4]]


class RedZig(CoherentZig):
    def __init__(self, threshold=RED_THRESHOLD, area=0.25, paired=True):
        super().__init__(threshold=threshold, area=area, darker_below=None, ambiguous_patterns=False, paired=paired)


class GeneralZig:
    def __init__(self, threshold=0.10, area=0.25):
        self.threshold = threshold
        self.area = area
        self.pivot = None
        self.extreme = None
        self.extreme_time = None
        self.ends = []

    def changed(self, earlier, later):
        return (np.abs(later - earlier) >= self.threshold) & (np.minimum(earlier, later) < 0.80)

    def push(self, when, values, motion=None):
        image = np.asarray(values, dtype=np.float32)
        pixels = image.ravel()
        if self.pivot is None:
            self.pivot = pixels.copy()
            return
        if motion is not None and image.ndim == 2:
            self.pivot = translated(self.pivot.reshape(image.shape), motion, image).ravel()
            if self.extreme is not None:
                self.extreme = translated(self.extreme.reshape(image.shape), motion, image).ravel()
        if self.extreme is None:
            if np.count_nonzero(self.changed(self.pivot, pixels)) >= self.area * pixels.size:
                self.extreme = pixels.copy()
                self.extreme_time = when
            return
        forward = self.extreme - self.pivot
        backward = pixels - self.extreme
        reversals = self.changed(self.pivot, self.extreme) & self.changed(self.extreme, pixels) & (forward * backward < 0)
        if np.count_nonzero(reversals) >= self.area * pixels.size:
            self.ends.append(self.extreme_time)
            self.pivot = self.extreme
            self.extreme = pixels.copy()
            self.extreme_time = when
        elif np.abs(pixels - self.pivot).sum() > np.abs(self.extreme - self.pivot).sum():
            self.extreme = pixels.copy()

    def finish(self):
        if self.extreme is not None:
            self.ends.append(self.extreme_time)


class AreaTransitions:
    def __init__(self, threshold=0.10, area=0.25, overlap=0.12):
        self.threshold = threshold
        self.area = area
        self.overlap = overlap
        self.previous = None
        self.event_delta = None
        self.event_mask = None
        self.event_time = None
        self.chain = False
        self.ends = []

    def push(self, when, values, motion=None):
        image = np.asarray(values, dtype=np.float32)
        if self.previous is None:
            self.previous = image.copy()
            return
        old = translated(self.previous, motion, image) if motion is not None else self.previous
        if motion is not None and self.event_delta is not None:
            empty = np.zeros_like(image)
            self.event_delta = translated(self.event_delta, motion, empty)
            self.event_mask = translated(self.event_mask.astype(np.float32), motion, empty) > 0.5
        delta = image - old
        changed = (np.abs(delta) >= self.threshold) & (np.minimum(image, old) < 0.80)
        if np.count_nonzero(changed) >= self.area * changed.size:
            if self.event_delta is not None:
                reversal = changed & self.event_mask & (delta * self.event_delta < 0)
                if np.count_nonzero(reversal) >= self.overlap * changed.size:
                    if not self.chain:
                        self.ends.append(self.event_time)
                    self.ends.append(when)
                    self.chain = True
                else:
                    self.chain = False
            self.event_delta = delta
            self.event_mask = changed
            self.event_time = when
        self.previous = image.copy()

    def finish(self):
        pass


_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.int32)


def _translated_batch(values_3d, motion, fill_3d):
    dy, dx = motion
    _, height, width = values_3d.shape
    out = fill_3d.copy()
    y0, y1 = max(0, dy), min(height, height + dy)
    x0, x1 = max(0, dx), min(width, width + dx)
    if y1 > y0 and x1 > x0:
        out[:, y0:y1, x0:x1] = values_3d[:, y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


def _integral_counts(mask, sat, x0, y0, x1, y1):
    """Exact count_nonzero(mask[y0:y1, x0:x1]) for all windows from one per-frame int32 summed-area table."""
    np.cumsum(mask, axis=0, dtype=np.int32, out=sat[1:, 1:])
    np.cumsum(sat[1:, 1:], axis=1, dtype=np.int32, out=sat[1:, 1:])
    return sat[y1, x1] - sat[y0, x1] - sat[y1, x0] + sat[y0, x0]


class _CoherentBatch:
    """Lockstep CoherentZig / RedZig state machines across all K scan windows at once."""

    def __init__(self, k, wh, ww, threshold=0.10, area=0.25, darker_below=0.80, ambiguous_patterns=True, paired=True, pair_window=1.0):
        self.k, self.wh, self.ww, self.p = k, wh, ww, wh * ww
        self.threshold = np.float32(threshold)
        self.area = area
        self.min_pixels = area * self.p
        self.darker_below = np.float32(darker_below) if darker_below is not None else None
        self.ambiguous_patterns = ambiguous_patterns
        self.paired = paired
        self.pair_window = pair_window
        self.pivot = None
        self.extreme = None
        self.piv_dark = None
        self.ext_dark = None
        self.extreme_mean = np.zeros(k, dtype=np.float64)
        self.extreme_time = np.zeros(k, dtype=np.int64)
        self.direction = np.zeros(k, dtype=np.int8)
        self.dir_f = np.zeros(k, dtype=np.float32)
        self.zero_pivot = np.zeros(k, dtype=bool)
        self._d = np.empty((k, self.p), dtype=np.float32)
        self._b1 = np.empty((k, self.p), dtype=bool)
        self._b2 = np.empty((k, self.p), dtype=bool)
        self.ends = [[] for _ in range(k)]
        self.ambiguous_ends = [[] for _ in range(k)]
        self.coherent_ends = [[] for _ in range(k)]
        self.swings = [[] for _ in range(k)]

    def _moved(self, earlier, later, direction):
        moved = (later - earlier) * direction >= self.threshold
        if self.darker_below is not None:
            moved &= np.minimum(earlier, later) < self.darker_below
        return moved

    def _record_one(self, idx):
        d = int(self.direction[idx])
        piv, ext = self.pivot[idx], self.extreme[idx]
        moved = self._moved(piv, ext, d)
        if int(np.count_nonzero(moved)) < self.min_pixels:
            return
        classic = not (self.ambiguous_patterns and int(np.count_nonzero(self._moved(piv, ext, -d))) >= self.min_pixels)
        t = int(self.extreme_time[idx])
        (self.coherent_ends[idx] if classic else self.ambiguous_ends[idx]).append(t)
        if self.paired:
            self.swings[idx].append((t, d, np.packbits(moved), self.p, classic))
        elif classic:
            self.ends[idx].append(t)

    def push(self, when, windows_3d, pix_means=None, pix_dark=None, motion=None):
        pixels = windows_3d.reshape(self.k, self.p)
        if self.pivot is None:
            self.pivot = pixels.copy()
            self.extreme = pixels.copy()
            self.extreme_time.fill(when)
            self.extreme_mean[:] = pix_means if pix_means is not None else pixels.mean(axis=1).astype(np.float64)
            if self.darker_below is not None:
                self.piv_dark = pix_dark.copy() if pix_dark is not None else (pixels < self.darker_below)
                self.ext_dark = self.piv_dark.copy()
            else:
                self.zero_pivot = ~np.any(pixels != 0.0, axis=1)
            return
        if motion is not None:
            self.pivot = _translated_batch(self.pivot.reshape(self.k, self.wh, self.ww), motion, windows_3d).reshape(self.k, self.p)
            self.extreme = _translated_batch(self.extreme.reshape(self.k, self.wh, self.ww), motion, windows_3d).reshape(self.k, self.p)
            self.extreme_mean[:] = self.extreme.mean(axis=1).astype(np.float64)
            if self.darker_below is not None:
                np.less(self.pivot, self.darker_below, out=self.piv_dark)
                np.less(self.extreme, self.darker_below, out=self.ext_dark)
            else:
                self.zero_pivot = ~np.any(self.pivot != 0.0, axis=1)
        if pix_means is None:
            pix_means = pixels.mean(axis=1).astype(np.float64)
        if self.darker_below is not None and pix_dark is None:
            pix_dark = pixels < self.darker_below
        has_dir = self.direction != 0
        idx0 = np.flatnonzero(~has_dir)
        if idx0.size:
            piv0, pix0 = self.pivot[idx0], pixels[idx0]
            diff0 = pix0 - piv0
            if self.darker_below is not None:
                dark0 = self.piv_dark[idx0] | pix_dark[idx0]
                up = np.count_nonzero((diff0 >= self.threshold) & dark0, axis=1) >= self.min_pixels
                dn = (~up) & (np.count_nonzero((-diff0 >= self.threshold) & dark0, axis=1) >= self.min_pixels)
            else:
                up = np.count_nonzero(diff0 >= self.threshold, axis=1) >= self.min_pixels
                dn = (~up) & (np.count_nonzero(-diff0 >= self.threshold, axis=1) >= self.min_pixels)
            if np.any(up):
                u = idx0[up]
                self.direction[u] = 1
                self.dir_f[u] = 1.0
                self.extreme[u] = pixels[u]
                self.extreme_mean[u] = pix_means[u]
                if self.darker_below is not None:
                    self.ext_dark[u] = pix_dark[u]
                self.extreme_time[u] = when
            if np.any(dn):
                v = idx0[dn]
                self.direction[v] = -1
                self.dir_f[v] = -1.0
                self.extreme[v] = pixels[v]
                self.extreme_mean[v] = pix_means[v]
                if self.darker_below is not None:
                    self.ext_dark[v] = pix_dark[v]
                self.extreme_time[v] = when
        if np.any(has_dir):
            np.subtract(pixels, self.extreme, out=self._d)
            np.multiply(self._d, -self.dir_f[:, None], out=self._d)
            np.greater_equal(self._d, self.threshold, out=self._b1)
            if self.darker_below is not None:
                np.bitwise_or(self.ext_dark, pix_dark, out=self._b2)
                self._b1 &= self._b2
            rev = has_dir & (np.count_nonzero(self._b1, axis=1) >= self.min_pixels)
            if np.any(rev):
                for w in np.flatnonzero(rev):
                    w = int(w)
                    self._record_one(w)
                    self.pivot[w] = self.extreme[w]
                    self.extreme[w] = pixels[w]
                    self.extreme_mean[w] = pix_means[w]
                    self.extreme_time[w] = when
                    self.direction[w] = -self.direction[w]
                    self.dir_f[w] = float(self.direction[w])
                    if self.darker_below is not None:
                        self.piv_dark[w] = self.ext_dark[w]
                        self.ext_dark[w] = pix_dark[w]
                    else:
                        self.zero_pivot[w] = not np.any(self.pivot[w] != 0.0)
            cand = np.flatnonzero(has_dir & (~rev) & ((pix_means - self.extreme_mean) * self.direction > 0.0))
            if cand.size:
                fwd = (pixels[cand] - self.pivot[cand]) * self.dir_f[cand, None] >= self.threshold
                if self.darker_below is not None:
                    fwd &= self.piv_dark[cand] | pix_dark[cand]
                upd = cand[np.count_nonzero(fwd, axis=1) >= self.min_pixels]
                if upd.size:
                    self.extreme[upd] = pixels[upd]
                    self.extreme_mean[upd] = pix_means[upd]
                    if self.darker_below is not None:
                        self.ext_dark[upd] = pix_dark[upd]

    def finish_and_resolve(self, times):
        for w in np.flatnonzero(self.direction != 0):
            self._record_one(int(w))
        self.direction.fill(0)
        self.dir_f.fill(0.0)
        if not self.paired:
            return
        for w, swings in enumerate(self.swings):
            if not swings:
                continue
            kept = [False] * len(swings)
            for i, (when, direction, moved, size, _) in enumerate(swings):
                t_i = times[when]
                for k in range(i - 1, -1, -1):
                    other_when, other_direction, other_moved, _, _ = swings[k]
                    if t_i - times[other_when] > self.pair_window + 1e-9:
                        break
                    if other_direction == -direction and int(_POPCOUNT[moved & other_moved].sum()) >= self.area * size:
                        kept[i] = kept[k] = True
            self.ends[w] = [swing[0] for swing, keep in zip(swings, kept) if keep and swing[4]]


class _GeneralBatch:
    """Lockstep GeneralZig state machines across all K scan windows, caching (extreme - pivot) invariants."""

    def __init__(self, k, wh, ww, threshold=0.10, area=0.25):
        self.k, self.wh, self.ww, self.p = k, wh, ww, wh * ww
        self.threshold = np.float32(threshold)
        self.min_pixels = area * self.p
        self.pivot = None
        self.extreme = None
        self.piv_dark = None
        self.ext_dark = None
        self.forward = np.zeros((k, self.p), dtype=np.float32)
        self.rev_sign = np.zeros((k, self.p), dtype=np.float32)
        self.ch_fe = np.zeros((k, self.p), dtype=bool)
        self.can_reverse = np.zeros(k, dtype=bool)
        self.ext_dist = np.zeros(k, dtype=np.float32)
        self._d = np.empty((k, self.p), dtype=np.float32)
        self._b1 = np.empty((k, self.p), dtype=bool)
        self._b2 = np.empty((k, self.p), dtype=bool)
        self.has_extreme = np.zeros(k, dtype=bool)
        self.extreme_time = np.zeros(k, dtype=np.int64)
        self.ends = [[] for _ in range(k)]

    def _sync(self, rows):
        fwd = self.extreme[rows] - self.pivot[rows]
        self.forward[rows] = fwd
        self.rev_sign[rows] = np.where(fwd > 0.0, np.float32(-1.0), np.float32(1.0))
        af = np.abs(fwd)
        ch = (af >= self.threshold) & (self.piv_dark[rows] | self.ext_dark[rows])
        self.ch_fe[rows] = ch
        self.can_reverse[rows] = np.count_nonzero(ch, axis=1) >= self.min_pixels
        self.ext_dist[rows] = af.sum(axis=1)

    def push(self, when, windows_3d, pix_dark, motion=None):
        pixels = windows_3d.reshape(self.k, self.p)
        if self.pivot is None:
            self.pivot = pixels.copy()
            self.extreme = np.zeros_like(pixels)
            self.piv_dark = pix_dark.copy()
            self.ext_dark = np.zeros_like(pix_dark)
            return
        if motion is not None:
            self.pivot = _translated_batch(self.pivot.reshape(self.k, self.wh, self.ww), motion, windows_3d).reshape(self.k, self.p)
            np.less(self.pivot, np.float32(0.80), out=self.piv_dark)
            he = np.flatnonzero(self.has_extreme)
            if he.size:
                self.extreme[he] = _translated_batch(self.extreme[he].reshape(he.size, self.wh, self.ww), motion, windows_3d[he]).reshape(he.size, self.p)
                self.ext_dark[he] = self.extreme[he] < np.float32(0.80)
                self._sync(he)
        was_active = self.has_extreme.copy()
        idx0 = np.flatnonzero(~was_active)
        if idx0.size:
            p0, x0 = self.pivot[idx0], pixels[idx0]
            ch0 = np.count_nonzero((np.abs(x0 - p0) >= self.threshold) & (self.piv_dark[idx0] | pix_dark[idx0]), axis=1) >= self.min_pixels
            if np.any(ch0):
                h0 = idx0[ch0]
                self.has_extreme[h0] = True
                self.extreme[h0] = pixels[h0]
                self.ext_dark[h0] = pix_dark[h0]
                self.extreme_time[h0] = when
                self._sync(h0)
        if np.any(was_active):
            rev = np.zeros(self.k, dtype=bool)
            if np.any(was_active & self.can_reverse):
                np.subtract(pixels, self.extreme, out=self._d)
                np.multiply(self._d, self.rev_sign, out=self._d)
                np.greater_equal(self._d, self.threshold, out=self._b1)
                self._b1 &= self.ch_fe
                np.bitwise_or(self.ext_dark, pix_dark, out=self._b2)
                self._b1 &= self._b2
                rev = was_active & self.can_reverse & (np.count_nonzero(self._b1, axis=1) >= self.min_pixels)
            if np.any(rev):
                r_idx = np.flatnonzero(rev)
                for w in r_idx:
                    w = int(w)
                    self.ends[w].append(int(self.extreme_time[w]))
                    self.pivot[w] = self.extreme[w]
                    self.piv_dark[w] = self.ext_dark[w]
                    self.extreme[w] = pixels[w]
                    self.ext_dark[w] = pix_dark[w]
                    self.extreme_time[w] = when
                self._sync(r_idx)
            stay = was_active & (~rev)
            if np.any(stay):
                np.subtract(pixels, self.pivot, out=self._d)
                np.abs(self._d, out=self._d)
                upd = np.flatnonzero(stay & (self._d.sum(axis=1) > self.ext_dist))
                if upd.size:
                    self.extreme[upd] = pixels[upd]
                    self.ext_dark[upd] = pix_dark[upd]
                    self._sync(upd)

    def finish(self):
        for w in np.flatnonzero(self.has_extreme):
            self.ends[int(w)].append(int(self.extreme_time[int(w)]))


class _AreaBatch:
    """AreaTransitions across all K windows, using one per-frame 2D integral image when motion is None."""

    def __init__(self, wins, wh, ww, threshold=0.10, area=0.25, overlap=0.12):
        self.wins = wins
        self.wh, self.ww, self.p = wh, ww, wh * ww
        self.x0 = np.array([x for x, _ in wins], dtype=np.intp)
        self.y0 = np.array([y for _, y in wins], dtype=np.intp)
        self.x1, self.y1 = self.x0 + ww, self.y0 + wh
        self.threshold = threshold
        self.min_pixels = area * self.p
        self.min_overlap = overlap * self.p
        self.previous = None
        self.event_delta = [None] * len(wins)
        self.event_mask = [None] * len(wins)
        self.event_time = [None] * len(wins)
        self.chain = [False] * len(wins)
        self.ends = [[] for _ in wins]

    def _apply_event(self, k, when, delta, changed):
        ed = self.event_delta[k]
        if ed is not None:
            reversal = changed & self.event_mask[k] & (delta * ed < 0)
            if int(np.count_nonzero(reversal)) >= self.min_overlap:
                if not self.chain[k]:
                    self.ends[k].append(self.event_time[k])
                self.ends[k].append(when)
                self.chain[k] = True
            else:
                self.chain[k] = False
        self.event_delta[k] = delta.copy()
        self.event_mask[k] = changed.copy()
        self.event_time[k] = when

    def push(self, when, frame_luma, windows_3d, sat, motion=None):
        if self.previous is None:
            self.previous = frame_luma.copy()
            return
        if motion is None:
            delta_full = frame_luma - self.previous
            changed_full = (np.abs(delta_full) >= self.threshold) & (np.minimum(frame_luma, self.previous) < 0.80)
            counts = _integral_counts(changed_full, sat, self.x0, self.y0, self.x1, self.y1)
            for k in np.flatnonzero(counts >= self.min_pixels):
                k = int(k)
                x, y = self.wins[k]
                self._apply_event(k, when, delta_full[y:y + self.wh, x:x + self.ww], changed_full[y:y + self.wh, x:x + self.ww])
        else:
            empty = np.zeros((self.wh, self.ww), dtype=np.float32)
            for k, (x, y) in enumerate(self.wins):
                image = windows_3d[k]
                old = translated(self.previous[y:y + self.wh, x:x + self.ww], motion, image)
                if self.event_delta[k] is not None:
                    self.event_delta[k] = translated(self.event_delta[k], motion, empty)
                    self.event_mask[k] = translated(self.event_mask[k].astype(np.float32), motion, empty) > 0.5
                delta = image - old
                changed = (np.abs(delta) >= self.threshold) & (np.minimum(image, old) < 0.80)
                if int(np.count_nonzero(changed)) >= self.min_pixels:
                    self._apply_event(k, when, delta, changed)
        self.previous = frame_luma.copy()


def busiest_second(ends, tolerance=1e-5):
    best, at, j = 0, None, 0
    ends = sorted(ends)
    for i in range(len(ends)):
        while ends[i] - ends[j] >= 1.0 - tolerance:
            j += 1
        if i - j + 1 > best:
            best, at = i - j + 1, round(ends[j], 3)
    return best, at


def screen_video(video_path, width=192, start=None, end=None, json_out=None):
    """Screen `video_path` for WCAG 2.3.1 general and red flashes. Returns the result dict."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe are required on PATH")
    video_path = str(video_path)
    w0, h0, fps, order = probe_order(ffprobe, video_path)
    # a stated field order answers it; only an unstated one ("unknown", or none) has its first 30 frames read
    fields = True if order in ("tt", "bb", "tb", "bt") else False if order == "progressive" else interlaced(ffprobe, video_path)
    W = width - width % 2
    H = max(6, int(round(W * h0 / w0 / 2.0)) * 2)
    field_filter = "separatefields," if fields else ""
    vf = (
        field_filter + f"split=2[area][point];[area]scale={W}:{H}:flags=area[a];"
        f"[point]scale={W}:{H}:flags=neighbor[b];[a][b]hstack=inputs=2,format=rgb24"
    )
    frames = Frames(ffmpeg, video_path, vf, W * 2 * H * 3, start, end)
    # WCAG 2.3.1's area is a 10-degree field: 341 x 256 px of content shown on a 1024 x 768 screen at a typical
    # distance. The film is fitted to that screen with its aspect kept, so for 16:9 the field is a third of the width
    # by 4/9 of the height (a third each way counted Stet's re-run button as a quarter of the field).
    fit = min(1024.0 / w0, 768.0 / h0)
    fw, fh = W * 341.0 / (fit * w0), H * 256.0 / (fit * h0)          # the field in scan pixels, before the frame clips it
    ww = max(2, min(W, int(round(fw))))
    wh = max(2, min(H, int(round(fh))))
    # WCAG's quarter is of the field: where the frame is narrower than the field (an ultrawide film), the window is the
    # whole frame and a quarter of the field is a larger share of it (a patch over 19% of the field had been flagged)
    area = min(1.0, 0.25 * (fw * fh) / (ww * wh))
    xs = sorted({x for x in range(0, W - ww + 1, max(1, W // 6))} | {W - ww})
    ys = sorted({y for y in range(0, H - wh + 1, max(1, H // 6))} | {H - wh})
    wins = [(x + mode * W, y) for mode in range(2) for y in ys for x in xs]
    kw = len(wins)
    # Vectorized across all 50 windows at once instead of 250 per-window .push() dispatches per frame, with a 2D int32
    # integral image skipping idle windows in AreaTransitions and RedZig while keeping every detector's exact state.
    y_wins = np.empty((kw, wh, ww), dtype=np.float32)
    r_wins = np.empty((kw, wh, ww), dtype=np.float32)
    sat = np.zeros((H + 1, W * 2 + 1), dtype=np.int32)
    rx0 = np.array([x for x, _ in wins], dtype=np.intp)
    ry0 = np.array([y for _, y in wins], dtype=np.intp)
    rx1, ry1 = rx0 + ww, ry0 + wh
    n = 0
    classic_zigs = _CoherentBatch(kw, wh, ww, area=area)
    candidate_zigs = _CoherentBatch(kw, wh, ww, area=area, paired=False)
    red_zigs = _CoherentBatch(kw, wh, ww, threshold=RED_THRESHOLD, area=area, darker_below=None, ambiguous_patterns=False, paired=True)
    general_zigs = _GeneralBatch(kw, wh, ww)
    area_zigs = _AreaBatch(wins, wh, ww)
    previous_luma = None
    prev_buf = None
    pix_dark = np.empty((kw, wh * ww), dtype=bool)
    for buf in frames:
        if buf == prev_buf:
            n += 1
            continue
        prev_buf = buf
        raw = np.frombuffer(buf, np.uint8).reshape(H, W * 2, 3)
        lin = srgb_to_linear(raw)
        Y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
        motion = unique_translation(previous_luma, Y[:, :W]) if previous_luma is not None else None
        previous_luma = Y[:, :W].copy()
        Yf = np.asarray(Y, dtype=np.float32)
        for k, (x, y) in enumerate(wins):
            y_wins[k] = Yf[y:y + wh, x:x + ww]
        y_flat = y_wins.reshape(kw, wh * ww)
        pix_means = y_flat.mean(axis=1).astype(np.float64)
        np.less(y_flat, np.float32(0.80), out=pix_dark)
        classic_zigs.push(n, y_wins, pix_means=pix_means, pix_dark=pix_dark)
        candidate_zigs.push(n, y_wins, pix_means=pix_means, pix_dark=pix_dark, motion=motion)
        general_zigs.push(n, y_wins, pix_dark=pix_dark, motion=motion)
        area_zigs.push(n, Yf, y_wins, sat, motion)
        red_idle = n > 0 and bool(np.all((red_zigs.direction == 0) & red_zigs.zero_pivot))
        if red_idle and int(np.count_nonzero((raw[..., 0] >= RED_FLOOR) & (raw[..., 0] > raw[..., 1]) & (raw[..., 0] > raw[..., 2]))) < red_zigs.min_pixels:
            n += 1
            continue
        red = red_amount(lin)
        if not (red_idle and (int(np.count_nonzero(red >= RED_THRESHOLD)) < red_zigs.min_pixels or bool(np.all(_integral_counts(red >= RED_THRESHOLD, sat, rx0, ry0, rx1, ry1) < red_zigs.min_pixels)))):
            for k, (x, y) in enumerate(wins):
                r_wins[k] = red[y:y + wh, x:x + ww]
            red_zigs.push(n, r_wins)
        n += 1
    offset = start or 0.0
    if n == 0:
        raise RuntimeError(f"ffmpeg decoded 0 frames from {video_path}")
    times = [t + offset for t in frames.times(n)]
    if n == 1:
        res = {
            "video": video_path,
            "frames": 1,
            "fps": fps,
            "frame_timing": "constant",
            "duration_s": round(1.0 / max(fps, 1.0), 3),
            "screened_as": "fields of an interlaced picture" if fields else "frames",
            "scan_size": [W, H],
            "windows": len(wins),
            "busiest_general": {"transitions_in_1s": 0, "at_s": None, "window": [0, 0, ww, wh]},
            "busiest_classic": {"transitions_in_1s": 0, "at_s": None, "window": [0, 0, ww, wh]},
            "busiest_red": {"transitions_in_1s": 0, "at_s": None, "window": [0, 0, ww, wh]},
            "flagged": [],
            "classic_flagged": [],
            "verdict": "no candidate flash sequences",
        }
        if json_out:
            Path(json_out).parent.mkdir(parents=True, exist_ok=True)
            Path(json_out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
        return res
    clock, _step = timing(times)
    classic_zigs.finish_and_resolve(times)
    candidate_zigs.finish_and_resolve(times)
    red_zigs.finish_and_resolve(times)
    general_zigs.finish()
    rows, flagged = [], []
    for k, (x, y) in enumerate(wins):
        classic = busiest_second([times[index] for index in classic_zigs.ends[k]], 1e-9)
        patterns = [busiest_second([times[index] for index in ends[k]], 1e-9) for ends in (general_zigs.ends, area_zigs.ends)]
        if candidate_zigs.ambiguous_ends[k]:
            candidate_ends = candidate_zigs.ends[k] + candidate_zigs.ambiguous_ends[k]
            patterns.append(busiest_second([times[index] for index in candidate_ends], 1e-9))
        coherent = busiest_second([times[index] for index in classic_zigs.coherent_ends[k]], 1e-9)
        patterns.append(coherent)
        pattern = max(patterns, key=lambda result: result[0])
        g = max((classic, pattern), key=lambda result: result[0])
        r = busiest_second([times[index] for index in red_zigs.ends[k]], 1e-9)
        red_coherent = busiest_second([times[index] for index in red_zigs.coherent_ends[k]], 1e-9)
        row = {
            "window": [x % W, y, ww, wh],
            "sampling": "area" if x < W else "point",
            "general_max_per_s": g[0],
            "general_at_s": g[1],
            "classic_max_per_s": classic[0],
            "classic_at_s": classic[1],
            "pattern_max_per_s": pattern[0],
            "pattern_at_s": pattern[1],
            "red_max_per_s": r[0],
            "red_at_s": r[1],
            "coherent_max_per_s": coherent[0],
            "coherent_at_s": coherent[1],
            "red_coherent_max_per_s": red_coherent[0],
            "red_coherent_at_s": red_coherent[1],
        }
        rows.append(row)
        if g[0] > 6 or r[0] > 6 or red_coherent[0] > 6:
            flagged.append(row)
    area_rows = [r for r in rows if r["sampling"] == "area"]
    gb = max(rows, key=lambda r: r["general_max_per_s"])
    cb = max(area_rows, key=lambda r: r["classic_max_per_s"])
    rb = max(area_rows, key=lambda r: r["red_max_per_s"])
    # WCAG 2.3.1's verdict rests on the paired, same-direction general and red detectors over area-averaged pixels.
    # Point-sampled windows alias fine detail (a dot grid zoomed at 192 px), and the pattern detectors count pans and
    # slides; both are reported as motion and patterns, not as WCAG findings.
    classic_flagged = [r for r in area_rows if r["classic_max_per_s"] > 6 or r["red_max_per_s"] > 6]
    duration = frames.end() + offset - times[0]
    res = {
        "video": video_path,
        "frames": n,
        "fps": fps,
        "frame_timing": clock,
        "duration_s": round(duration, 3),
        "screened_as": "fields of an interlaced picture" if fields else "frames",
        "scan_size": [W, H],
        "windows": len(wins),
        "busiest_general": {"transitions_in_1s": gb["general_max_per_s"], "at_s": gb["general_at_s"], "window": gb["window"]},
        "busiest_classic": {"transitions_in_1s": cb["classic_max_per_s"], "at_s": cb["classic_at_s"], "window": cb["window"]},
        "busiest_red": {"transitions_in_1s": rb["red_max_per_s"], "at_s": rb["red_at_s"], "window": rb["window"]},
        "flagged": flagged,
        "classic_flagged": classic_flagged,
        "verdict": "FLAGGED" if classic_flagged else "motion or patterns to look at, not WCAG 2.3.1 flashes" if flagged else "no candidate flash sequences",
    }
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video")
    ap.add_argument("--width", type=int, default=192)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    a = ap.parse_args(argv)
    res = screen_video(a.video, width=a.width, start=a.start, end=a.end, json_out=a.json_out)
    g, r = res["busiest_general"], res["busiest_red"]
    print(
        f"{Path(a.video).name}: {res['frames']} frames at {res['fps']:g} fps; busiest second: "
        f"general {g['transitions_in_1s']} transitions (at {g['at_s']} s), red {r['transitions_in_1s']} (at {r['at_s']} s); {res['verdict']}"
    )
    return 1 if res["classic_flagged"] else 0


if __name__ == "__main__":
    import utf8  # noqa: F401
    sys.exit(main())
