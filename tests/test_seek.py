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


def grab_many(video, seeks, per_run=24):
    """grab() of each time in `seeks`, up to `per_run` in one ffmpeg: each seek its own -ss before its own -i of the
    video, mapped to a one-frame raw output of its own, so each is the same independent seek grab() makes (120 ffmpeg
    starts a rate had been most of this file's time). The oracle stays apart from the tools it checks."""
    got = []
    with tempfile.TemporaryDirectory() as tmp:
        for start in range(0, len(seeks), per_run):
            part = seeks[start:start + per_run]
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            for ss in part:
                cmd += ["-ss", f"{ss:.6f}", "-i", video]
            outs = [Path(tmp) / f"{start + k}.gray" for k in range(len(part))]
            for k, out in enumerate(outs):
                cmd += ["-map", f"{k}:v:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", str(out)]
            p = subprocess.run(cmd, capture_output=True)
            assert p.returncode == 0 and not p.stderr.strip(), (p.returncode, p.stderr[-400:])
            for out in outs:
                raw = out.read_bytes()
                assert len(raw) == W * H, (out.name, len(raw))
                got.append(index_of(np.frombuffer(raw, np.uint8).reshape(H, W)))
    return got


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
        landed = grab_many(video, [film_diff.seek_to(times, f / fps)[0] for f in range(120)])
        wrong = [f for f in range(120) if landed[f] != f]
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
        import measure_film
        win = [index_of(np.asarray(im.convert("L"))) for im in measure_film.window_frames(video, 40, 45)]
        assert win == list(range(40, 46)), f"measure_film.window_frames at {fps} fps: {win}"
        import decode
        import sheet
        from PIL import Image
        from unittest.mock import patch
        real_pics, sheet_cmds = decode.pictures, []
        sh = tmp / f"sheet{fps}.jpg"
        with patch.object(decode, "pictures", lambda cmd, *a, **k: (sheet_cmds.append(list(cmd)), real_pics(cmd, *a, **k))[1]), \
                patch.object(sys, "argv", ["sheet.py", str(video), "-o", str(sh), "--native", "--from", f"{43 / fps:.6f}",
                                           "--to", f"{49 / fps:.6f}", "--cols", "6", "--rows", "2", "--width", str(W)]):
            sheet.main()
        assert sheet_cmds and "-ss" in sheet_cmds[-1] and "-frames:v" in sheet_cmds[-1], f"sheet.py --native seeks and stops: {sheet_cmds}"
        im = np.asarray(Image.open(sh).convert("L"))
        tiles = [index_of(im[sheet.STRIP:sheet.STRIP + H, k * W:(k + 1) * W]) for k in range(6)]
        assert tiles == list(range(43, 49)), f"sheet.py --native at {fps} fps: {tiles}"


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
    import measure_film
    from unittest.mock import patch
    real_run, cmds = measure_film.subprocess.run, []
    with patch.object(measure_film.subprocess, "run", lambda cmd, **kw: (cmds.append(list(cmd)), real_run(cmd, **kw))[1]):
        win = [index_of(np.asarray(im.convert("L"))) for im in measure_film.window_frames(vfr, 28, 34)]
    assert win == list(range(28, 35)), f"measure_film.window_frames across a VFR rate step: {win}"
    assert cmds and "-ss" in cmds[-1] and "-frames:v" in cmds[-1], f"window_frames seeks and stops: {cmds}"
    import decode
    import sheet
    from PIL import Image
    real_pics, sheet_cmds = decode.pictures, []
    sh = tmp / "sheet_vfr.jpg"
    with patch.object(decode, "pictures", lambda cmd, *a, **k: (sheet_cmds.append(list(cmd)), real_pics(cmd, *a, **k))[1]), \
            patch.object(sys, "argv", ["sheet.py", str(vfr), "-o", str(sh), "--native", "--from", f"{28 / 30:.6f}",
                                       "--to", f"{1 + 5 / 60:.6f}", "--cols", "7", "--rows", "2", "--width", str(W)]):
        sheet.main()
    assert sheet_cmds and "-ss" in sheet_cmds[-1] and "-frames:v" in sheet_cmds[-1], f"sheet.py --native VFR seeks and stops: {sheet_cmds}"
    im = np.asarray(Image.open(sh).convert("L"))
    tiles = [index_of(im[sheet.STRIP:sheet.STRIP + H, k * W:(k + 1) * W]) for k in range(7)]
    assert tiles == list(range(28, 35)), f"sheet.py --native across a VFR rate step: {tiles}"
    black = tmp / "black.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c=black:s={W}x{H}:r=45:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black)], check=True)
    diff = film_diff.run(str(vfr), str(black), 0.0, None, tmp / "diff")
    m = next(row for row in diff["worst"] if row["frame"] == 58)
    panel = np.asarray(Image.open(m["sheet"]).crop((0, 26, 960, 26 + 540)).convert("L"))
    assert index_of(panel) == 47, f"VFR worst sheet at {m['t_in_clip']} s showed frame #{index_of(panel)}, not #47"


