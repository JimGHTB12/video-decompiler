#!/usr/bin/env python3
"""tools/measure.py against films with known answers.

  python tests/test_measure.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"


def film(path, box_h=80, slide_at=2.0, beeps=(1.0, 1.6, 3.0)):
    """4 s: dark until a box appears at 1.0, the box slides at slide_at for 0.5 s, a grey cut at 3.0; beeps in sound."""
    x = f"if(lt(t,{slide_at}),100,if(lt(t,{slide_at + 0.5}),100+(t-{slide_at})*400,300))"
    video = f"[0][2]overlay=x='{x}':y=100:eval=frame:enable='between(t,1,3)',drawbox=x=0:y=0:w=640:h=360:color=0x808080:t=fill:enable='gte(t,3)'"
    sound = "+".join(f"between(t,{b:.2f},{b + 0.1:.2f})" for b in beeps)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101010:s=640x360:r=30:d=4",
                    "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*880*t)*({sound})':s=44100:d=4",
                    "-f", "lavfi", "-i", f"color=c=white:s=120x{box_h}:r=30:d=4", "-filter_complex", video, "-map", "1:a",
                    "-c:v", "libx264", "-crf", "6", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def eased(path, curve):
    """A box sliding 300 px from 1.0 s for 0.6 s along a known easing: 'out' (fast start) or 'in' (fast end)."""
    q = "((t-1)/0.6)"
    prog = f"(1-pow(1-{q},3))" if curve == "out" else f"pow({q},3)"
    x = f"if(lt(t,1),100,if(lt(t,1.6),100+300*{prog},400))"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101010:s=640x360:r=60:d=2.5",
                    "-f", "lavfi", "-i", "color=c=white:s=120x120:r=60:d=2.5", "-filter_complex", f"[0][1]overlay=x='{x}':y=120:eval=frame",
                    "-c:v", "libx264", "-crf", "6", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def run(*args, ok=True):
    done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), *map(str, args)], capture_output=True, text=True)
    assert ok is None or (done.returncode == 0) == ok, f"measure.py {' '.join(map(str, args))} exited {done.returncode}: {done.stdout[-800:]} {done.stderr[-800:]}"
    return done.stdout


def known_series():
    sys.path.insert(0, str(TOOLS))
    import film_diff
    import measure
    import numpy as np
    e = np.zeros(40)
    e[20], e[21] = 15.0, 60.0
    assert film_diff.find_cuts(e) == [21], f"a move running into a cut doesn't pull the cut early: {film_diff.find_cuts(e)}"
    segs = measure.segments(np.array([0.0] + [2.0] * 20), 30)
    assert segs[0][0] == "move" and segs[0][1] == 0, f"a film moving from its first frame has no rest at 0 s: {segs}"
    still = measure.segments(np.array([0.0] * 10 + [2.0] * 10), 30)
    assert still[0] == ["hold", 0, 10], f"a film that starts still still starts with a hold: {still}"


def main():
    known_series()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        run(film(d / "a.mp4"), "--out", d / "a")
        m = json.loads((d / "a" / "measure.json").read_text(encoding="utf-8"))
        for t in (1.0, 2.0, 3.0):
            assert any(abs(e - t) <= 1 / 30 + 1e-6 for e in m["events"]), f"an event at {t} s: {m['events']}"
        assert [round(c, 1) for c in m["cuts"]] == [3.0], f"only the full-frame change at 3 s is a cut, not a small box appearing: {m['cuts']}"
        box = next(h for h in m["holds"] if h["t0"] <= 1.5 <= h["t1"])
        assert abs(box["largest_band"] - 80 / 360) <= 0.012, f"the box is 80/360 of the frame high: {box['largest_band']}"
        assert abs(m["summary"]["sync_rate"] - 2 / 3) < 0.01, f"two of three events land on a beep: {m['summary']}"
        assert m["summary"]["sync_chance"] < 0.3, f"chance should be well under that: {m['summary']}"
        assert (d / "a" / m["sheets"][0]).is_file()

        run(film(d / "same.mp4"), "--out", d / "same")
        run("compare", d / "a", d / "same", "--as", "rebuild")

        run(film(d / "late.mp4", slide_at=2.2), "--out", d / "late")
        out = run("compare", d / "a", d / "late", "--as", "rebuild", ok=False)
        assert "OFF events within 2 frames" in out and "2.0" in out, f"a slide 6 frames late is a missed event: {out}"

        run(film(d / "small.mp4", box_h=40), "--out", d / "small")
        beats = d / "beats.json"
        beats.write_text(json.dumps([{"id": "box", "t0": 1.0, "t1": 3.0}, {"id": "grey", "t0": 3.0, "t1": 4.0}]), encoding="utf-8")
        out = run("compare", d / "a", d / "small", "--as", "refill", "--beats", beats, beats, ok=False)
        assert "OFF beat box" in out and "largest_band" in out, f"a box half as tall loses the beat's scale: {out}"
        assert "ok  beat grey" in out, out
        peaks = {}
        for curve in ("out", "in"):
            run(eased(d / f"{curve}.mp4", curve), "--out", d / curve)
            mv = json.loads((d / curve / "measure.json").read_text(encoding="utf-8"))["moves"]
            assert len(mv) == 1, f"one move in the {curve} film: {mv}"
            peaks[curve] = mv[0]["peak"]
        assert peaks["out"] <= 0.2 and peaks["in"] >= 0.8, f"an ease-out peaks early and an ease-in late: {peaks}"
        out = run("compare", d / "out", d / "in", "--as", "rebuild", ok=False)
        assert "OFF moves that ease like the source" in out, f"the same slide eased the other way is caught: {out}"
    print("measure checks passed")


def beat_rows():
    """A beat that rests in one film and not the other says so in words, and one too short to rest says nothing."""
    summary = dict(events_per_10s=5, median_hold_s=1, median_move_s=0.5, move_share=0.5, drift=0.1, occupancy=0.3, detail=0.05, largest_band=0.2, move_peak=0.5, sync_rate=None, sync_chance=0)
    hold = dict(occupancy=0.3, detail=0.05, largest_band=0.2, drift=0.1)
    base = dict(version=measure_version(), duration=4.0, analysed_fps=30, summary=summary, events=[], cuts=[], segments=[], moves=[], energy=[])
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, holds in (("a", [dict(t0=0.0, t1=1.0, **hold)]), ("b", [dict(t0=1.0, t1=2.0, **hold)])):
            (d / name).mkdir()
            (d / name / "measure.json").write_text(json.dumps(dict(base, holds=holds)), encoding="utf-8")
        src = [dict(id="rest", t0=0.0, t1=1.0), dict(id="busy", t0=1.0, t1=2.0), dict(id="blink", t0=2.0, t1=2.05), dict(id="gone", t0=2.05, t1=4.0)]
        other = [dict(id="rest", t0=0.0, t1=1.0), dict(id="busy", t0=1.0, t1=2.0), dict(id="blink", t0=2.0, t1=2.05)]
        (d / "ba.json").write_text(json.dumps(src), encoding="utf-8")
        (d / "bb.json").write_text(json.dumps(other), encoding="utf-8")
        done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), "compare", str(d / "a"), str(d / "b"), "--as", "refill", "--beats", str(d / "ba.json"), str(d / "bb.json")], capture_output=True, text=True)
        out = done.stdout
    assert "beat rest: source rests, other keeps moving" in out and "beat busy: source keeps moving, other rests" in out, out
    assert "no hold" not in out and "beat blink" not in out, out


def lit(path, how):
    """3 s of one grey picture: `even` all over, or with its corners darkened as a lens darkens them (`vignette`), or
    lit from the left and falling off to the right (`side`)."""
    look = {"even": "null", "vignette": "vignette=PI/3", "side": "geq=lum='lum(X,Y)*(1-0.7*X/W)':cb=128:cr=128"}[how]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0xb0b0b0:s=640x360:r=30:d=3", "-vf", look,
                    "-c:v", "libx264", "-crf", "6", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def where_the_light_is():
    # broke: three of four films by fresh agents were a lit middle with four darker corners in four frames of five, a
    # blind reader called it one template repeating, and no number in the measure said where a film's light was
    sys.path.insert(0, str(TOOLS))
    import measure
    import numpy as np
    ys, xs = np.mgrid[0:180, 0:320]
    away = np.hypot((xs - 160) / 160, (ys - 90) / 90)
    grey = lambda v: np.repeat(np.clip(v, 0, 255).astype(np.uint8)[:, :, None], 3, axis=2)
    assert measure.lit_middle(grey(200 - 90 * away)), "a middle with four darker corners is one"
    assert not measure.lit_middle(grey(np.full((180, 320), 180.0))), "an even ground isn't"
    assert not measure.lit_middle(grey(np.zeros((180, 320)))), "a black frame has no lit middle"
    assert not measure.lit_middle(grey(60 + 90 * away)), "a dark thing on a light ground isn't"
    assert not measure.lit_middle(grey(220 - 0.5 * xs)), "light from one side leaves two corners brighter than the middle"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        read = {}
        for how in ("even", "vignette", "side"):
            run(lit(d / f"{how}.mp4", how), "--out", d / how)
            read[how] = json.loads((d / how / "measure.json").read_text(encoding="utf-8"))["summary"]["dark_corners"]
        assert read == {"even": 0.0, "vignette": 1.0, "side": 0.0}, f"a film's share of such frames: {read}"
        out = run(d / "vignette.mp4", "--out", d / "again")
        assert "all four corners are darker in 100% of its frames" in out, out


def keyframes_are_not_events():
    """broke: il's copy has a keyframe every 3.000 s, and over a still picture each keyframe's one-frame change (0.39 to
    0.76, the compression resetting) was counted as a move and an event, at 6, 12, 30, 48, 51, 54 and 57 s. Planted: a
    still textured picture, lossless, a keyframe every second, its brightness stepping one level at each keyframe as a
    low-bitrate copy's does; and one real change of the same size between keyframes, which stays an event."""
    import numpy as np
    base = np.random.default_rng(3).integers(60, 190, (360, 640)).astype(np.int16)
    frames = []
    for i in range(150):                                   # 5 s at 30 fps; keyframes at 0, 1, 2, 3 and 4 s
        f = base + (i // 30) % 2                           # up a level at one keyframe, down at the next
        if i >= 75:
            f = f.copy()
            f[150:210, 290:350] += 64                      # a real change at 2.5 s, about as big over the whole frame
        frames.append(f.astype(np.uint8))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "640x360", "-r", "30", "-i", "-",
                        "-c:v", "libx264", "-qp", "0", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
                        str(d / "keys.mp4")], input=np.stack(frames).tobytes(), check=True)
        run(d / "keys.mp4", "--out", d / "keys")
        m = json.loads((d / "keys" / "measure.json").read_text(encoding="utf-8"))
        near = lambda t: any(abs(e - t) <= 1 / 30 + 1e-6 for e in m["events"])
        assert not any(near(t) for t in (1.0, 2.0, 3.0, 4.0)), f"a keyframe's compression step is no event: {m['events']}"
        assert near(2.5), f"a real change of the same size between keyframes still is: {m['events']}"
        still = [(base + (i // 30) % 2).astype(np.uint8) for i in range(150)]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "640x360", "-r", "30", "-i", "-",
                        "-output_ts_offset", "0.5", "-c:v", "libx264", "-qp", "0", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
                        "-pix_fmt", "yuv420p", str(d / "offset.mp4")], input=np.stack(still).tobytes(), check=True)
        run(d / "offset.mp4", "--out", d / "offset")
        mo = json.loads((d / "offset" / "measure.json").read_text(encoding="utf-8"))
        assert mo["events"] == [], f"keyframe steps on an offset file are not false events: {mo['events']}"
        run(d / "offset.mp4", "--out", d / "offset_win", "--from", "0", "--to", "4.0")
        mw = json.loads((d / "offset_win" / "measure.json").read_text(encoding="utf-8"))
        assert mw["events"] == [], f"nor in a window cut from an offset file: {mw['events']}"
        # a review's finding: with sound starting a second before the picture, the decode repeats the first picture back
        # to 0, so the curve starts at the file's 0, not at the first picture's packet; keys placed from the packet were a
        # second late and a still clip got a false event at 5.0. Sound after the picture, and preroll, the same.
        stillmp4 = d / "still.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "640x360", "-r", "30", "-i", "-",
                        "-c:v", "libx264", "-qp", "0", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
                        str(stillmp4)], input=np.stack(still).tobytes(), check=True)
        for name, picture_at, sound_at in (("sound_first", 1, 0), ("sound_after", 0, 1)):
            clip = d / f"{name}.mkv"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-itsoffset", str(picture_at), "-i", str(stillmp4), "-itsoffset", str(sound_at), "-f", "lavfi",
                            "-t", "5", "-i", "anullsrc=r=48000:cl=stereo", "-c:a", "pcm_s16le", "-c:v", "copy", str(clip)], check=True)
            run(clip, "--out", d / name)
            ma = json.loads((d / name / "measure.json").read_text(encoding="utf-8"))
            assert ma["events"] == [], f"keyframe steps where {name.replace('_', ' ')} are not events: {ma['events']}"
        pre = d / "preroll.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(stillmp4), "-c", "copy", "-output_ts_offset", "-0.1", "-avoid_negative_ts", "disabled", str(pre)], check=True)
        run(pre, "--out", d / "preroll")
        mp = json.loads((d / "preroll" / "measure.json").read_text(encoding="utf-8"))
        assert mp["events"] == [], f"nor on a file with preroll before 0: {mp['events']}"


