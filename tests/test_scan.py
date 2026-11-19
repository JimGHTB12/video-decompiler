#!/usr/bin/env python3
"""tools/scan.py, the scan vd export runs, on small films made here with known answers, at 30 and at 60 frames a second:
a moving film with a one-frame flash at a known frame (that pop is found and no other), a moving film that freezes for
0.8 s at a known time (that hold is found, its times right to a frame), and a film that keeps moving (nothing found).
Also: the stretches vd pack picks hold a planted burst of motion, and the level is read and judged. Needs ffmpeg.

  python tests/test_scan.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import scan  # noqa: E402

W, H = 320, 180


def texture(seed=3):
    """A soft random picture four times the frame's width, so a window sliding across it is steady motion."""
    from PIL import Image
    rng = np.random.default_rng(seed)
    t = Image.fromarray(rng.integers(0, 256, (H // 20, W // 5)).astype(np.uint8))
    # soft: a slide of 3 px changes a frame by a few levels, as a camera move does, so a flash stands far above it
    return np.asarray(t.resize((W * 4, H), Image.BICUBIC))


def film(path, fps, seconds, clock=lambda f: f, speed=3, flash=None, sound_db=None):
    """Frame f shows the texture slid by speed * clock(f) px at 30 a second (the same pixels a second at any rate); frame `flash` is white. A sine under it at `sound_db` dBFS."""
    tex = texture()
    n = int(round(seconds * fps))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    if sound_db is not None:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds},volume={sound_db}dB", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", "14", "-g", "1000", "-pix_fmt", "yuv420p", str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n):
        x = int(round(speed * 30 / fps * clock(f)))             # the same speed in pixels a second at any rate
        assert x <= tex.shape[1] - W, "the slide stays on the texture: a wrap is a jump"
        fr = np.full((H, W), 255, np.uint8) if f == flash else tex[:, x:x + W]
        p.stdin.write(np.ascontiguousarray(fr).tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return path


def frozen(at, frames):
    """A clock that stops at frame `at` for `frames` frames and then goes on from where it stopped (no jump when it starts
    again, so the end of the hold is no pop)."""
    return lambda f: f if f < at else at if f < at + frames else f - frames + 1


def test_a_flash_is_the_one_pop():
    for fps in (30, 60):
        with tempfile.TemporaryDirectory() as tmp:
            at = int(1.4 * fps)
            text, fixes = scan.scan(film(Path(tmp) / "flash.mp4", fps, 3, flash=at), to=Path(tmp) / "scan.txt")
            d, d2 = scan.changes(Path(tmp) / "flash.mp4", two=True)
            assert scan.pops(d, d2) == [(at, "flash")], f"{fps}: only the flash at frame {at}: {scan.pops(d, d2)}\n{text}"
            assert [p for p in scan.pops(d) if p[1] == "jump"] == [], "pops.py's rule alone does not see a one-frame flash, which is why the second rule is there"
            assert len(fixes) == 1 and f"{at / fps:.2f} s (frame {at}" in fixes[0], fixes
            assert "holds: still" in text and "none of 0.5 s" in text, text
            assert (Path(tmp) / "scan.txt").read_text(encoding="utf-8").strip() == text.strip()
            assert scan.rate(Path(tmp) / "flash.mp4") == fps


def test_a_flash_on_the_films_second_or_next_to_last_frame_is_found():
    # a review's finding: the rule began two frames in and stopped two short, and its one test planted its flash mid-film.
    # A film's opening and closing frames are the ones everybody sees
    for at in (1, 88):                                           # of 90 frames: the first and the last a flash can be on
        with tempfile.TemporaryDirectory() as tmp:
            text, fixes = scan.scan(film(Path(tmp) / "edge.mp4", 30, 3, flash=at))
            d, d2 = scan.changes(Path(tmp) / "edge.mp4", two=True)
            assert scan.pops(d, d2) == [(at, "flash")], f"only the flash at frame {at}: {scan.pops(d, d2)}\n{text}"
            assert len(fixes) == 1 and f"(frame {at}" in fixes[0], fixes
    # and by the rule alone, on numbers: a jump onto the last frame, and one off the first
    quiet = [0.3] * 10
    assert scan.pops(np.array(quiet + [9.0])) == [(11, "jump")] and scan.pops(np.array([9.0] + quiet)) == [(1, "jump")]
    assert scan.pops(np.array(quiet)) == [], "a film that only moves has none"


def test_a_freeze_is_the_one_hold_in_the_films_own_seconds():
    for fps in (30, 60):
        with tempfile.TemporaryDirectory() as tmp:
            at, n = int(1.5 * fps), int(round(0.8 * fps))       # frames at .. at + n - 1 show one picture: 1.5 s to 2.3 s
            text, fixes = scan.scan(film(Path(tmp) / "freeze.mp4", fps, 4, clock=frozen(at, n)))
            d = scan.changes(Path(tmp) / "freeze.mp4")
            hs = scan.holds(d, fps)
            assert len(hs) == 1, f"{fps}: one hold: {hs}\n{text}"
            (a, b), = hs
            assert abs(a - 1.5) <= 2 / fps and abs(b - 2.3) <= 2 / fps, f"{fps}: 1.5 to 2.3 s to a frame or two: {a, b}"
            assert "pops: none" in text and "1.50 to   2.30 s" in text and "long holds total 0.80 s" in text, text
            assert fixes == [] and "check:" not in text, f"a hold under 1 s is listed, not flagged: {fixes}"
            # one over a second is asked about, not called a fault: studio films hold still on purpose
            text, fixes = scan.scan(film(Path(tmp) / "long.mp4", fps, 4, clock=frozen(at, int(1.3 * fps))))
            checks = [l for l in text.splitlines() if l.startswith("check:")]
            assert fixes == [] and "fix before anyone watches" not in text, (fixes, text)
            assert len(checks) == 1 and "stands still from 1.50 to 2.80 s" in checks[0] and checks[0].endswith(
                "keep it only if you chose it: a chosen hold creeps or breathes"), (checks, text)


def test_a_film_that_keeps_moving_has_nothing_to_fix():
    for fps in (30, 60):
        with tempfile.TemporaryDirectory() as tmp:
            text, fixes = scan.scan(film(Path(tmp) / "moving.mp4", fps, 3))
            assert fixes == [] and "pops: none" in text and "none of 0.5 s" in text and "no sound" in text, text


def test_the_level_is_read_and_judged():
    with tempfile.TemporaryDirectory() as tmp:
        text, fixes = scan.scan(film(Path(tmp) / "quiet.mp4", 30, 3, sound_db=-40))
        line = next(l for l in text.splitlines() if "loudness" in l)
        assert "LUFS integrated" in line and "LU under -15 (allowed 1 either way)" in line, line
        assert fixes == [], "the level is said, not a fix"


def test_the_stretches_picked_hold_a_burst_of_motion():
    # still for 4 s but for one second of fast motion from 2.5 s: that second is the first stretch picked
    for fps in (30, 60):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = int(2.5 * fps), int(3.5 * fps)
            clock = lambda f: 0.15 * f if f < a else 0.15 * a + 4 * (f - a) if f < b else 0.15 * a + 4 * (b - a) + 0.15 * (f - b)
            clip = film(Path(tmp) / "burst.mp4", fps, 6, clock=clock)
            got = scan.windows(clip, fps, 3)
            ranked = scan.windows(clip, fps, 5, ranked=True)
            assert len(got) == 3 and any(abs(t - 2.5) <= 2 / fps for t in got), f"{fps}: the burst at 2.5 s is picked: {got}"
            assert abs(ranked[0] - 2.5) <= 2 / fps and sorted(ranked[:3]) == got, f"{fps}: ranked puts the burst first: {ranked}"
            assert got == sorted(got) and all(y - x >= 1.0 - 1e-9 for x, y in zip(got, got[1:])), f"in time order, not overlapping: {got}"


def test_a_film_whose_frames_are_not_evenly_spaced_is_told_its_seconds_can_be_off():
    # a review's risk: every time in a scan is a frame number over one rate, so on a phone or screen recording the
    # seconds named a moment the film does not show there, and nothing said so
    with tempfile.TemporaryDirectory() as tmp:
        even = film(Path(tmp) / "even.mp4", 30, 3)
        text, _ = scan.scan(even)
        assert "timing:" not in text, text
        odd = Path(tmp) / "odd.mp4"
        # two of every six frames kept after the first half second, each at its own time: the gaps are not all one length
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(even), "-vf", "select='lt(n,15)+lt(mod(n,6),2)'", "-fps_mode", "vfr",
                        "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(odd)], check=True)
        assert scan.uneven(odd, scan.rate(odd)), "the test's own film must be uneven"
        text, _ = scan.scan(odd)
        line = next((l for l in text.splitlines() if l.strip().startswith("timing:")), "")
        assert "not evenly spaced" in line and "frame numbers" in line and "-fps_mode cfr" in line, text


def test_the_changes_and_the_one_probe_are_the_old_ones():
    # C7: changes subtracts in uint8 and sums whole numbers, and scan asks ffprobe once for the rate, the average rate,
    # the frame count and the sound; the changes must be the int16 means to the bit (including frames 0 and 255 apart),
    # and a file with no picture is refused in the same words rate() uses
    rng = np.random.default_rng(9)
    frames = [rng.integers(0, 256, (scan.H, scan.W)).astype(np.uint8) for _ in range(6)]
    frames += [np.zeros((scan.H, scan.W), np.uint8), np.full((scan.H, scan.W), 255, np.uint8), np.zeros((scan.H, scan.W), np.uint8)]
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "exact.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{scan.W}x{scan.H}", "-r", "30", "-i", "-",
                        "-c:v", "ffv1", "-pix_fmt", "gray", str(clip)], input=b"".join(f.tobytes() for f in frames), check=True)
        d, d2 = scan.changes(clip, two=True)
        i16 = [f.astype(np.int16) for f in frames]
        assert np.array_equal(d, [float(np.abs(i16[k + 1] - i16[k]).mean()) for k in range(len(i16) - 1)]), d
        assert np.array_equal(d2, [float(np.abs(i16[k + 2] - i16[k]).mean()) for k in range(len(i16) - 2)]), d2
        assert scan.probe(clip)[:2] == (scan.rate(clip), scan.uneven(clip, scan.rate(clip))) and scan.probe(clip)[3] == scan.has_sound(clip)
        sound = Path(tmp) / "sound.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", str(sound)], check=True)
        said = []
        for read in (scan.rate, scan.probe):
            try:
                read(sound)
            except SystemExit as e:
                said.append(str(e))
        assert len(said) == 2 and said[0] == said[1] and "no video stream" in said[0], said


if __name__ == "__main__":
    import utf8  # noqa: F401
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
