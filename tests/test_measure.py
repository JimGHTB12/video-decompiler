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
    films it read 150, 240, 222 and 67 BPM for 150, 120, 112.5 and 100, and steal pinned those as the film's clock."""
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


if __name__ == "__main__":
    a_short_window_or_broken_sound_is_not_measured()
    a_cut_short_file_is_not_measured()
    beat_rows()
    one_to_one()
    palette_and_memory()
    small_things()
    tempo_known()
    where_the_light_is()
    windowed()
    main()