def measure_version():
    sys.path.insert(0, str(TOOLS))
    import measure
    return measure.VERSION


def slide(path, box):
    """One easeOutCubic slide of 400 px over 0.5 s at 60 fps, from 0.5 s, of a white box `box` px wide and tall."""
    q = "((t-0.5)/0.5)"
    x = f"if(lt(t,0.5),100,if(lt(t,1.0),100+400*(1-pow(1-{q},3)),500))"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101010:s=960x540:r=60:d=2",
                    "-f", "lavfi", "-i", f"color=c=white:s={box}x{box}:r=60:d=2", "-filter_complex", f"[0][1]overlay=x='{x}':y=150:eval=frame",
                    "-c:v", "libx264", "-crf", "6", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def small_things():
    # broke: easing was fitted to picture change, which stops following speed once a thing moves further in a frame
    # than its own size. The same slide read as 0.5 s eased [0.3, 0.9, 0.6, 1.0] on a 200 px box and as 0.3 s, nearly
    # linear [0.3, 0.4, 0.5, 0.8], on a 24 px box, with nothing to say the second wasn't a measurement.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, box in (("big", 200), ("small", 24)):
            run(slide(d / f"{name}.mp4", box), "--out", d / name)
        big, small = (json.loads((d / n / "measure.json").read_text(encoding="utf-8")) for n in ("big", "small"))
        assert len(big["moves"]) == 1 and big["moves"][0]["ease_reliable"] and big["moves"][0]["peak"] <= 0.2, big["moves"]
        assert len(small["moves"]) == 1 and small["moves"][0]["ease_reliable"] is False, f"the small box's easing can't be read: {small['moves']}"
        assert small["summary"]["move_peak"] is None, "a peak the method can't read isn't reported"
        out = run("compare", d / "big", d / "small", "--as", "rebuild", ok=None)
        assert "moves that ease like the source" not in out and "left out of the easing row" in out and "further in a frame than its own size" in out, out


