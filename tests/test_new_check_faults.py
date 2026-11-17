#!/usr/bin/env python3
"""The checks and makers the newer commands added, against faults a review planted and found.

Scan: a checkerboard that reverses five times a second is a flash by WCAG 2.3.1; the export's scan never calls it `ok`
(every flash is a line to look at: the check fires on an accepted film, so it is not calibrated), and a steady film
stays quiet. Look: white type at 72 px on plain #767676 passes (WCAG asks 3:1 of large text, and it measures 4.54:1), and the same type over busy mid-grey noise is called a collision. Launch and
capture: with no command given, nothing is shown as having run; the folder's own BOARD.md is left as it was. Needs ffmpeg.

  python tests/test_new_check_faults.py
"""
import contextlib
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import lean  # noqa: E402
import look  # noqa: E402
import puppet  # noqa: E402
import scan  # noqa: E402


def frames_to_mp4(path, frames, fps=30):
    h, w = frames[0].shape[:2]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                    "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", str(path)], input=np.stack(frames).tobytes(), check=True)




def flash_line(text):
    return next(line for line in text.splitlines() if "flash (WCAG 2.3.1" in line).strip()




def test_scan_reports_a_reversing_checkerboard():
    w, h = 320, 180
    yy, xx = np.mgrid[0:h, 0:w]
    board = (((yy // 8) + (xx // 8)) % 2).astype(np.uint8)
    with tempfile.TemporaryDirectory() as tmp:
        flashing = Path(tmp) / "board.mp4"
        frames_to_mp4(flashing, [np.where(board ^ ((i // 3) % 2), 235, 20).astype(np.uint8) for i in range(60)])
        text, fixes = scan.scan(flashing)
        # its brightness over the field does not change, so it is no WCAG 2.3.1 flash; it is named as a pattern to look at
        assert "motion or patterns (not WCAG flashes)" in text, f"a 5 Hz reversing checkerboard was not named:\n{text}"
        steady = Path(tmp) / "steady.mp4"
        frames_to_mp4(steady, [np.where(board, 235, 20).astype(np.uint8) for _ in range(60)])
        text, fixes = scan.scan(steady)
        assert flash_line(text).endswith("ok") and not any("WCAG" in f for f in fixes), f"a still checkerboard was called a flash:\n{text}"




def type_case(ground, masked=True):
    W, H = 1920, 1080
    img = Image.fromarray(ground)
    f = ImageFont.truetype(str(ROOT / "skills" / "video-decompiler" / "library" / "films" / "plusone" / "media" / "fonts" / "anton.ttf"), 72)  # a heavy face, shipped here
    x, y, words = 300, 400, "Ship it today"
    ImageDraw.Draw(img).text((x, y), words, font=f, fill=(255, 255, 255))
    glyphs = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glyphs).text((x, y), words, font=f, fill=255)
    bb = ImageDraw.Draw(img).textbbox((x, y), words, font=f)
    t = {"text": words, "box": [x, y, bb[2] - x + 200, bb[3] - y], "size": 72.0, "color": "rgb(255, 255, 255)", "opacity": 1.0, "lines": 1}
    # raea's layer mask, at a quarter of the frame: the picture is frontmost everywhere but under the letters
    image_mask = np.asarray(glyphs)[2::4, 2::4][:270, :480] < 128
    return look.contrast_note(t, np.asarray(img), W, H, image_mask_2d=image_mask if masked else None)


def test_near_black_is_dark():
    # broke: units were guessed from the largest value, so #010101 read as luminance 1.0 and dark-on-dark text passed
    import flash_scan
    for v, want in ((0, 0.0), (1, 0.000304), (2, 0.000607), (255, 1.0)):
        got = float(flash_scan.relative_luminance(np.array([[[v, v, v]]], dtype=np.uint8))[0, 0])
        assert abs(got - want) < 2e-5, (v, got)
        assert abs(float(flash_scan.relative_luminance(np.array([[[v, v, v]]]))[0, 0]) - want) < 2e-5, ("int64", v)
    assert abs(float(flash_scan.relative_luminance(np.array([[[1.0, 1.0, 1.0]]]))[0, 0]) - 1.0) < 1e-6, "floats are 0..1"


def test_look_contrast_holds_large_type_to_three_to_one():
    plain = np.full((1080, 1920, 3), 118, dtype=np.uint8)
    for masked in (True, False):  # with raea's layer mask, and without one (a film whose layers were not read)
        assert type_case(plain, masked) is None, f"white 72 px type on plain #767676 (4.54:1) was called a collision (mask: {masked})"
    noise = np.random.default_rng(2).integers(90, 256, (1080 // 6, 1920 // 6, 1)).astype(np.uint8)
    busy = np.repeat(np.repeat(np.repeat(noise, 6, 0), 6, 1), 3, 2)
    assert type_case(busy) is not None, "white type over bright busy noise was passed"
    assert look.wcag_floor(72) == 3.0 and look.wcag_floor(22) == 4.5


def test_look_judges_contrast_by_what_is_shown():
    mask = np.ones((270, 480), dtype=bool)
    # a 72 px title the camera shows 22 px high is held to 4.5:1, not large text's 3:1 (it was passed at about 3.45:1)
    noise = np.random.default_rng(3).integers(105, 146, (540, 960, 1), dtype=np.uint8)
    mid = np.repeat(np.repeat(np.repeat(noise, 2, 0), 2, 1), 3, 2)
    shrunk = {"text": "Scaled title", "box": [300, 400, 400, 22], "size": 72, "color": "#ffffff", "opacity": 1, "lines": 1}
    assert look.contrast_note(shrunk, mid, 1920, 1080, image_mask_2d=mask) is not None, "a shrunken title kept large text's floor"
    two = {**shrunk, "text": "Scaled" + chr(10) + "title", "box": [300, 400, 400, 44], "lines": 2}   # two lines shown 22 px each
    assert look.contrast_note(two, mid, 1920, 1080, image_mask_2d=mask) is not None, "a shrunken two-line title kept large text's floor"
    # near-black type on a dark busy ground is a collision (#010101 was read as white and passed)
    noise = np.random.default_rng(2).integers(50, 101, (540, 960, 1), dtype=np.uint8)
    dark = np.repeat(np.repeat(np.repeat(noise, 2, 0), 2, 1), 3, 2)
    t = {"text": "Dark title", "box": [300, 400, 600, 72], "size": 72, "color": "#010101", "opacity": 1, "lines": 1}
    assert look.contrast_note(t, dark, 1920, 1080, image_mask_2d=mask) is not None, "near-black type on a dark ground passed"



def write_layers(path, layers, masks, w=480, h=270):
    """A RAEALAYR file as raea writes it: a JSON header naming the layers, then each frame's mask as (value, run) pairs."""
    import gzip
    import json
    import struct
    head = json.dumps({"layers": layers, "mask": {"w": w, "h": h}, "frames": len(masks), "at": sorted(masks)}).encode()
    body = b""
    for f in sorted(masks):
        flat = np.asarray(masks[f], dtype=np.int64).ravel()
        runs, i = [], 0
        while i < len(flat):
            j = i
            while j < len(flat) and flat[j] == flat[i] and j - i < 65535:
                j += 1
            runs += [int(flat[i]), j - i]
            i = j
        body += struct.pack("<I", len(runs) // 2) + struct.pack(f"<{len(runs)}H", *runs)
    path.write_bytes(gzip.compress(b"RAEALAYR" + struct.pack("<I", len(head)) + head + body))


def look_at(tmp, rgb, texts, layers, mask):
    import json
    out = Path(tmp)
    png = out / "frame-00010.png"
    Image.fromarray(rgb).save(png)
    write_layers(out / "f.layers", layers, {10: mask})
    (out / "render.json").write_text(json.dumps({"width": 1920, "height": 1080, "layers": "f.layers",
                                                 "frames": [{"frame": 10, "text": texts, "elements": []}]}), encoding="utf-8")
    per, _ = look.report(out, [10], 60, pngs_by_frame={10: png})
    return [n for n in per[10] if n.kind == "contrast"]


def test_look_checks_text_over_any_busy_ground_and_only_its_own_layers():
    W, H = 1920, 1080
    rng = np.random.default_rng(5)
    noise = np.repeat(np.repeat(rng.integers(150, 256, (H // 6, W // 6, 1)).astype(np.uint8), 6, 0), 6, 1).repeat(3, 2)
    plain = np.full((H, W, 3), 200, dtype=np.uint8)
    box = [600, 450, 700, 100]
    # the ground is a drawn element (a CSS background, an SVG), not an <img>: it was never checked
    layers = [{"kind": "element", "name": "ground", "loc": "film.tsx:1:1", "key": "g", "parent": None, "frames": [0, 100]},
              {"kind": "text", "name": "Pale title", "loc": "kit/core.tsx:9:1", "key": "t", "parent": "film.tsx:1:1|g", "frames": [0, 100]},
              {"kind": "element", "name": "panel", "loc": "film.tsx:2:1", "key": "p", "parent": None, "frames": [0, 100]}]
    mask = np.ones((270, 480), dtype=np.int64)
    mask[:, 400:] = 3                                   # a panel beside it: the ground is not frontmost on all the frame
    mask[115:135, 155:320] = 2                          # the letters, frontmost over the ground
    t = {"text": "Pale title", "box": box, "size": 80.0, "color": "#e6e6e6", "opacity": 1.0, "lines": 1, "loc": "kit/core.tsx:9:1"}
    with tempfile.TemporaryDirectory() as tmp:
        assert look_at(tmp, noise.copy(), [t], layers, mask), "pale text over a busy drawn ground was passed"
    with tempfile.TemporaryDirectory() as tmp:
        assert not look_at(tmp, plain.copy(), [t], layers, mask), "a plain drawn ground is no collision"
    # a sentence set as word spans (<Words>), wholly covered by a card whose own title sits over its box: it drew no
    # pixels, so it is no collision (every text layer had stood in for its own, the card's title too)
    layers2 = [{"kind": "element", "name": "ground", "loc": "film.tsx:1:1", "key": "g", "parent": None, "frames": [0, 100]},
               {"kind": "text", "name": "Three", "loc": "kit/base.tsx:60:7", "key": "w1", "parent": "kit/base.tsx:54:5|s", "frames": [0, 100]},
               {"kind": "text", "name": "seconds", "loc": "kit/base.tsx:60:7", "key": "w2", "parent": "kit/base.tsx:54:5|s", "frames": [0, 100]},
               {"kind": "text", "name": "Modal", "loc": "card.tsx:3:3", "key": "m", "parent": "card.tsx:1:1|c", "frames": [0, 100]},
               {"kind": "element", "name": "panel", "loc": "film.tsx:2:1", "key": "p", "parent": None, "frames": [0, 100]}]
    mask2 = np.ones((270, 480), dtype=np.int64)
    mask2[:, 400:] = 5
    mask2[115:135, 155:320] = 4                         # the card's title covers the box; the words are under the card
    t2 = {"text": "Three seconds", "box": box, "size": 80.0, "color": "#e6e6e6", "opacity": 1.0, "lines": 1, "loc": "kit/base.tsx:54:5"}
    with tempfile.TemporaryDirectory() as tmp:
        assert not look_at(tmp, noise.copy(), [t2], layers2, mask2), "wholly covered word spans were called a collision"
    # see-through ink shows the ground through it: dark ink at a fifth of full alpha over a bright busy ground is pale
    rng2 = np.random.default_rng(6)
    bright = np.repeat(np.repeat(rng2.integers(170, 256, (H // 6, W // 6, 1)).astype(np.uint8), 6, 0), 6, 1).repeat(3, 2)
    solid = {**t, "color": "#101010"}
    faint = {**t, "color": "rgba(16, 16, 16, 0.2)"}
    with tempfile.TemporaryDirectory() as tmp:
        assert not look_at(tmp, bright.copy(), [solid], layers, mask), "solid dark ink over a bright ground reads"
    with tempfile.TemporaryDirectory() as tmp:
        assert look_at(tmp, bright.copy(), [faint], layers, mask), "dark ink at a fifth of full alpha was judged as solid"


def test_launch_shows_no_run_that_did_not_happen_and_keeps_the_board():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        film = Path(tmp) / "film"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            lean.main(["new", str(film), "--like", "stet"])
        (film / "BOARD.md").write_text("# my own board\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            puppet.build_launch_film(repo, out_dir=film)
        assert (film / "BOARD.md").read_text(encoding="utf-8") == "# my own board\n", "launch overwrote the film's board"
        assert (film / "REPO-FACTS.md").is_file()
        gen = (film / "kit" / "puppet.gen.ts").read_text(encoding="utf-8")
        assert '"ran": false' in gen and '"command": null' in gen and "ready" not in gen, gen[-600:]


def flash_film(path, frame, n=60):
    frames_to_mp4(path, [frame(i) for i in range(n)])
    return scan.scan(path)


def test_flash_verdict_follows_wcag_231():
    # calibrated to WCAG 2.3.1's own terms: a flash is a pair of opposing changes over a quarter of a 10-degree field,
    # and more than three in a second fails. Every case is built from exact frame counts at 30 fps.
    w, h = 320, 180
    wcag = lambda fixes: [f for f in fixes if "WCAG 2.3.1" in f]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        full = lambda half: (lambda i: np.full((h, w), 235 if (i // half) % 2 else 20, dtype=np.uint8))
        assert wcag(flash_film(tmp / "4hz.mp4", full(4))[1]), "full-frame flashing near 4 Hz (7.5 changes a second) is a fix"
        assert not wcag(flash_film(tmp / "3hz.mp4", full(5))[1]), "full-frame flashing at 3 Hz (6 changes a second) is at the limit, not over"

        def box(share):   # a flashing box of `share` of the 10-degree field (a third of the width by 4/9 of the height)
            bw, bh = int(w / 3 * share ** 0.5), int(h * 4 / 9 * share ** 0.5)
            def frame(i):
                f = np.full((h, w), 20, dtype=np.uint8)
                if (i // 4) % 2:
                    f[60:60 + bh, 120:120 + bw] = 235
                return f
            return frame
        assert wcag(flash_film(tmp / "box30.mp4", box(0.30))[1]), "a box over 30% of the field flashing at 4 Hz is a fix"
        assert not wcag(flash_film(tmp / "box20.mp4", box(0.20))[1]), "a box over 20% of the field is under WCAG's quarter"
        # near-black: black against #010101 is no flash (#010101 was once read as white)
        assert not wcag(flash_film(tmp / "black.mp4", lambda i: np.full((h, w), 1 if (i // 4) % 2 else 0, dtype=np.uint8))[1])
        # an ultrawide frame clips the field's height: WCAG's quarter is of the field, not of what is left of it in the frame
        # (a patch over 19% of the field was flagged). 1024 x 128: the field is a third of the width by twice the height.
        def strip(share_of_field):
            uw, uh = 1024, 128
            fw, fh = uw / 3, uh * 2
            pw = int(fw * share_of_field * fh / uh)        # a patch the frame's full height, so its share of the field is set by its width
            def frame(i):
                f = np.full((uh, uw), 20, dtype=np.uint8)
                if (i // 4) % 2:
                    f[:, 300:300 + pw] = 235
                return f
            return frame
        assert not wcag(flash_film(tmp / "uw19.mp4", strip(0.19))[1]), "a patch over 19% of the field of an ultrawide film is under WCAG's quarter"
        assert wcag(flash_film(tmp / "uw30.mp4", strip(0.30))[1]), "a patch over 30% of the field of an ultrawide film is over it"
        # a pan over stripes moves; it does not flash
        yy, xx = np.mgrid[0:h, 0:w]
        text, fixes = flash_film(tmp / "pan.mp4", lambda i: np.where(((xx + 6 * i) // 12) % 2, 235, 20).astype(np.uint8))
        assert not wcag(fixes), f"a pan over stripes was called a flash:\n{text}"


def test_the_accepted_films_have_no_wcag_flash():
    import flash_scan
    for film in ("stet", "onoma", "plusone", "linden"):
        r = flash_scan.screen_video(ROOT / "docs" / "media" / f"{film}.mp4")
        assert not r["classic_flagged"], (film, r["busiest_classic"], r["busiest_red"])


def test_scan_points_at_the_second_that_flashed():
    import flash_scan
    w, h = 320, 180
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "plain.mp4"
        frames_to_mp4(f, [np.full((h, w), 90, dtype=np.uint8) for _ in range(30)])
        row = {"window": [0, 0, 64, 36]}
        planted = {"busiest_general": {"transitions_in_1s": 2, "at_s": 1.0}, "busiest_classic": {"transitions_in_1s": 2, "at_s": 1.0},
                   "busiest_red": {"transitions_in_1s": 10, "at_s": 9.0}, "flagged": [row], "classic_flagged": [row]}
        real = flash_scan.screen_video
        flash_scan.screen_video = lambda *_a, **_k: planted   # a red flash at 9 s, the general detectors quiet at 1 s
        try:
            text, _ = scan.scan(f)
        finally:
            flash_scan.screen_video = real
        line = next(x for x in text.splitlines() if x.startswith("fix before anyone watches:") and "WCAG" in x)
        assert "red flashing" in line and "at 9.0 s" in line, line
        # a red-only pattern that is no WCAG flash names its own busiest second (it printed "0 changes in a second at None s")
        row = {"window": [0, 0, 64, 36], "general_max_per_s": 0, "general_at_s": None, "red_max_per_s": 10, "red_at_s": 3.0,
               "red_coherent_max_per_s": 0, "red_coherent_at_s": None}
        planted = {"busiest_general": {"transitions_in_1s": 0, "at_s": None}, "busiest_classic": {"transitions_in_1s": 2, "at_s": 1.0},
                   "busiest_red": {"transitions_in_1s": 2, "at_s": 1.0}, "flagged": [row], "classic_flagged": []}
        flash_scan.screen_video = lambda *_a, **_k: planted
        try:
            text, _ = scan.scan(f)
        finally:
            flash_scan.screen_video = real
        line = next(x for x in text.splitlines() if "motion or patterns" in x)
        assert "10 changes" in line and "3.0 s" in line, line




def spring_curve(t, f, d):
    """A damped spring from 0 to 1 (frequency f Hz, damping ratio d), written here apart from the tool."""
    import math
    w, x0 = 2 * math.pi * f, -1.0
    if d < 1:
        wd = w * math.sqrt(1 - d * d)
        return 1 + np.exp(-d * w * t) * (x0 * np.cos(wd * t) + (d * w * x0 / wd) * np.sin(wd * t))
    r = math.sqrt(d * d - 1)
    a, b = -w * (d - r), -w * (d + r)
    c2 = (-a * x0) / (b - a)
    return 1 + (x0 - c2) * np.exp(a * t) + c2 * np.exp(b * t)


def test_borrow_recovers_planted_springs_and_says_when_it_cannot():
    import borrow
    # the short moves are the 12 to 20 frames SKILL.md asks for; a grid made in move-relative units read 2.2 Hz as 5.0 there
    for f, d, dur in [(2.2, 0.45, 1.0), (3.0, 0.7, 0.5), (1.5, 0.9, 1.2), (4.0, 0.3, 0.8), (2.2, 0.45, 0.2), (2.2, 0.45, 0.25), (3.0, 0.7, 0.3)]:
        v = np.abs(np.diff(spring_curve(np.linspace(0, dur, 25), f, d)))
        fit = borrow.fit_spring_profile(v, dur=dur)
        assert fit["fitted"] and abs(fit["freq"] - f) <= 0.15 and abs(fit["damp"] - d) <= 0.06, ((f, d, dur), fit)
    s = np.linspace(0, 1, 25)
    glide = np.where(s < 0.5, 4 * s ** 3, 1 - (-2 * s + 2) ** 3 / 2)            # inOutCubic, the worked films' glide
    assert borrow.fit_spring_profile(np.abs(np.diff(glide)), dur=0.3)["fitted"] is False, "a glide is no spring"
    empty = borrow.fit_spring_profile([], dur=0.5)
    assert empty["fitted"] is False and empty["mse"] is None, empty



def test_borrow_takes_the_ground_from_the_border_and_the_octave_from_the_film():
    import borrow
    # broke: the largest colour cluster was taken for the ground (a film of dark paintings on paper got the paintings'
    # navy), and the accent was the most saturated colour even one step from the ground
    holds = [{"t0": 0, "t1": 4, "ground": "#f3eadb", "palette": [["#1d2a44", 0.6], ["#f3eadb", 0.3], ["#e0462c", 0.1]], "bands": [0.1]},
             {"t0": 4, "t1": 6, "ground": "#f2e9da", "palette": [["#1d2a44", 0.7], ["#f3eadb", 0.3]], "bands": [0.1]}]
    pal = borrow.extract_palette_and_ink({"holds": holds})
    assert pal["ground"] in ("#f3eadb", "#f2e9da") and pal["accent"] == "#e0462c" and pal["is_dark"] is False, pal
    # broke: Linden's 100 BPM, read as 200, was set at 18 frames a beat; the octave nearest the film's own beat is taken
    m = {"duration": 30.0, "events": [0.0], "sound": {"tempo": {"bpm": 200.0, "octave": [100.0, 400.0]}, "onsets": []}}
    assert borrow.compile_beat_table(m, near_fb=36)[0]["FB"] == 36
    assert borrow.compile_beat_table(m)[0]["FB"] == 18, "with no film's beat to go by, the tempo read is kept"


def rgb_clip(path, frames, fps=12):
    h, w = frames[0].shape[:2]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                    "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", str(path)], input=np.stack(frames).astype(np.uint8).tobytes(), check=True)


def borrow_planted(tmp, m, frames=None, fps=12):
    """vd borrow, through lean.main, on a small clip whose measures are planted in borrow's cache, so what borrow writes
    from a measure is checked without measuring a film: (film folder, dna.json, dna.gen.ts, REFERENCE.md, what it printed)."""
    import hashlib
    import json
    import shutil
    import measure
    import pack
    frames = [f.copy() for f in (frames or [np.full((36, 64, 3), 240, np.uint8)] * 12)]
    h, w = frames[0].shape[:2]
    frames[0][h // 2, w // 2] = np.random.default_rng().integers(0, 255, 3)   # a clip of its own each run: no other run's measures fit it
    clip = Path(tmp) / "ref.mp4"
    rgb_clip(clip, frames, fps)
    planted = Path.home() / ".vd" / "measures" / ("borrow-" + hashlib.sha1(clip.read_bytes()).hexdigest()[:12])
    planted.mkdir(parents=True, exist_ok=True)
    whole = {"version": measure.VERSION, "w": w, "h": h, "fps": fps, "duration": len(frames) / fps, "summary": {}, "events": [0.0],
             "cuts": [], "segments": [], "holds": [], "moves": [], "sound": None, **m}
    (planted / "measure.json").write_text(json.dumps(whole), encoding="utf-8")
    film = Path(tmp) / f"vd-test-borrowed-{Path(tmp).name[-6:]}"   # its own name: outputs go by a film folder's name
    said = io.StringIO()
    try:
        with contextlib.redirect_stdout(said):
            assert lean.main(["borrow", str(clip), "-o", str(film), "--like", "stet", "--k", "1"]) == 0
    finally:
        shutil.rmtree(planted, ignore_errors=True)
        shutil.rmtree(pack.sheets_root(clip), ignore_errors=True)
    read = lambda p: (film / p).read_text(encoding="utf-8")
    return film, json.loads(read("dna.json")), read("kit/dna.gen.ts"), read("REFERENCE.md"), said.getvalue()


def test_borrow_says_when_no_move_was_fitted_and_gives_no_spring_of_its_own():
    # broke: every move came back unfitted (HEX 0 of 4, il 0 of 27), and borrow wrote its own fallback spring
    # {freq 2.4, damp 0.48} and curve [0.2, 0.8, 0.2, 1] as DNA_SPRING and DNA_BEZIER, and REFERENCE.md said the
    # film's moves follow it; a film imported it as the reference's motion
    flat = [1.0] * 24                                     # an even speed: no spring of physics.ts's family makes it
    moves = [{"t0": 1.0 + i, "dur": 0.4, "peak": 0.5, "ease": [0.3, 0.4, 0.5, 0.8], "profile": flat, "ease_reliable": True} for i in range(3)]
    with tempfile.TemporaryDirectory() as tmp:
        _, dna, ts, ref, _ = borrow_planted(tmp, {"moves": moves})
    assert not any(mv["spring"]["fitted"] for mv in dna["springs"]), dna["springs"]
    assert dna["default_spring"] is None and dna["default_bezier"] is None, (dna["default_spring"], dna["default_bezier"])
    assert "export const DNA_SPRING = null" in ts and "export const DNA_BEZIER = null" in ts, ts
    assert "freq: 2.4" not in ref and "damp: 0.48" not in ref and "0.2, 0.8, 0.2, 1.0" not in ref, ref
    assert "no move was fitted" in ref.lower(), ref
    # one move that is a spring, among the even ones: the default is that one's, and says it comes from one move
    good = np.abs(np.diff(spring_curve(np.linspace(0, 0.5, 25), 3.0, 0.7)))
    moves.append({"t0": 5.0, "dur": 0.5, "peak": 0.2, "ease": [0.2, 0.9, 0.3, 1.0], "profile": list(good / good.max()), "ease_reliable": True})
    with tempfile.TemporaryDirectory() as tmp:
        _, dna, ts, ref, _ = borrow_planted(tmp, {"moves": moves})
    assert abs(dna["default_spring"]["freq"] - 3.0) <= 0.15 and abs(dna["default_spring"]["damp"] - 0.7) <= 0.06, dna["default_spring"]
    assert "1 of 4 moves" in ref, ref


def section(md, heading):
    """The text under one `## heading` of a page, up to the next heading."""
    part = md.split("## " + heading, 1)
    assert len(part) == 2, f"no heading {heading!r} in:\n{md}"
    return part[1].split("\n## ", 1)[0]


def test_borrow_leaves_the_world_and_idea_to_write_and_says_its_sync_against_chance():
    # broke: REFERENCE.md was one template for every film. "The formal idea" read "Events lock to a 150.0 BPM grid" for a
    # film whose events landed on an onset 0.286 of the time against 0.234 by chance, and "The world" and "What we
    # take" were filled with numbers, where TAKE-APART.md asks the reader to write them from the film
    sound = {"tempo": {"bpm": 150.0, "strength": 0.26, "octave": [75.0, 300.0]}, "onsets": [0.5, 1.0]}
    at_chance = {"sound": sound, "summary": {"sync_rate": 0.286, "sync_chance": 0.234, "tempo_bpm": 150.0}}
    with tempfile.TemporaryDirectory() as tmp:
        _, _, _, ref, _ = borrow_planted(tmp, at_chance)
    assert "lock to" not in ref.lower(), ref
    for heading in ("The world", "The formal idea", "What we take and what stays theirs"):
        body = section(ref, heading)
        assert "TAKE-APART.md" in body and not re.search(r"#[0-9a-f]{6}|BPM|spring\(", body), (heading, body)
    measured = section(ref, "Measured")
    assert "0.286" in measured and "0.234" in measured and "no more than chance" in measured, measured
    with tempfile.TemporaryDirectory() as tmp:
        _, _, _, ref, _ = borrow_planted(tmp, {"sound": sound, "summary": {"sync_rate": 0.548, "sync_chance": 0.208, "tempo_bpm": 150.0}})
    assert "above chance" in section(ref, "Measured"), ref
    with tempfile.TemporaryDirectory() as tmp:      # no tempo in its sound: the clock is borrow's own, and says so
        _, _, _, ref, _ = borrow_planted(tmp, {})
    assert "not the film's" in section(ref, "Measured"), ref


def test_borrow_takes_every_ground_with_its_time_and_keeps_the_accent_apart():
    # broke: grounds came only from holds. A film that never rests (HEX, 1.5 s of holds in 35 s) lost five of its seven
    # grounds; a red end card, the longest hold, was called the film's dark ground; il's dark room (#262521) was filed
    # as ink alone; and six near-identical off-whites filled the swatches, so il's blue chip never appeared
    def solid(c, n, chip=None):
        f = np.zeros((36, 64, 3), np.uint8)
        f[:] = c
        if chip:
            f[16:20, 29:35] = chip              # a small blue chip: an accent, not a ground
            f[26:29, 10:54] = (37, 36, 33)      # a line of dark type
        return [f.copy() for _ in range(n)]
    off1, off2, dark, green, yellow, purple, red, blue = ((246, 244, 243), (239, 237, 237), (38, 37, 33), (24, 156, 71), (255, 224, 0),
                                                          (126, 94, 188), (236, 62, 9), (32, 80, 255))
    frames = (solid(off1, 36, blue) + solid(off2, 18, blue) + solid(dark, 30) + solid(green, 12) + solid(yellow, 3)
              + solid(purple, 15) + solid(red, 12))                          # 12 a second: 3 s, 1.5, 2.5, 1, 0.25 (a flash), 1.25, 1
    holds = [{"t0": 0.2, "t1": 0.4, "ground": "#f6f4f3", "bands": [0.1], "palette": [["#f8f6f5", 0.5], ["#f6f5f4", 0.2], ["#f6f4f3", 0.1], ["#f7f6f5", 0.1], ["#252421", 0.1]]},
             {"t0": 3.2, "t1": 3.4, "ground": "#efeded", "bands": [0.1], "palette": [["#efeded", 0.6], ["#f5f4f3", 0.3], ["#252421", 0.1]]},
             {"t0": 9.5, "t1": 10.5, "ground": "#ec3e09", "bands": [0.1], "palette": [["#ec3e09", 0.9], ["#f2f2f6", 0.1]]}]
    with tempfile.TemporaryDirectory() as tmp:
        _, dna, _, ref, _ = borrow_planted(tmp, {"holds": holds}, frames=frames)
    pal = dna["palette"]
    rgb = lambda h: np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)
    near = lambda h, c, d=30: float(np.linalg.norm(rgb(h) - np.array(c, float))) < d
    seconds = lambda c: next((g["seconds"] for g in pal.get("grounds") or [] if near(g["hex"], c)), None)
    got = [seconds(c) for c in (off1, dark, green, purple, red)]
    assert all(s is not None and abs(s - want) <= 0.3 for s, want in zip(got, (4.5, 2.5, 1.0, 1.25, 1.0))), (got, pal)
    assert len(pal["grounds"]) == 5 and seconds(yellow) is None, ("a 0.25 s flash is no ground; the two off-whites are one", pal["grounds"])
    assert all(g["spans"] for g in pal["grounds"]) and near(pal["ground"], off1) and pal["is_dark"] is False, pal
    assert near(pal["accent"], blue, 60), ("the accent is the blue chip, never a ground", pal["accent"])
    sw = [s["hex"] for s in pal["swatches"]]
    assert all(not near(a, rgb(b), 20) for i, a in enumerate(sw) for b in sw[i + 1:]), ("near-identical swatches are one", sw)
    assert sum(s["weight"] for s in pal["swatches"]) <= 1.004, ("shares of the time held, each rounded to 3 places", pal["swatches"])
    measured = section(ref, "Measured")
    assert all(any(near(h, c) for h in re.findall(r"#[0-9a-f]{6}", measured)) for c in (off1, dark, green, purple, red)), measured


def test_borrow_labels_its_beat_table_and_keeps_every_cue():
    # broke: DNA_TIMES held beats with no unit (END 42.559 in a 17 s film), so a reader took them for seconds past the
    # film's end and threw the table away; and the cues stopped after 24 events (at 23.4 s of a 34.9 s film)
    events = [round(0.5 + 0.6 * i, 3) for i in range(30)]           # 30 events from 0.5 to 17.9 s
    sound = {"tempo": {"bpm": 150.0, "strength": 0.3, "octave": [75.0, 300.0]}, "onsets": []}
    with tempfile.TemporaryDirectory() as tmp:
        _, dna, ts, ref, _ = borrow_planted(tmp, {"duration": 18.5, "events": events, "cuts": events[::3], "sound": sound,
                                                  "summary": {"tempo_bpm": 150.0}})
    times, beat = dna["times"], dna["clock"]["FB"] / dna["clock"]["FPS"]
    assert times.get("UNIT") == "beats" and abs(times.get("BEAT_S", 0) - beat) < 1e-6, times
    secs = times.get("SECONDS") or {}
    assert [round(t, 2) for t in secs.get("EVENTS", [])] == [round(t, 2) for t in events], secs
    assert len(secs.get("CUTS", [])) == 10 and secs.get("END", 99) <= 18.5 and times["END"] > 18.5, ("END in beats lies past the end in seconds", times)
    assert len(dna["cues"]) == 30, f"every event is a cue, not the first 24: {len(dna['cues'])}"
    assert all(set(c) == {"name", "s", "beat"} and abs(c["s"] - c["beat"] * beat) < 0.002 for c in dna["cues"]), dna["cues"][:3]
    assert re.search(r"//[^\n]*DNA_TIMES[^\n]*beats[^\n]*\n", ts), ts
    assert "beats" in section(ref, "Measured") and "seconds" in section(ref, "Measured"), ref


def test_vd_borrow_says_what_it_wrote():
    # broke: through vd.py (lean.cmd_borrow) borrow printed only the folder's path; its summary lived in borrow.main
    with tempfile.TemporaryDirectory() as tmp:
        film, _, _, _, said = borrow_planted(tmp, {})
    lines = said.strip().splitlines()
    assert lines and lines[-1] == str(film), ("the last line is still the folder", lines[-3:])
    for what in ("dna.json", "dna.gen.ts", "REFERENCE.md", "grounds", "spring"):
        assert what in said, (what, said)


def test_evolve_for_a_repository_writes_its_counts_on_every_board():
    import evolve
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        old = lean.OUTROOT
        lean.OUTROOT = Path(tmp) / "out"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                evolve.build_tournament(name=str(Path(tmp) / "evo"), repo_dir=repo, reads_root=Path(tmp) / "reads", seed=1)
        finally:
            lean.OUTROOT = old
        boards = sorted((Path(tmp) / "out" / "evo" / "tournaments" / "t1").glob("*/BOARD.md"))
        assert len(boards) == 4 and all("1 functions" in b.read_text(encoding="utf-8") for b in boards), boards


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("new check fault checks passed")
