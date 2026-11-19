#!/usr/bin/env python3
"""The tools a reader watches and compares with, on small synthetic clips with known answers: every-frame sheets,
the blind pack and its score, motion blur, and a recording read by numbers.

  python tests/test_frames.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def moving_box(path, x_of_n, seconds=2, rate=30, box=40, ground="0x101010", colour="white", y=160):
    """A dark clip with one box whose left edge on frame n is x_of_n (an ffmpeg expression in n)."""
    ffmpeg("-f", "lavfi", "-i", f"color=c={ground}:s=640x360:r={rate}:d={seconds}", "-f", "lavfi", "-i", f"color=c={colour}:s={box}x{box}:r={rate}:d={seconds}",
           "-filter_complex", f"[0][1]overlay=x='{x_of_n}':y={y}", "-c:v", "libx264", "-crf", "6", "-pix_fmt", "yuv420p", path)
    return path


def run_tool(name, *args):
    done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / name), *map(str, args)], capture_output=True, text=True)
    assert done.returncode == 0, f"{name} failed: {done.stderr[-800:]}"
    return done.stdout


def true_centres(clip):
    """The x of the box on every frame, decoded straight from the clip: what a sheet has to agree with."""
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip), "-vf", "crop=640:4:0:178", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    rows = np.frombuffer(raw, np.uint8).reshape(-1, 4, 640).astype(float).mean(1) > 128
    return [float((r * np.arange(640)).sum() / r.sum()) for r in rows]


def box_centres(sheet, cols, tile_w, count):
    """The x of the bright box in each tile of a sheet, in tile pixels (the stamp in the corner is ignored)."""
    im = np.asarray(Image.open(sheet).convert("L")).astype(float)
    tile_h = im.shape[0] // ((count + cols - 1) // cols)
    out = []
    for i in range(count):
        tile = im[(i // cols) * tile_h + 24:(i // cols + 1) * tile_h, (i % cols) * tile_w:(i % cols + 1) * tile_w]
        column = (tile > 128).sum(0)
        assert column.sum() > 0, f"tile {i} has no box"
        out.append(float((column * np.arange(tile_w)).sum() / column.sum()))
    return out


def test_every_frame_once(tmp):
    clip = moving_box(tmp / "move.mp4", "20+8*n")
    out = run_tool("sheet.py", clip, "-o", tmp / "s" / "move.jpg", "--native", "--from", 0.5, "--to", 1.5, "--cols", 6, "--rows", 10, "--width", 160)
    assert "30 frames" in out and "every frame" in out, out
    xs = box_centres(tmp / "s" / "move.jpg", 6, 160, 30)
    steps = np.diff(xs)
    assert np.all(np.abs(steps - 2.0) < 0.7), f"each tile should be the next frame, 8 px on (2 px in a 160 px tile): {steps.round(2)}"
    truth = true_centres(clip)
    first = xs[0] * 4 + 1.5                                   # the box's centre in source pixels, from the first tile (tiles are a quarter size)
    assert abs(first - truth[15]) < 3, f"the first tile should be frame 15, the first at or after 0.5 s: box at {first:.1f}, frame 15 has it at {truth[15]:.1f}"


def test_a_held_frame_shows(tmp):
    clip = moving_box(tmp / "stutter.mp4", "20+8*(n-gte(n,20))")       # one frame repeats the one before it
    held = [i + 1 for i, d in enumerate(np.diff(true_centres(clip))) if abs(d) < 0.5]
    assert len(held) == 1, f"the clip should hold exactly one frame: {held}"
    run_tool("sheet.py", clip, "-o", tmp / "s" / "stutter.jpg", "--native", "--cols", 10, "--rows", 6, "--width", 160)
    steps = np.diff(box_centres(tmp / "s" / "stutter.jpg", 10, 160, 60))
    still = [i + 1 for i, d in enumerate(steps) if abs(d) < 0.3]
    assert still == held, f"the one held frame should be the only tile equal to the one before it: sheet {still}, clip {held}"


def test_long_stretch_splits_and_old_use_still_works(tmp):
    clip = moving_box(tmp / "long.mp4", "20+8*n")
    out = run_tool("sheet.py", clip, "-o", tmp / "s" / "long.jpg", "--native", "--cols", 6, "--rows", 2, "--width", 160)
    files = sorted(p.name for p in (tmp / "s").glob("long_*.jpg"))
    assert files == [f"long_{i:03d}.jpg" for i in range(5)], files
    assert "60 frames -> 5 sheets" in out, out
    out = run_tool("sheet.py", clip, "-o", tmp / "s" / "glance.jpg", "--every", 0.5)
    assert "4 frames" in out and (tmp / "s" / "glance.jpg").exists(), out
    out = run_tool("sheet.py", clip, "-o", tmp / "s" / "over.jpg", "--fps", 5, "--cols", 5)
    assert "10 frames -> 1 sheet" in out and (tmp / "s" / "over.jpg").exists(), out
    (tmp / "stills").mkdir()                                  # a folder of stills, as a render writes them, on one sheet
    for n in (5, 20, 50):
        ffmpeg("-i", clip, "-vf", f"select=eq(n\\,{n})", "-frames:v", "1", tmp / "stills" / f"frame-{n:05d}.png")
    out = run_tool("sheet.py", tmp / "stills", "-o", tmp / "s" / "stills.jpg", "--labels", "5,20,50", "--cols", 3, "--width", 160)
    assert "3 stills" in out, out
    xs = box_centres(tmp / "s" / "stills.jpg", 3, 160, 3)
    truth = true_centres(clip)
    assert all(abs(x * 4 + 1.5 - truth[n]) < 3 for x, n in zip(xs, (5, 20, 50))), f"each tile is the still it is labelled as: {xs}"


def test_variable_rate_stamps(tmp):
    # broke: --native stamped frame number over r_frame_rate, so on a file at 30 then 60 frames a second the tile
    # stamped 1.50 s showed the frame from 2.00 s
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_seek", Path(__file__).with_name("test_seek.py"))
    seek = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seek)
    vfr = seek.numbered(tmp / "vfr.mp4", 60, n=90, pts="if(lt(N,30),N/30,1+(N-30)/60)")
    out = run_tool("sheet.py", vfr, "-o", tmp / "s" / "vfr.jpg", "--native", "--from", 1.5, "--to", 1.6, "--cols", 6, "--rows", 2, "--width", 320)
    assert "6 frames" in out and "variable rate" in out, out
    im = np.asarray(Image.open(tmp / "s" / "vfr.jpg").convert("L"))
    got = [seek.index_of(im[:180, k * 320:(k + 1) * 320]) for k in range(6)]
    assert got == list(range(60, 66)), f"the tiles from 1.5 s are frames 60 to 65, 30 frames in at 60 a second: {got}"


def test_blur_averages_the_open_shutter(tmp):
    # 96 pictures a second for a 24 fps film: the box moves 6 px a picture, 24 px a frame
    clip = moving_box(tmp / "sub.mp4", "20+6*n", seconds=1, rate=96)
    out = run_tool("blur.py", clip, tmp / "blurred.mp4", "--sub", 4, "--open", 2, "--fps", 24, "--crf", 6)
    assert "one frame for every 4 pictures" in out, out
    count = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(tmp / "blurred.mp4")], capture_output=True, text=True).stdout.strip()
    assert count == "24", f"a second of film is 24 frames, got {count}"
    ffmpeg("-i", tmp / "blurred.mp4", "-vf", "select=eq(n\\,10)", "-frames:v", "1", tmp / "f10.png")
    row = np.asarray(Image.open(tmp / "f10.png").convert("L")).astype(float)[180]
    wide, solid = int((row > 60).sum()), int((row > 200).sum())
    assert 44 <= wide <= 49 and 31 <= solid <= 37, f"two pictures 6 px apart: 46 px touched, 34 px fully lit; got {wide} and {solid}"
    left = float(np.argmax(row > 60))
    picture40 = true_centres(clip)[40] - 19.5                 # the left edge of the 40 px box on picture 40
    assert abs(left - picture40) <= 2, f"frame 10 is pictures 40 and 41: its left edge is where picture 40's is ({picture40:.0f}), got {left:.0f}"


def test_an_even_sample_reads_no_frame_times(tmp):
    # D8: sheet.py --fps stamps each tile from its own clock, so it reads no packet times (it read them, and asked
    # whether the film was variable-rate, on every vd export's hand-in sheet)
    import argparse
    from unittest.mock import patch
    import sheet
    clip = tmp / "box.mp4"
    moving_box(clip, "n*4")
    asked = []
    a = argparse.Namespace(video=str(clip), out=str(tmp / "even.jpg"), start=0.0, end=None, fps=4, cols=4, rows=2, width=160, frame_times=None)
    with patch.object(sheet, "frame_times", lambda *x, **k: asked.append("frame_times")),             patch.object(sheet, "variable_rate", lambda *x, **k: asked.append("variable_rate")):
        sheet.every_frame(a, 640, 360, 30.0, 2.0, quiet=False)
    assert not asked and (tmp / "even.jpg").exists(), asked


def test_every_in_batches_lands_where_one_seek_a_tile_did(tmp):
    # D1: sheet.py --every fetches its tiles in batches of 48 from one seek each; each must be the very frame one
    # `-ss t` call returned (the first at or after t), here on a variable-rate file whose clock starts at 2.5 s (a frame
    # time then comes out a hair under t: 2.8 - 2.5), across three batches, and with times past the end left out
    sys.path.insert(0, str(ROOT / "tests"))
    import awkward
    import sheet
    clip = awkward.vfr_late(tmp)
    w, h, _, dur = sheet.probe(str(clip))
    times = [round(k * 0.02, 3) for k in range(int(dur / 0.02) + 1)] + [dur + 0.5]
    got = dict(sheet.every_still(str(clip), times, 128, w, h))
    assert len(times) > 2 * sheet.BATCH and dur + 0.5 not in got, (len(times), sorted(got)[-3:])
    for t in times:
        one = sheet.one_still(str(clip), t, 128)
        assert (one is None) == (t not in got), t
        assert one is None or np.array_equal(np.asarray(one), np.asarray(got[t])), (t, awkward.number(np.asarray(one)), awkward.number(np.asarray(got[t])))


def main():
    tests = [test_variable_rate_stamps, test_every_frame_once, test_a_held_frame_shows, test_long_stretch_splits_and_old_use_still_works, test_blur_averages_the_open_shutter,
             test_an_even_sample_reads_no_frame_times, test_every_in_batches_lands_where_one_seek_a_tile_did]
    for t in tests:
        with tempfile.TemporaryDirectory() as tmp:
            t(Path(tmp))
        print("ok", t.__name__)
    print("frames checks passed")


if __name__ == "__main__":
    main()