def test_worst_stills_are_the_frames_scored(tmp):
    # a review's finding: film_diff.run fetched each worst moment's still by the nearest packet time, while the scores
    # came through ffmpeg's fps filter after a seek; on 30-then-60 fps the still was the next frame (window [1.37, 2.37]:
    # scored #68, still #69; from 0: scored #27, still #28). Every still is checked against the frame stream() scored.
    from unittest.mock import patch
    vfr = numbered(tmp / "vfr50.mp4", 60, n=150, pts="if(lt(N,30),N/30,1+(N-30)/60)")
    black = tmp / "black.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c=black:s={W}x{H}:r=50:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black)], check=True)
    fps = film_diff.probe(vfr)["fps"]
    times = film_diff.clock(vfr, fps)
    for start, end, picks in ((1.37, 2.37, [14, 38]), (1.01, 2.01, [14]), (0.0, None, [27, 46])):
        seconds = (end - start) if end else film_diff.probe(vfr)["duration"]
        scored = [index_of(f) for f in film_diff.stream(vfr, start, seconds, fps, times)]
        every = sorted(set(picks + list(range(0, len(scored), 5))))
        stills = {}
        real_sheet = film_diff.sheet
        with patch.object(film_diff, "worst_frames", lambda s, **k: every), \
                patch.object(film_diff, "sheet", lambda a, b, box: (stills.setdefault(len(stills), a), real_sheet(a, b, box))[1]), \
                patch.object(film_diff, "colour_matrix", lambda p: (_ for _ in ()).throw(AssertionError("C5b: run reads the matrix from its own probe"))):
            film_diff.run(str(vfr), str(black), start, end, tmp / f"d{start}")
        got = {t: index_of(np.asarray(stills[i].convert("L"))) for i, t in enumerate(every)}
        bad = {t: (scored[t], got[t]) for t in every if got[t] != scored[t]}
        assert not bad, f"window {start}..{end}: (scored, still) differ at {bad}"