def one_to_one():
    # broke: each source event took its nearest rebuild event, so one rebuild event at 1.05 s matched source events at
    # 1.0 and 1.1 s, and "0 of 7 off" passed a rebuild that had merged the two
    summary = dict(events_per_10s=5, median_hold_s=1, median_move_s=0.5, move_share=0.5, drift=0.1, occupancy=0.3, detail=0.05, largest_band=0.2, move_peak=0.5, sync_rate=None, sync_chance=0)
    base = dict(version=measure_version(), duration=4.0, analysed_fps=30, summary=summary, cuts=[], segments=[], moves=[], holds=[], energy=[0.0] * 120)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, events in (("a", [1.0, 1.1]), ("b", [1.05])):
            (d / name).mkdir()
            (d / name / "measure.json").write_text(json.dumps(dict(base, events=events)), encoding="utf-8")
        out = run("compare", d / "a", d / "b", "--as", "rebuild", ok=False)
    assert "OFF events within 2 frames: source 2, other 1" in out and "'missing': [1.1]" in out, out
    sys.path.insert(0, str(TOOLS))
    import measure
    assert measure.match_events([1.0, 1.1, 2.0], [1.09, 1.03, 2.5], 0.07) == ([(1.0, 1.03), (1.1, 1.09)], [2.0], [2.5]), "each event once, whatever order they come in"
    # broke: the closest single pair (1.00 with 1.04) was taken first, which left 1.12 with nothing in reach
    assert measure.match_events([1.0, 1.12], [0.92, 1.04], 0.08 + 1e-6) == ([(1.0, 0.92), (1.12, 1.04)], [], []), "as many pairs as can be made, each within two frames"


