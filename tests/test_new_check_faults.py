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