def test_the_box_means_and_ssim_are_the_summed_area_ones_to_the_bit(tmp):
    # C1: blur8 is OpenCV's box filter, read pairs as uint8, and the cells sum whole numbers; each must give exactly the
    # numbers the summed-area and float64 versions gave, so scores, worst frames and cuts cannot move. Checked on
    # random frames and at the edges (all black, all white, one level apart), with products as large as they get
    def summed(x):
        pad = np.pad(x, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return (pad[8:, 8:] - pad[:-8, 8:] - pad[8:, :-8] + pad[:-8, :-8]) / 64.0

    def ssim_summed(a, b):
        a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        ma, mb = summed(a), summed(b)
        va, vb = summed(a * a) - ma * ma, summed(b * b) - mb * mb
        cov = summed(a * b) - ma * mb
        return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    rng = np.random.default_rng(11)
    shape = (film_diff.H, film_diff.W)
    pairs = [(np.zeros(shape), np.zeros(shape)), (np.full(shape, 255), np.full(shape, 255)), (np.full(shape, 255), np.full(shape, 254)),
             (np.zeros(shape), np.full(shape, 255))] + [(rng.integers(0, 256, shape), rng.integers(0, 256, shape)) for _ in range(6)]
    for a, b in pairs:
        a, b = a.astype(np.uint8), b.astype(np.uint8)
        for x in (a, a.astype(np.float64) ** 2, a.astype(np.float64) * b):
            assert np.array_equal(film_diff.blur8(x), summed(np.asarray(x, np.float64))), "blur8"
        assert np.array_equal(film_diff.ssim_map(a, b), ssim_summed(a, b)), "ssim_map"
        assert np.array_equal(film_diff.cells(a), film_diff.cells(a.astype(np.float64))), "cells"


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


def test_a_reader_closed_early_lets_go_of_the_film_through_a_launcher(tmp):
    # broke on the hosted Windows runners (2 runs in 5): their ffmpeg is Chocolatey's launcher, which starts the real
    # one. Closing film_diff.stream after one frame killed the launcher at once and left the real ffmpeg holding the
    # film, so the test's folder could not be removed (a council's finding). space.frames did the same; decode.pictures
    # already waited for ffmpeg. Here `ffmpeg` is run through a launcher of that kind, and the film must be deletable the moment each reader
    # is closed.
    import subprocess as sp
    import time
    from unittest.mock import patch
    import decode
    import space
    launcher = tmp / "launcher.py"
    launcher.write_text("import subprocess, sys\nsys.exit(subprocess.call(sys.argv[1:]))\n", encoding="utf-8")
    real = sp.Popen

    def through_launcher(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and Path(str(cmd[0])).stem.lower() == "ffmpeg":
            cmd = [sys.executable, str(launcher), *map(str, cmd)]
        return real(cmd, *a, **k)
    readers = {
        "film_diff.stream": lambda v: film_diff.stream(str(v), 0.0, 1.0, 30.0),
        "decode.pictures": lambda v: decode.pictures(["ffmpeg", "-v", "error", "-i", str(v), "-f", "rawvideo", "-pix_fmt", "gray", "-"], W * H, "a test"),
        "space.frames": lambda v: space.frames(str(v), 30),
    }
    held = []
    for name, open_reader in readers.items():
        video = numbered(tmp / f"{name}.mp4", 30, n=90)
        with patch.object(sp, "Popen", through_launcher):
            frames = open_reader(video)
            next(frames)
            frames.close()
        try:
            os.unlink(video)
        except PermissionError:
            held.append(name)
            removed_later = time.monotonic() + 10
            while os.path.exists(video) and time.monotonic() < removed_later:
                try:
                    os.unlink(video)
                except PermissionError:
                    time.sleep(0.1)
    assert not held, f"closed after one frame, still holding the film: {held}"


def test_a_raw_stream_is_read_from_the_start(tmp):
    # an R2 review's finding: a raw H.264 stream decodes but has no packet times and no seek index; the tools that seek
    # to frame N handed over nothing (sheet.py --native: "0 pictures of the 12"; window_frames: []). Each tool's frames are
    # named by the numbers in the pictures and checked against a plain decode from the start.
    import awkward
    import lean
    import measure
    import measure_film
    import pack
    raw, mp4 = awkward.raw_h264(tmp), awkward.numbered(tmp)
    shown = awkward.shown(raw)
    assert film_diff.packet_clock(raw)[1] is False and film_diff.packet_clock(mp4)[1] is True
    for a, b in ((0, 4), (28, 34)):
        got = [awkward.number(np.asarray(im)) for im in measure_film.window_frames(raw, a, b)]
        assert got == shown[a:b + 1], f"window_frames {a}..{b} on a raw stream: {got}"
    # times on a raw stream are its estimated clock (ffmpeg reads it at 25 a second): frame f is the f-th picture shown
    clock = film_diff.clock(raw)
    at = [0.0, 0.5, 1.0]
    got = [awkward.number(im) for im in measure.grabs(raw, at)]
    assert got == [shown[film_diff.seek_to(clock, t)[1]] for t in at], f"measure.grabs on a raw stream: {got}"
    tiles = pack.tiles(raw, 1.0, 0.5)
    got = [awkward.number(np.asarray(im)) for _, im in tiles]
    assert got and got == [shown[int(np.searchsorted(clock, t + 1e-6, side="right")) - 1] for t, _ in tiles], f"pack.tiles on a raw stream: {got}"
    assert lean.join_report(raw, [30]) == lean.join_report(mp4, [30]), (lean.join_report(raw, [30]), lean.join_report(mp4, [30]))
    for start, end in (("0", "0.2"), ("1", "1.2")):
        said = subprocess.run([sys.executable, str(TOOLS / "sheet.py"), str(raw), "--native", "--from", start, "--to", end, "--width", "64",
                               "-o", str(Path(tmp) / f"s{start}.jpg")], capture_output=True, text=True)
        assert said.returncode == 0 and " frames -> 1 sheet" in said.stdout, (start, said.stdout, said.stderr)


def test_preroll_is_counted_as_a_decode_counts_it(tmp):
    # an R2 review's finding: on a file with packets before 0 (preroll a decode never shows), a seek by packet number
    # landed three pictures early, and window_frames' caller, which counts the pictures a decode shows, stamped them
    # with its own numbers. Every pick is checked against a plain decode from the start, not against packet times.
    from unittest.mock import patch
    import awkward
    import measure_film
    import pack
    import sheet
    pre = awkward.preroll(tmp)
    seen = awkward.shown_at(pre)
    assert film_diff.packet_clock(pre)[1] is False, "a clock with preroll is not one to seek by"
    shown = [k for _, k in seen]
    got = [awkward.number(np.asarray(im)) for im in measure_film.window_frames(pre, 28, 34)]
    assert got == shown[28:35], f"window_frames 28..34 counts pictures as a decode shows them: {got}, not {shown[28:35]}"
    for start, end in ((0.0, 0.2), (1.0, 1.2)):
        tiles = []
        with patch.object(sheet, "board", lambda ts, cols, out: (tiles.extend(ts), Path(out).write_bytes(b""))):
            sheet.native_stretch(pre, Path(tmp) / "pre.jpg", start, end, width=awkward.W)
        got = [awkward.number(np.asarray(t)[sheet.STRIP:]) for t in tiles]
        want = [k for t, k in seen if start - 1e-6 <= t < end - 1e-6]
        assert got == want, f"sheet --native {start}..{end} on preroll: {got}, not {want}"
    tiles = pack.tiles(pre, 1.0, 0.5)
    got = [awkward.number(np.asarray(im)) for _, im in tiles]
    want = [[k for s, k in seen if s <= t + 1e-6][-1] for t, _ in tiles]
    assert got and got == want, f"pack.tiles on preroll: {got}, not {want}"


def main():
    for t in (test_zero_rate_is_not_a_crash, test_every_tool_lands_on_frame_f, test_variable_rate, test_worst_stills_are_the_frames_scored,
              test_the_box_means_and_ssim_are_the_summed_area_ones_to_the_bit, test_a_phone_clip_is_its_shown_shape,
              test_a_reader_closed_early_lets_go_of_the_film_through_a_launcher, test_a_raw_stream_is_read_from_the_start,
              test_preroll_is_counted_as_a_decode_counts_it):
        with tempfile.TemporaryDirectory() as tmp:     # a file still held here is a reader that did not let go
            t(Path(tmp))
        print("ok", t.__name__)
    print("seek checks passed")


if __name__ == "__main__":
    main()