def cuts(path):
    """8 s: dark, a white card from 3 s, grey from 5 s; a box slides 2.2 to 2.8 s."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101010:s=640x360:r=30:d=8", "-f", "lavfi", "-i", "color=c=0x909090:s=60x60:r=30:d=8",
                    "-filter_complex", "[0][1]overlay=x='if(lt(t,2.2),50,if(lt(t,2.8),50+(t-2.2)*500,350))':y=50:eval=frame,drawbox=x=0:y=120:w=640:h=240:color=white:t=fill:enable='between(t,3,5)',"
                    "drawbox=x=0:y=0:w=640:h=360:color=0x606060:t=fill:enable='gte(t,5)'", "-c:v", "libx264", "-crf", "6", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def windowed():
    # broke: --from/--to wrote "video" as a temp copy that was never deleted, "duration" as the window's length with no
    # name for the whole film's, and compare lined a windowed source's energy up with a whole rebuild's from index 0
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        temp = d / "temp"
        temp.mkdir()
        film_ = cuts(d / "cuts.mp4")
        env = dict(os.environ, TMP=str(temp), TEMP=str(temp), TMPDIR=str(temp))
        done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), str(film_), "--out", str(d / "win"), "--from", "2", "--to", "6"], capture_output=True, text=True, env=env)
        assert done.returncode == 0, done.stderr[-600:]
        assert not any(temp.iterdir()), f"no temporary copy is left behind: {list(temp.iterdir())}"
        m = json.loads((d / "win" / "measure.json").read_text(encoding="utf-8"))
        assert m["video"] == str(film_) and m["window"] == [2.0, 6.0] and m["window_seconds"] == m["duration"] == 4.0 and m["film_seconds"] == 8.0 and m["energy_t0"] == 2.0, {k: m.get(k) for k in ("video", "window", "window_seconds", "duration", "film_seconds", "energy_t0")}
        assert [round(t, 1) for t in m["cuts"]] == [3.0, 5.0], m["cuts"]
        run(film_, "--out", d / "whole")
        out = run("compare", d / "win", d / "whole", "--as", "rebuild", ok=None)
        assert "ok  still where the source moves" in out, f"the same film, windowed and whole, moves at the same moments: {out}"


def palette_and_memory():
    # broke: the hold palette came from k-means seeded by OpenCV's global generator, so the same picture gave another
    # palette depending on what the process had looked at before
    sys.path.insert(0, str(TOOLS))
    import cv2
    import numpy as np
    import measure
    rng = np.random.default_rng(1)
    pic = cv2.GaussianBlur(rng.integers(0, 255, (540, 960, 3)).astype(np.uint8), (0, 0), 6)
    first = measure.look(pic)["palette"]
    for _ in range(4):
        measure.look(cv2.GaussianBlur(rng.integers(0, 255, (540, 960, 3)).astype(np.uint8), (0, 0), 6))
    assert measure.look(pic)["palette"] == first, "the same picture gives the same palette whatever ran before"
    # broke: every analysed frame was kept for a fallback that almost never runs (1.9 GB on a 3 minute film)
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_seek", Path(__file__).with_name("test_seek.py"))
    seek = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seek)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        peaks = []
        for s in (4, 20):  # always moving and longer than MOVE_FIT, so neither fits an easing, whose table is a large passing peak
            clip = d / f"m{s}.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=60:d={s}", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(clip)], check=True)
            code, said, peak = seek.peak_mb([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), str(clip), "--out", str(d / f"o{s}")])
            assert code == 0, said[-400:]
            peaks.append(peak)
        assert peaks[1] - peaks[0] < 40, f"measure.py's memory grows with the film: {peaks[0]:.0f} MB for 4 s, {peaks[1]:.0f} MB for 20 s (keeping every frame, about 165 MB more)"
        frames = list(measure.frames(d / "m4.mp4", 60.0))
        assert np.array_equal(measure.analysed_frame(d / "m4.mp4", 60.0, 37), frames[37]), "the fallback decodes the same analysed frame"


def a_cut_short_file_is_not_measured():
    # broke: measure.py, see.py and ear.py read an ffmpeg pipe, threw its errors away and ignored its exit code, so a file
    # that stopped decoding part way was measured as the part that decoded, and written as if it were all of it
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        whole = film(d / "whole.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(whole), "-c", "copy", "-movflags", "+faststart", str(d / "fast.mp4")], check=True)
        data = (d / "fast.mp4").read_bytes()
        cut = d / "cut.mp4"
        cut.write_bytes(data[:len(data) * 6 // 10])   # its index says 4 s; its pictures and sound stop near 2.4 s, as a copy cut off does
        for tool in ("measure.py", "see.py"):
            done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / tool), str(cut), "--out", str(d / tool)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            said = done.stdout + done.stderr
            assert done.returncode != 0 and "stopped reading" in said and not (d / tool).exists(), f"{tool} stops, says why and writes nothing: {said[-400:]}"
        run(whole, "--out", d / "fine")
        assert (d / "fine" / "measure.json").exists(), "and measure.py measures a whole file"


def a_short_window_or_broken_sound_is_not_measured():
    # broke: with --from/--to, a source cut off early gave a shorter temporary clip while ffmpeg exited 0, and it was measured
    # as the window; and the sound was decoded apart from the pictures with its exit status unread, so broken sound under
    # whole pictures was analysed as far as it got
    sys.path.insert(0, str(TOOLS))
    import measure
    from types import SimpleNamespace
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        whole = film(d / "whole.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(whole), "-c", "copy", "-movflags", "+faststart", str(d / "fast.mp4")], check=True)
        data = (d / "fast.mp4").read_bytes()
        cut = d / "cut.mp4"
        cut.write_bytes(data[:len(data) * 6 // 10])   # its index says 4 s; its pictures and sound stop near 2.4 s
        done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), str(cut), "--out", str(d / "window"), "--from", "0", "--to", "3.5"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        said = done.stdout + done.stderr
        assert done.returncode != 0 and "window cut" in said and not (d / "window" / "measure.json").exists(), f"a short window is not measured as the window: {said[-400:]}"
        # and the pictures are what is counted: a cut runs as long as its sound, which can outlast pictures that stopped early
        talk = d / "talk.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=24:d=2", "-f", "lavfi", "-i", "sine=d=8",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(talk)], check=True)
        done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), str(talk), "--out", str(d / "talk"), "--from", "0", "--to", "3.5"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        said = done.stdout + done.stderr
        assert done.returncode != 0 and "of pictures" in said and not (d / "talk" / "measure.json").exists(), f"8 s of sound don't make 2 s of pictures a 3.5 s window: {said[-400:]}"
        broken = SimpleNamespace(returncode=1, stdout=bytes(2 * 16000), stderr=b"Error while decoding stream #0:1: Invalid data found when processing input")
        with patch.object(measure.subprocess, "run", lambda *a, **k: broken):
            try:
                measure.audio(whole, 4.0)
                raise AssertionError("a sound ffmpeg failed to decode is not analysed")
            except SystemExit as e:
                assert "couldn't read" in str(e), e


def tempo_known():
    """A drum pattern at 112.5 BPM (kick on each beat, hat on each half beat, accent every bar) is read as 112.5.
    broke: measure.audio took the highest level-autocorrelation lag in 60-200 BPM, then halved it; on the four accepted
    films it read 150, 240, 222 and 67 BPM for 150, 120, 112.5 and 100, and borrow pinned those as the film's clock."""
    sys.path.insert(0, str(TOOLS))
    import measure
    bpm, dur = 112.5, 12.0
    beat = 60.0 / bpm
    kick = "+".join(f"between(t,{i * beat:.4f},{i * beat + 0.06:.4f})*(1+{int(i % 4 == 0)})" for i in range(int(dur / beat)))
    hat = "+".join(f"between(t,{(i + 0.5) * beat:.4f},{(i + 0.5) * beat + 0.02:.4f})" for i in range(int(dur / beat)))
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "beat.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"aevalsrc='0.4*sin(2*PI*70*t)*({kick})+0.15*sin(2*PI*5000*t)*({hat})':s=44100:d={dur}", str(wav)], check=True)
        t = measure.audio(wav, dur)["tempo"]
        assert t and abs(t["bpm"] - bpm) < 0.5, f"a 112.5 BPM pattern is read as 112.5: {t}"
        assert 56.0 < t["octave"][0] < 57.0 and 224.0 < t["octave"][1] < 226.0, f"its half and double are named as the octave it can't rule out: {t}"


