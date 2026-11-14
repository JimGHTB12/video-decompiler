#!/usr/bin/env python3
"""tools/space.py against films with known answers: a page that slides, a scene with two depths, one thing on a still
ground, and a picture with nothing to follow. Then the row it adds to a refill's compare.

  python tests/test_space.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import space  # noqa: E402

W, H, FPS, SECONDS = 640, 360, 30, 3


def speckle(seed, n, size, lo, hi):
    """A sheet much bigger than the frame with `n` small squares on it: things a tracker can follow. Returns it and its mask."""
    rng = np.random.default_rng(seed)
    sheet, mask = np.zeros((H * 3, W * 3), np.uint8), np.zeros((H * 3, W * 3), bool)
    for _ in range(n):
        x, y = int(rng.integers(0, W * 3 - size)), int(rng.integers(0, H * 3 - size))
        sheet[y:y + size, x:x + size] = int(rng.integers(lo, hi))
        mask[y:y + size, x:x + size] = True
    return sheet, mask


def window(sheet, x, y, zoom=1.0):
    """The frame's view of a sheet with its corner at (x, y), zoomed about that corner."""
    import cv2
    m = np.float32([[zoom, 0, -x * zoom], [0, zoom, -y * zoom]])
    return cv2.warpAffine(sheet.astype(np.float32), m, (W, H), flags=cv2.INTER_LINEAR)


def write(path, pictures):
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for pic in pictures:
        p.stdin.write(np.clip(pic, 0, 255).astype(np.uint8).tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return path


def films(d):
    far, _ = speckle(1, 900, 9, 70, 130)
    near, near_mask = speckle(2, 260, 22, 170, 250)
    n = FPS * SECONDS
    # a page: one sheet, slid and zoomed as one thing for the whole film
    page = write(d / "page.mp4", (window(far, 300 + 6 * k, 200 + 2 * k, 1 + 0.002 * k) + 16 for k in range(n)))
    # a scene: the same far sheet, and a near one passing in front of it three times as fast
    def two(k):
        back = window(far, 300 + 2 * k, 200) + 16
        front, cover = window(near, 200 + 7 * k, 150), window(near_mask.astype(np.uint8) * 255, 200 + 7 * k, 150) > 127
        back[cover] = front[cover]
        return back
    scene = write(d / "scene.mp4", (two(k) for k in range(n)))
    # one thing on a still ground: neither
    def one(k):
        pic = window(far, 300, 200) + 16
        pic[150:210, 40 + 5 * k:120 + 5 * k] = 240
        return pic
    local = write(d / "local.mp4", (one(k) for k in range(n)))
    blank = write(d / "blank.mp4", (np.full((H, W), 40.0) for _ in range(n)))
    return page, scene, local, blank


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        page, scene, local, blank = films(d)
        # broke: nothing in the skill could tell a film that slides a page from one that travels through a scene. It measured
        # how full the frame was instead, and a film that filled its frame with lines read fuller and was ranked lower
        got = space.read(page)
        assert got["sheet_move"] > 0.8 and got["scene_move"] < 0.05, f"one sheet slid and zoomed is a page, however far it travels: {got}"
        got = space.read(scene)
        assert got["scene_move"] > 0.8 and got["sheet_move"] < 0.05, f"a near thing passing a far one is a scene: no one slide explains both: {got}"
        got = space.read(local)
        assert got["scene_move"] < 0.05 and got["sheet_move"] < 0.05, f"one thing moving on a still ground is neither: most of the picture stayed put: {got}"
        got = space.read(blank)
        assert got["scene_move"] is None and got["sheet_move"] is None and got["readable"] == 0, f"a picture with nothing to follow isn't measured, and says so: {got}"
        assert space.read(scene) == space.read(scene), "the same film reads the same twice"
        said = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "space.py"), str(page)], capture_output=True, text=True, encoding="utf-8").stdout
        assert "(a page)" in said and "(a scene)" in said and "%" in said, f"run by hand it says both shares in words: {said}"

        # the row a film of its own gets against the video it learned from: one way only
        import measure
        assert measure.VERSION >= 5, "a measurement made before the summary said how a film moves is measured again"
        for film in (page, scene):
            subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), str(film), "--out", str(d / film.stem)], check=True, capture_output=True)
        made = json.loads((d / "scene" / "measure.json").read_text(encoding="utf-8"))["summary"]
        assert made["scene_move"] > 0.8 and "sheet_move" in made, f"measure.py keeps the reading in its summary: {made}"
        row = lambda rows: next((r for r in rows if r["metric"] == "scene_move"), None)
        off = row(measure.compare(d / "scene", d / "page", "refill"))
        assert off and off["ok"] is False and off["source"] > 0.8 and off["other"] < 0.05, f"a film that slides a page where its source moves as a scene is off: {off}"
        assert row(measure.compare(d / "page", d / "scene", "refill"))["ok"] is True, "a film may move as a scene where its source doesn't: the row asks one way only"
        assert row(measure.compare(d / "scene", d / "scene", "refill"))["ok"] is True
        assert row(measure.compare(d / "scene", d / "page", "rebuild")) is None, "an exact rebuild is held to its source move by move already"
        assert measure.judge("reach", 0.1, 0.17, 0.12) and not measure.judge("reach", 0.1, 0.35, 0.12) and measure.judge("reach", 0.1, 0.05, 0.0), \
            "past the line, and at least half as much of the time as the source; a source that does none asks for none"

    print("space checks passed")


if __name__ == "__main__":
    main()