def batched_seeks_stay_exact_and_under_select_limit():
    """measure.sheet and hold grabs fetch stills in batches under ffmpeg's ~100-term select limit and 32k command line,
    landing on the exact frame across batch boundaries on both constant- and variable-rate clips."""
    import importlib.util
    from unittest.mock import patch
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(TOOLS))
    import film_diff
    import measure
    spec = importlib.util.spec_from_file_location("test_seek", Path(__file__).with_name("test_seek.py"))
    seek = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seek)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfr = seek.numbered(d / "cfr.mp4", 30, n=150)
        ct, ok = film_diff.packet_clock(cfr)   # as measure.measure reads it: the clock and whether it can be sought by
        # 110 stills: past ffmpeg's ~100-term select parser limit, split into batches of <= BATCH
        picks = list(range(5, 115))
        ts = [round(f / 30, 3) for f in picks]
        (d / "sh").mkdir()
        real_run, cmds = measure.subprocess.run, []
        with patch.object(measure.subprocess, "run", lambda cmd, **kw: (cmds.append([str(x) for x in cmd]), real_run(cmd, **kw))[1]):
            files = measure.sheet(cfr, ts, d / "sh", 30.0, ct, ok)
        assert len(cmds) <= (len(picks) + 47) // 48 and len(cmds) < 10, f"110 sheet tiles fetched in {len(cmds)} batched ffmpeg calls, not one per tile"
        assert all(sum(len(x) + 1 for x in c) < 8000 and x_terms <= 60 for c in cmds for x_terms in [sum(s.count("eq(n") for s in c)]), cmds
        # Check tiles across batch boundaries (0, 47, 48, 95, 96, 109) show the exact frame (avoiding top-left 70x16 label)
        for idx in (0, 47, 48, 95, 96, 109):
            with Image.open(d / "sh" / files[idx // 40]) as board:
                k = idx % 40
                tile = np.asarray(board.crop(((k % 5) * 320, (k // 5) * 180, (k % 5 + 1) * 320, (k // 5 + 1) * 180)).convert("L"))
                assert seek.index_of(tile) == picks[idx], f"tile {idx} showed frame {seek.index_of(tile)}, not {picks[idx]}"
        # Variable-rate clip: batched grabs across rate step (frames 28, 30, 60) land on exact frames
        vfr = seek.numbered(d / "vfr.mp4", 60, n=90, pts="if(lt(N,30),N/30,1+(N-30)/60)")
        vt = film_diff.clock(vfr)
        got = [seek.index_of(np.mean(im, axis=2)) for im in measure.grabs(vfr, [vt[28], vt[30], vt[60]], vt)]
        assert got == [28, 30, 60], f"batched grabs on VFR: {got}"


def times_as_an_array_are_read_by_their_length():
    """An R2 review's finding: measure.sheet given its times as a NumPy array tested the array's truth, not its length,
    so one time at 0.0 drew nothing and two raised ValueError."""
    import numpy as np
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(Path(__file__).parent))
    import awkward
    import measure
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        film = awkward.numbered(d)
        for k, times in enumerate((np.array([]), np.array([0.0]), np.array([0.0, 1.0]))):
            (d / f"s{k}").mkdir()
            files = measure.sheet(film, times, d / f"s{k}", 30.0)
            assert len(files) == (0 if len(times) == 0 else 1), (times, files)
        got = [None if im is None else awkward.number(im) for im in measure.grabs(film, np.array([0.0, 1.0, 2.0]))]
        assert got == [0, 30, 60], got


def a_batch_that_starts_in_preroll_picks_each_frame_as_one_grab_would():
    """An R2 review's finding: on a file with packets before 0, a batch whose first time fell in the preroll a decode
    never shows counted every later pick from the wrong picture ([3, 6, 34] where single grabs give [3, 3, 31]). Each
    pick is checked against the shown picture nearest its time in a plain decode from the start."""
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(Path(__file__).parent))
    import awkward
    import measure
    with tempfile.TemporaryDirectory() as tmp:
        pre = awkward.preroll(Path(tmp))
        seen = awkward.shown_at(pre)
        at = [-0.1, 0.0, 0.933333, 2.0, 4.8]
        want = [min(seen, key=lambda s: (abs(s[0] - t), s[0]))[1] for t in at]
        got = [None if im is None else awkward.number(im) for im in measure.grabs(pre, at)]
        assert want[:3] == [3, 3, 31] and got == want, f"preroll batch picks {got}, not {want}"
        got = [awkward.number(measure.grab(pre, t)) for t in at]
        assert got == want, f"preroll single grabs {got}, not {want}"


def a_files_frames_and_keyframes_come_from_one_read_of_its_packets():
    """C5a: frame_times read the packets and then the whole file again for its start_time, and keyframe_times did both
    once more; one ffprobe now gives the times, the keyframes and the start_time, on a file whose clock starts late."""
    from unittest.mock import patch
    import numpy as np
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(Path(__file__).parent))
    import awkward
    import film_diff
    with tempfile.TemporaryDirectory() as tmp:
        late = awkward.vfr_late(Path(tmp))
        real, calls = film_diff.subprocess.run, []
        with patch.object(film_diff.subprocess, "run", lambda cmd, **k: (calls.append(cmd[0]), real(cmd, **k))[1]):
            times = film_diff.frame_times(late)
            assert calls == ["ffprobe"], f"frame_times reads the file once: {calls}"
            calls.clear()
            times2, keys = film_diff.packet_times(late)
            assert calls == ["ffprobe"], f"times and keyframes in one read: {calls}"
        assert np.array_equal(times, times2) and abs(times[0]) < 1e-9 and abs(times[30] - 1.0) < 1e-3, times[:3]
        assert keys and keys[0] == 0.0 and all(k in set(times.tolist()) for k in keys), keys


def the_light_table_and_the_ink_mask_are_the_old_numbers():
    """C4: lit_middle reads light from a table, and look finds ink with cv2.inRange; both must give the old numbers
    exactly, the table on all 256 greys and the mask where the ground's mean is a half and pixels sit at 40 from it."""
    import numpy as np
    sys.path.insert(0, str(TOOLS))
    import measure
    greys = np.resize(np.arange(256, dtype=np.uint8), (180, 320))
    assert np.array_equal(measure.GAMMA22[greys], (greys.astype(np.float32) / 255) ** 2.2), "the light table is the power, bit for bit"
    rng = np.random.default_rng(4)
    for ground in ((100, 101), (40, 41), (200, 201), (0, 0), (255, 255), (7, 9)):
        rgb = rng.integers(0, 256, (90, 160, 3)).astype(np.uint8)
        border = np.array(ground * 500, np.uint8)[:2 * 160 + 2 * 90]
        rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1] = (np.stack([border[:160]] * 3, -1), np.stack([border[160:320]] * 3, -1),
                                                  np.stack([border[320:410]] * 3, -1), np.stack([border[410:500]] * 3, -1))
        bg = measure.background(rgb)
        near = np.clip(np.round(bg)[None, None, :] + rng.integers(-42, 43, (90, 160, 3)), 0, 255).astype(np.uint8)
        near[0], near[-1], near[:, 0], near[:, -1] = rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]
        for picture in (rgb, near):
            old = np.abs(picture.astype(int) - measure.background(picture)).max(axis=2) > 40
            assert abs(old.mean() - measure.look(picture)["occupancy"]) < 5e-4, ground
            b = measure.background(picture)
            lo, hi = np.clip(np.ceil(b - 40), 0, 255), np.clip(np.floor(b + 40), 0, 255)
            new = measure.cv2.inRange(picture, tuple(float(v) for v in lo), tuple(float(v) for v in hi)) == 0
            assert np.array_equal(old, new), (ground, b)


if __name__ == "__main__":
    the_light_table_and_the_ink_mask_are_the_old_numbers()
    a_files_frames_and_keyframes_come_from_one_read_of_its_packets()
    a_batch_that_starts_in_preroll_picks_each_frame_as_one_grab_would()
    times_as_an_array_are_read_by_their_length()
    a_short_window_or_broken_sound_is_not_measured()
    a_cut_short_file_is_not_measured()
    batched_seeks_stay_exact_and_under_select_limit()
    beat_rows()
    keyframes_are_not_events()
    one_to_one()
    palette_and_memory()
    small_things()
    tempo_known()
    where_the_light_is()
    windowed()
    main()
