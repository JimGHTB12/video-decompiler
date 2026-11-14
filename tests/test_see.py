#!/usr/bin/env python3
"""tools/see.py against clips whose motion is known exactly, stored without loss so every machine reads the same pictures.

  python tests/test_see.py [case ...]

Each case makes a film from a function of time, runs the tool, and compares what it says with what was drawn. Every
result prints as measured against true, so a pass can be judged for how close it was as well as whether it held.

What this doesn't test is compression. These films were x264 at crf 14 until the tests first ran on other machines, and
two answers turned out to depend on the encode. A real film is
compressed, so a pass here says the tool reads clean pictures right on this machine, and no more than that.
"""
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"))
import see  # noqa: E402

FPS, W, H = 30, 1280, 720
RESULTS, FAILED = [], []


def linear(u):
    return u


def out_cubic(u):
    return 1 - (1 - u) ** 3


def in_quad(u):
    return u * u


def smooth(u):
    return u * u * (3 - 2 * u)


def back_out(u, s=1.0):
    return 1 + (s + 1) * (u - 1) ** 3 + s * (u - 1) ** 2


def progress(curve, t, t0, dur):
    return curve(float(np.clip((t - t0) / dur, 0, 1)))


def crossing_of(curve, level, t0, dur):
    u = np.linspace(0, 1, 4001)
    v = np.array([curve(float(x)) for x in u])
    return t0 + dur * u[int(np.argmax(v >= level))]


def noise_ground(seed, w=W, h=H, base=None):
    """Textured ground with both broad patches and sharp specks, so flow has corners to hold."""
    rng = np.random.default_rng(seed)
    broad = cv2.resize(rng.random((h // 18, w // 18, 3), np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    fine = rng.random((h // 3, w // 3, 3), np.float32)
    fine = cv2.resize(fine, (w, h), interpolation=cv2.INTER_NEAREST)
    img = 40 + 150 * broad + 60 * fine
    for _ in range(420):
        x, y = int(rng.integers(0, w - 14)), int(rng.integers(0, h - 14))
        size = int(rng.integers(4, 14))
        img[y:y + size, x:x + size] = rng.integers(0, 255, 3)
    return np.clip(img, 0, 255).astype(np.uint8)


def flat_ground(colour=(38, 34, 30)):
    return np.full((H, W, 3), colour, np.uint8)


def flat_sprite(w, h, colour):
    return np.full((h, w, 3), colour, np.uint8), None


def textured_sprite(w, h, seed):
    rng = np.random.default_rng(seed)
    broad = cv2.resize(rng.random((max(2, h // 12), max(2, w // 12), 3), np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    img = np.clip(60 + 190 * broad, 0, 255)
    for _ in range(max(20, w * h // 2000)):
        x, y = int(rng.integers(0, max(1, w - 8))), int(rng.integers(0, max(1, h - 8)))
        s = int(rng.integers(3, 8))
        img[y:y + s, x:x + s] = rng.integers(0, 255, 3)
    return img.astype(np.uint8), None


def stamp(frame, sprite, x, y):
    """Draw sprite with its top-left at (x, y), to sub-pixel accuracy, into frame."""
    img, _ = sprite
    h, w = img.shape[:2]
    x0, y0 = int(np.floor(x)) - 2, int(np.floor(y)) - 2
    x1, y1 = x0 + w + 5, y0 + h + 5
    fh, fw = frame.shape[:2]
    if x1 <= 0 or y1 <= 0 or x0 >= fw or y0 >= fh:
        return
    m = np.float32([[1, 0, x - x0], [0, 1, y - y0]])
    layer = cv2.warpAffine(img, m, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR)
    alpha = cv2.warpAffine(np.full((h, w), 255, np.uint8), m, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR).astype(np.float32)[..., None] / 255
    ax0, ay0 = max(0, -x0), max(0, -y0)
    ax1, ay1 = min(x1 - x0, fw - x0), min(y1 - y0, fh - y0)
    fx0, fy0 = x0 + ax0, y0 + ay0
    region = frame[fy0:fy0 + ay1 - ay0, fx0:fx0 + ax1 - ax0]
    frame[fy0:fy0 + ay1 - ay0, fx0:fx0 + ax1 - ax0] = (region * (1 - alpha[ay0:ay1, ax0:ax1]) + layer[ay0:ay1, ax0:ax1] * alpha[ay0:ay1, ax0:ax1]).astype(np.uint8)


def render(path, seconds, draw, size=(W, H), fps=FPS):
    # stored without loss (-qp 0), so every machine reads the pictures that were drawn. As x264 at crf 14 a case read a
    # different film on each machine: the encoder's output changes with its build and its thread count, which it takes
    # from the machine's cores. The fast throw passed on 22 cores and failed on 2, and on GitHub's Mac the flat rise
    # failed on 1, 2 and 4 threads and passed on the encoder's own choice
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE, creationflags=see.NO_WINDOW)
    for i in range(int(round(seconds * fps))):
        p.stdin.write(draw(i / fps, i).tobytes())
    p.stdin.close()
    p.wait()
    assert p.returncode == 0


def read(path, out):
    model = see.analyse(path, out)
    json.loads((Path(out) / "motion.json").read_text(encoding="utf-8"))
    return model


def biggest_move(model, shot=0):
    moves = [(m, th) for th in model["shots"][shot]["things"] for m in th["moves"]]
    return max(moves, key=lambda x: x[0]["distance"]) if moves else (None, None)


def note(case, what, measured, true, ok):
    RESULTS.append((case, what, measured, true, ok))
    if not ok:
        FAILED.append(f"{case}: {what}: measured {measured}, true {true}")


def near(case, what, measured, true, tol):
    ok = measured is not None and abs(measured - true) <= tol
    note(case, what, None if measured is None else round(float(measured), 3), f"{true:.3f} +/- {tol:.3f}", ok)
    return ok


def equal(case, what, measured, true):
    note(case, what, measured, true, measured == true)


# Case 1: a flat bright card rises and decelerates. How far, which way, when.
def case_flat_rise(tmp):
    ground, card = flat_ground(), flat_sprite(300, 180, (240, 235, 225))
    t0, dur, dist = 1.0, 0.8, 220
    x, y0 = 300, 460
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, x, y0 - dist * progress(out_cubic, t, t0, dur))
        return f
    film = tmp / "flat_rise.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "flat_rise")
    m, th = biggest_move(model)
    equal("flat_rise", "shots", len(model["shots"]), 1)
    assert m is not None, "no move found"
    equal("flat_rise", "direction", see.direction_word(m["dx"], m["dy"]), "up")
    near("flat_rise", "distance px", m["distance"], dist, 0.08 * dist)
    near("flat_rise", "start s", m["t0"], crossing_of(out_cubic, 0.02, t0, dur), 0.07)
    near("flat_rise", "arrival s", m["t1"], crossing_of(out_cubic, 0.98, t0, dur), 0.1)
    equal("flat_rise", "shape", m["shape"], "decelerates")
    near("flat_rise", "width share", th["w"] / W, 300 / W, 0.04)
    near("flat_rise", "height share", th["h"] / H, 180 / H, 0.2)
    equal("flat_rise", "no overshoot", m["overshoot"], 0.0)


# Case 2: textured object on textured ground, constant speed right. Flow must not lose it in the texture.
def case_textured_right(tmp):
    ground, card = noise_ground(1), textured_sprite(220, 220, 2)
    t0, dur, dist = 0.7, 1.4, 340
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 200 + dist * progress(linear, t, t0, dur), 260)
        return f
    film = tmp / "tex.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "tex")
    m, _ = biggest_move(model)
    assert m is not None, "no move found"
    equal("textured_right", "direction", see.direction_word(m["dx"], m["dy"]), "right")
    near("textured_right", "distance px", m["distance"], dist, 0.1 * dist)
    near("textured_right", "start s", m["t0"], crossing_of(linear, 0.02, t0, dur), 0.08)
    near("textured_right", "arrival s", m["t1"], crossing_of(linear, 0.98, t0, dur), 0.1)
    equal("textured_right", "shape", m["shape"], "constant speed")
    equal("textured_right", "camera", model["shots"][0]["camera"]["state"], "locked")


# Case 3: one object, three moves, three eases, with rests between.
def case_ease_shapes(tmp):
    ground, card = flat_ground((30, 45, 60)), textured_sprite(180, 180, 3)
    moves = [(0.5, 0.9, in_quad, 260, 0), (2.0, 0.9, smooth, 0, 180), (3.5, 0.9, out_cubic, -220, 0)]
    def draw(t, i):
        x, y = 240.0, 180.0
        for s, d, c, dx, dy in moves:
            p = progress(c, t, s, d)
            x += dx * p
            y += dy * p
        f = ground.copy()
        stamp(f, card, x, y)
        return f
    film = tmp / "ease.mp4"
    render(film, 5, draw)
    model = read(film, tmp / "ease")
    all_moves = sorted((m for th in model["shots"][0]["things"] for m in th["moves"] if m["distance"] > 60), key=lambda m: m["t0"])
    equal("ease_shapes", "moves found", len(all_moves), 3)
    for (m, (s, d, c, dx, dy), want) in zip(all_moves, moves, ("accelerates", "eased both ends", "decelerates")):
        tag = c.__name__
        equal("ease_shapes", f"{tag} shape", m["shape"], want)
        near("ease_shapes", f"{tag} distance", m["distance"], abs(dx) + abs(dy), 0.1 * (abs(dx) + abs(dy)))
        near("ease_shapes", f"{tag} half-time fraction", m["t50"], (crossing_of(c, 0.5, s, d) - crossing_of(c, 0.02, s, d)) / (crossing_of(c, 0.98, s, d) - crossing_of(c, 0.02, s, d)), 0.12)


# Case 4: overshoot: does it find the overshoot's size and settling, on a flat card at 1280 width?
def case_overshoot(tmp):
    ground, card = flat_ground((25, 30, 35)), flat_sprite(260, 160, (60, 170, 240))
    t0, dur, dist = 0.8, 1.0, 240
    curve = lambda u: back_out(u, 1.2)
    us = np.linspace(0, 1, 2001)
    true_over = (max(curve(float(u)) for u in us) - 1) * dist
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 360 + dist * progress(curve, t, t0, dur), 300)
        return f
    film = tmp / "over.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "over")
    m, _ = biggest_move(model)
    assert m is not None, "no move found"
    near("overshoot", "distance px", m["distance"], dist, 0.1 * dist)
    note("overshoot", "overshoot found", round(m["overshoot"], 1), f"{true_over:.1f}", m["overshoot"] > 0)
    near("overshoot", "overshoot px", m["overshoot"], true_over, max(5.0, 0.35 * true_over))
    near("overshoot", "settled s", m["settled"], t0 + dur, 0.2)


# Case 5: camera pushes in while a thing moves on its own: the two must not be confused.
def case_camera_vs_object(tmp):
    world, card = noise_ground(5, W + 400, H + 240), textured_sprite(200, 200, 6)
    t0, dur, s1 = 0.5, 2.0, 1.18
    a0, ad, adist = 1.0, 1.0, 260
    cx, cy = (W + 400) / 2, (H + 240) / 2
    def draw(t, i):
        s = 1 + (s1 - 1) * progress(smooth, t, t0, dur)
        m = np.float32([[s, 0, W / 2 - s * cx], [0, s, H / 2 - s * cy]])
        f = cv2.warpAffine(world, m, (W, H), flags=cv2.INTER_LINEAR)
        wx = 300 + adist * progress(linear, t, a0, ad)
        wy = 320.0
        sx, sy = W / 2 + s * (wx - cx + 200), H / 2 + s * (wy - cy + 120)
        card_img = cv2.resize(card[0], None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
        stamp(f, (card_img, None), sx, sy)
        return f
    film = tmp / "cam.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "cam")
    shot = model["shots"][0]
    cam = shot["camera"]
    equal("camera_vs_object", "camera state", cam["state"], "moving")
    zooms = sorted(cam["zooms"], key=lambda z: -abs(z["to"] - z["from"]))
    assert zooms, "no zoom found"
    z = zooms[0]
    near("camera_vs_object", "zoom end", z["to"] / z["from"], s1, 0.025)
    near("camera_vs_object", "zoom start s", z["t0"], crossing_of(smooth, 0.02, t0, dur), 0.25)
    near("camera_vs_object", "zoom peak s", z["peak_at"], t0 + dur / 2, 0.25)
    equal("camera_vs_object", "zoom shape", z["shape"], "eased both ends")
    m, th = biggest_move(model)
    assert m is not None, "object lost"
    equal("camera_vs_object", "object direction", see.direction_word(m["dx"], m["dy"]), "right")
    near("camera_vs_object", "object distance", m["distance"], adist * 1.09, 0.2 * adist)
    near("camera_vs_object", "object start s", m["t0"], crossing_of(linear, 0.02, a0, ad), 0.12)
    big_others = [x for x in shot["things"] if x is not th and x["area_share"] > 0.04 and sum(k["distance"] for k in x["moves"]) > 60]
    equal("camera_vs_object", "no phantom large movers", len(big_others), 0)


# Case 6: two things overlapping in time.
def case_two_overlapping(tmp):
    ground = flat_ground((32, 32, 40))
    a, b = flat_sprite(200, 120, (235, 235, 235)), flat_sprite(160, 160, (60, 200, 90))
    def draw(t, i):
        f = ground.copy()
        stamp(f, a, 240, 480 - 200 * progress(out_cubic, t, 1.0, 0.8))
        stamp(f, b, 700 + 300 * progress(smooth, t, 1.2, 0.8), 180)
        return f
    film = tmp / "two.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "two")
    shot = model["shots"][0]
    moves = [(m, th) for th in shot["things"] for m in th["moves"] if m["distance"] > 80]
    equal("two_overlapping", "two movers", len({id(th) for _, th in moves}), 2)
    assert len(moves) >= 2
    up = next((m for m, _ in moves if see.direction_word(m["dx"], m["dy"]) == "up"), None)
    right = next((m for m, _ in moves if see.direction_word(m["dx"], m["dy"]) == "right"), None)
    assert up and right, "directions not recovered"
    near("two_overlapping", "lead of B after A s", right["t0"] - up["t0"], crossing_of(smooth, 0.02, 1.2, 0.8) - crossing_of(out_cubic, 0.02, 1.0, 0.8), 0.1)
    rels = [r for r in shot["relations"] if r["overlap"]]
    equal("two_overlapping", "overlap reported", len(rels) >= 1, True)
    equal("two_overlapping", "count at once", model["census"]["max_at_once"], 2)


def moving_scene(tmp, name, seed, hold=None, every=None):
    """A textured card crossing a textured ground at constant speed, with a held span or repeated frames applied."""
    ground, card = noise_ground(seed), textured_sprite(200, 200, seed + 1)
    def frame_at(i):
        f = ground.copy()
        stamp(f, card, 60 + 6.0 * i, 260)
        return f
    def draw(t, i):
        k = i
        if hold and hold[0] <= i < hold[1]:
            k = hold[0]
        if every and every[0] <= i < every[1]:
            k = every[0] + (i - every[0]) // every[2] * every[2]
        return frame_at(k)
    film = tmp / f"{name}.mp4"
    render(film, 5, draw)
    return film


def case_freeze(tmp):
    film = moving_scene(tmp, "freeze", 7, hold=(60, 105))
    model = read(film, tmp / "freeze")
    stills = [s for shot in model["shots"] for s in shot["stills"]]
    longest = max(stills, key=lambda x: x["dur"], default=None)
    assert longest is not None, "freeze not found"
    near("freeze", "start s", longest["t0"], 2.0, 0.08)
    near("freeze", "end s", longest["t1"], 3.5, 0.08)
    equal("freeze", "frame-identical", longest["kind"], "frame-identical")
    equal("freeze", "entered at speed", longest["entered_at_speed"], True)
    equal("freeze", "left at speed", longest["left_at_speed"], True)
    equal("freeze", "no other long stills", len([s for s in stills if s is not longest and s["dur"] >= 0.5]), 0)
    equal("freeze", "timecheck finds it, labelled", any(f["kind"] == "freeze" and abs(f["start"] - 2.0) < 0.2 for f in model["timecheck"]["findings"]), True)
    equal("freeze", "timecheck line in transcript", "timecheck.py freeze" in (tmp / "freeze" / "SEE.md").read_text(encoding="utf-8"), True)


def case_deliberate_rest(tmp):
    ground, card = noise_ground(9), textured_sprite(220, 180, 10)
    def draw(t, i):
        f = ground.copy()
        x = 200 + 400 * progress(out_cubic, t, 0.6, 0.8) - 300 * progress(smooth, t, 3.0, 0.8)
        stamp(f, card, x, 300)
        return f
    film = tmp / "rest.mp4"
    render(film, 4.5, draw)
    model = read(film, tmp / "rest")
    stills = [s for shot in model["shots"] for s in shot["stills"] if s["dur"] >= 0.8]
    equal("deliberate_rest", "one long rest", len(stills), 1)
    assert stills
    near("deliberate_rest", "rest ends s", stills[0]["t1"], 3.0, 0.2)
    equal("deliberate_rest", "entered from rest, not at speed", stills[0]["entered_at_speed"], False)


def case_stutter(tmp):
    film = moving_scene(tmp, "stutter", 11, every=(60, 96, 3))
    model = read(film, tmp / "stutter")
    spans = [c for shot in model["shots"] for c in shot["stepped"]]
    equal("stutter", "one stepped stretch", len(spans), 1)
    assert spans
    near("stutter", "start s", spans[0]["t0"], 2.0, 0.17)
    near("stutter", "end s", spans[0]["t1"], 3.2, 0.17)
    equal("stutter", "held for frames", spans[0]["hold_frames"], 3)
    equal("stutter", "film cadence norm", model["cadence"]["label"], "every frame is new")


def case_clean_controls(tmp):
    film = moving_scene(tmp, "clean", 13)
    model = read(film, tmp / "clean")
    equal("clean", "no repeated-frame spans", sum(len(s["cadence"]) for s in model["shots"]), 0)
    equal("clean", "no stills", sum(len(s["stills"]) for s in model["shots"]), 0)
    equal("clean", "no colour events", sum(len(s["colour"]) for s in model["shots"]), 0)
    equal("clean", "no sharpness events", sum(len(s["sharpness"]) for s in model["shots"]), 0)
    equal("clean", "one shot", len(model["shots"]), 1)
    equal("clean", "camera locked", model["shots"][0]["camera"]["state"], "locked")


def case_dissolve_vs_cut(tmp):
    a, b, c = noise_ground(21), noise_ground(22), noise_ground(23)
    card = textured_sprite(160, 160, 24)
    def draw(t, i):
        if t < 2.0:
            f = a.copy()
        elif t < 2.6:
            k = (t - 2.0) / 0.6
            f = (a.astype(np.float32) * (1 - k) + b.astype(np.float32) * k).astype(np.uint8)
        elif t < 4.6:
            f = b.copy()
        else:
            f = c.copy()
        if t < 2.0 or t >= 2.6:
            stamp(f, card, 100 + 25 * t * (1 if t < 4.6 else 1.5), 300)
        return f
    film = tmp / "dissolve.mp4"
    render(film, 6.5, draw)
    model = read(film, tmp / "dissolve")
    joins = [s["join"]["kind"] for s in model["shots"]]
    equal("dissolve_vs_cut", "joins", joins, ["start", "dissolve", "cut"])
    if len(model["shots"]) >= 3:
        d = model["shots"][1]["join"]
        near("dissolve_vs_cut", "dissolve starts", model["shots"][0]["t1"], 2.0, 0.1)
        near("dissolve_vs_cut", "dissolve ends", model["shots"][1]["t0"], 2.6, 0.1)
        near("dissolve_vs_cut", "hard cut at", model["shots"][2]["t0"], 4.6, 0.05)


def case_colour_change(tmp):
    ground = noise_ground(31)
    def draw(t, i):
        f = ground.copy()
        if 2.0 <= t < 3.5:
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(int) + 15) % 180
            f = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return f
    film = tmp / "colour.mp4"
    render(film, 5, draw)
    model = read(film, tmp / "colour")
    equal("colour_change", "one shot, no false cut", len(model["shots"]), 1)
    evs = [c for s in model["shots"] for c in s["colour"]]
    equal("colour_change", "one colour event", len(evs), 1)
    assert evs
    near("colour_change", "change at", evs[0]["t"], 2.0, 0.07)
    near("colour_change", "reverts at", evs[0].get("reverts_at", 99), 3.5, 0.07)
    text = (tmp / "colour" / "SEE.md").read_text(encoding="utf-8")
    equal("colour_change", "plain sentence for an unexplained change", "with no cut and nothing moving at that moment" in text, True)
    equal("colour_change", "compares with the rest of the film", "only sudden whole-picture colour change in this film" in text, True)


def case_soft(tmp):
    ground = noise_ground(41)
    def draw(t, i):
        f = ground.copy()
        return cv2.GaussianBlur(f, (0, 0), 3.0) if 1.5 <= t < 2.7 else f
    film = tmp / "soft.mp4"
    render(film, 4.2, draw)
    model = read(film, tmp / "soft")
    evs = [c for s in model["shots"] for c in s["sharpness"]]
    equal("soft", "one sharpness event", len(evs), 1)
    assert evs
    near("soft", "falls at", evs[0]["t"], 1.5, 0.07)
    near("soft", "recovers at", evs[0]["t_end"], 2.7, 0.1)
    note("soft", "detail fell", round(evs[0]["ratio"], 2), "under 0.6", evs[0]["ratio"] < 0.6)
    equal("soft", "plain sentence for an unexplained change", "with no cut and nothing moving at that moment" in (tmp / "soft" / "SEE.md").read_text(encoding="utf-8"), True)
    equal("soft", "one shot, no false cut", len(model["shots"]), 1)


def case_transcript(tmp):
    """Lines budget, and it reads as a transcript: no invented object names, shots listed, and a move given numbers."""
    ground, card = flat_ground((25, 25, 30)), flat_sprite(300, 180, (240, 235, 225))
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 300, 460 - 220 * progress(out_cubic, t, 1.0, 0.8))
        return f
    film = tmp / "text.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "text")
    text = (tmp / "text" / "SEE.md").read_text(encoding="utf-8")
    note("transcript", "line count", len(text.splitlines()), "under 80", len(text.splitlines()) < 80)
    equal("transcript", "has a shot heading", "### Shot 1" in text, True)
    equal("transcript", "says rises", "rises" in text, True)
    equal("transcript", "says region", "region" in text, True)




# --- Held-out cases, written after the tool's thresholds were set: other sizes, rates, speeds and contrasts. ---


def case_small_overshoot_1080p(tmp):
    """24 fps at 1920x1080, a pale card with a real 6 px overshoot."""
    size, fps = (1920, 1080), 24
    ground = np.full((1080, 1920, 3), (46, 40, 36), np.uint8)
    card = flat_sprite(420, 300, (235, 240, 245))
    t0, dur, dist = 1.0, 0.9, 300
    s = 0.8
    curve = lambda u: back_out(u, s)
    us = np.linspace(0, 1, 2001)
    true_over = (max(curve(float(u)) for u in us) - 1) * dist
    print("    true overshoot", round(true_over, 2))
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 700, 600 - dist * progress(curve, t, t0, dur))
        return f
    film = tmp / "small_over.mp4"
    render(film, 3, draw, size=size, fps=fps)
    model = read(film, tmp / "small_over")
    m, th = biggest_move(model)
    assert m is not None, "no move found"
    near("small_overshoot", "distance px", m["distance"], dist, 0.08 * dist)
    equal("small_overshoot", "direction", see.direction_word(m["dx"], m["dy"]), "up")
    near("small_overshoot", "overshoot px", m["overshoot"], true_over, 4.0)
    near("small_overshoot", "width px", th["w"], 420, 60)


def case_fast_throw(tmp):
    """A card crossing most of the frame in eight frames: beyond what flow can follow; it must not claim a precise wrong number."""
    ground = noise_ground(61)
    card = textured_sprite(180, 140, 62)
    t0, dur, dist = 1.0, 8 / 30, 900
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 100 + dist * progress(smooth, t, t0, dur), 300)
        return f
    film = tmp / "throw.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "throw")
    moves = [(m, th) for shot in model["shots"] for th in shot["things"] for m in th["moves"]]
    assert moves, "no move found"
    m, _ = max(moves, key=lambda x: x[0]["distance"])
    text = (tmp / "throw" / "SEE.md").read_text(encoding="utf-8")
    speeds = [int(v) for v in __import__("re").findall(r"(\d+) px/s", text)]
    note("fast_throw", "no impossible speed printed", max(speeds, default=0), "at most 30 px a frame at 480 wide", max(speeds, default=0) <= see.FAST * W / 480 * FPS)
    equal("fast_throw", "one line at the top instead of a mark on each", ("could only be estimated" in text, "(too fast to follow)" in text, "two estimates disagree" in text), (True, False, False))
    # how far, for a move this fast, depends on how the film happened to be compressed: over 36 encodes of this film it read 442
    # to 752 px, always short of the 900. It was held to within 40%, which 11 of the 36 met. What is promised is the mark
    note("fast_throw", "distance not wildly off, and flagged", (round(m["distance"], 1), m["trust"]), f"{dist}: a third of it to 40% over, trust not 'good'", dist / 3 <= m["distance"] <= 1.4 * dist and m["trust"] != "good")
    equal("fast_throw", "direction", see.direction_word(m["dx"], m["dy"]), "right")


def case_low_contrast(tmp):
    """Card 18 grey levels above its ground."""
    ground = np.full((H, W, 3), (70, 70, 70), np.uint8)
    card = flat_sprite(260, 180, (88, 88, 88))
    t0, dur, dist = 1.0, 0.8, 300
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 300 + dist * progress(smooth, t, t0, dur), 280)
        return f
    film = tmp / "low.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "low")
    m, _ = biggest_move(model)
    assert m is not None, "no move found"
    near("low_contrast", "distance px", m["distance"], dist, 0.15 * dist)
    equal("low_contrast", "direction", see.direction_word(m["dx"], m["dy"]), "right")


def case_carry_through_cut(tmp):
    """Movement before a hard cut continues in the same direction after it, then a cut where it doesn't."""
    a_bg, b_bg, c_bg = noise_ground(71), noise_ground(72), noise_ground(73)
    card = textured_sprite(200, 200, 74)
    def draw(t, i):
        if t < 2.0:
            f = a_bg.copy(); stamp(f, card, 100 + 300 * t, 260)
        elif t < 4.0:
            f = b_bg.copy(); stamp(f, card, 100 + 300 * (t - 2.0), 400)
        else:
            f = c_bg.copy(); stamp(f, card, 1000 - 300 * (t - 4.0), 260)
        return f
    film = tmp / "carry.mp4"
    render(film, 6, draw)
    model = read(film, tmp / "carry")
    equal("carry_through_cut", "three shots", len(model["shots"]), 3)
    if len(model["shots"]) == 3:
        equal("carry_through_cut", "carries through first cut", "carries through" in (model["shots"][1].get("carry") or ""), True)
        note("carry_through_cut", "direction change noted at second", model["shots"][2].get("carry"), "movement changes across the cut", "changes" in (model["shots"][2].get("carry") or ""))


def case_jump_in_continuous_shot(tmp):
    """A textured pan with 30 frames removed: the same scene leaps forward in one frame."""
    world = noise_ground(81, W + 800, H)
    def draw(t, i):
        k = i if i < 60 else i + 30
        x = 7.0 * k
        m = np.float32([[1, 0, -x], [0, 1, 0]])
        return cv2.warpAffine(world, m, (W, H), flags=cv2.INTER_LINEAR)
    film = tmp / "jump.mp4"
    render(film, 4, draw)
    model = read(film, tmp / "jump")
    joins = [(round(s["t0"], 2), s["join"]["kind"]) for s in model["shots"]]
    found = next((j for j in joins[1:] if abs(j[0] - 2.0) <= 0.1), None)
    note("jump_cut", "a boundary near 2.0 s", joins, "a join near 2.0 s", found is not None)
    cam = model["shots"][0]["camera"]
    equal("jump_cut", "camera pans in first shot", cam["state"], "moving")


def case_pan_vs_object(tmp):
    """Camera pans right across a textured world while a card moves left through it on its own."""
    world = noise_ground(91, W + 900, H)
    card = textured_sprite(180, 180, 92)
    pan_total, card_world = 500, 300
    def draw(t, i):
        x = pan_total * progress(smooth, t, 0.5, 2.5)
        m = np.float32([[1, 0, -x], [0, 1, 0]])
        f = cv2.warpAffine(world, m, (W, H), flags=cv2.INTER_LINEAR)
        wx = 1100 - card_world * progress(linear, t, 1.0, 1.5)
        stamp(f, card, wx - x, 320)
        return f
    film = tmp / "pan.mp4"
    render(film, 3.5, draw)
    model = read(film, tmp / "pan")
    cam = model["shots"][0]["camera"]
    pans = sorted(cam["moves"], key=lambda m: -m["distance"])
    equal("pan_vs_object", "camera moving", cam["state"], "moving")
    assert pans, "no pan found"
    p = pans[0]
    equal("pan_vs_object", "pan direction (picture slides left)", see.direction_word(p["dx"], p["dy"]), "left")
    near("pan_vs_object", "pan distance", p["distance"], pan_total, 0.12 * pan_total)
    m, _ = biggest_move(model)
    assert m is not None, "object lost"
    near("pan_vs_object", "object travel net of pan", m["distance"], card_world, 0.25 * card_world)
    equal("pan_vs_object", "object direction", see.direction_word(m["dx"], m["dy"]), "left")


def case_fade(tmp):
    """Fade to black, then fade up, against textured pictures."""
    a, b = noise_ground(101), noise_ground(102)
    def draw(t, i):
        if t < 1.5:
            return a.copy()
        if t < 2.2:
            return (a.astype(np.float32) * (2.2 - t) / 0.7).astype(np.uint8)
        if t < 2.9:
            return (b.astype(np.float32) * (t - 2.2) / 0.7).astype(np.uint8)
        return b.copy()
    film = tmp / "fade.mp4"
    render(film, 4, draw)
    model = read(film, tmp / "fade")
    kinds = [s["join"]["kind"] for s in model["shots"]]
    equal("fade", "joins", kinds, ["start", "fade_through"])
    if len(model["shots"]) == 2:
        near("fade", "fade starts s", model["shots"][0]["t1"], 1.5, 0.15)
        near("fade", "fade ends s", model["shots"][1]["t0"], 2.9, 0.15)
    print("    fade shots:", [(round(s["t0"], 2), round(s["t1"], 2), s["join"]["kind"]) for s in model["shots"]])


def case_small_hue_on_motion(tmp):
    """A 12-degree hue step while a card moves: small and not on a still picture."""
    ground, card = noise_ground(111), textured_sprite(200, 200, 112)
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 60 + 180 * t, 260)
        if 2.0 <= t < 3.2:
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(int) + 6) % 180
            f = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return f
    film = tmp / "small_hue.mp4"
    render(film, 4.5, draw)
    model = read(film, tmp / "small_hue")
    evs = [c for s in model["shots"] for c in s["colour"]]
    note("small_hue", "event at 2.0 s", [round(e["t"], 2) for e in evs], "one near 2.0", any(abs(e["t"] - 2.0) <= 0.1 for e in evs))
    equal("small_hue", "one shot", len(model["shots"]), 1)


def case_soft_slight(tmp):
    """Slight blur, sigma 1.2 at 1920 wide, on detailed ground."""
    size = (1920, 1080)
    ground = noise_ground(121, 1920, 1080)
    def draw(t, i):
        return cv2.GaussianBlur(ground, (0, 0), 1.2) if 1.5 <= t < 2.7 else ground.copy()
    film = tmp / "soft_slight.mp4"
    render(film, 4.2, draw, size=size)
    model = read(film, tmp / "soft_slight")
    evs = [c for s in model["shots"] for c in s["sharpness"]]
    note("soft_slight", "event at 1.5 s", [(round(e["t"], 2), round(e["ratio"], 2)) for e in evs], "one near 1.5", any(abs(e["t"] - 1.5) <= 0.1 for e in evs))


def case_pop_in(tmp):
    """A plain element appears in a single frame and stays."""
    ground = flat_ground((30, 34, 40))
    label = flat_sprite(260, 90, (230, 230, 230))
    def draw(t, i):
        f = ground.copy()
        if t >= 1.5:
            stamp(f, label, 500, 500)
        return f
    film = tmp / "pop.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "pop")
    ch = [c for s in model["shots"] for c in s["changes"]]
    note("pop_in", "appears near 1.5 s", [(round(c["t0"], 2), c["what"]) for c in ch], "appears at 1.5", any(c["what"] == "appears" and abs(c["t0"] - 1.5) <= 0.1 for c in ch))
    equal("pop_in", "one shot", len(model["shots"]), 1)


def case_handheld(tmp):
    """Small random wander of a textured scene: not a sequence of big camera moves, not many moving things."""
    world = noise_ground(131, W + 120, H + 120)
    rng = np.random.default_rng(4)
    path = np.cumsum(rng.normal(0, 0.6, (300, 2)), axis=0)
    path = np.array([np.convolve(path[:, k], np.ones(12) / 12, "same") for k in range(2)]).T
    def draw(t, i):
        m = np.float32([[1, 0, -60 + path[i, 0]], [0, 1, -60 + path[i, 1]]])
        return cv2.warpAffine(world, m, (W, H), flags=cv2.INTER_LINEAR)
    film = tmp / "handheld.mp4"
    render(film, 5, draw)
    model = read(film, tmp / "handheld")
    shot = model["shots"][0]
    equal("handheld", "one shot", len(model["shots"]), 1)
    note("handheld", "things moving", len(shot["things"]), "at most 1", len(shot["things"]) <= 1)
    note("handheld", "camera wander reported", round(shot["camera"]["wander"], 1), "above 4 px", shot["camera"]["wander"] > 4)
    print("    handheld camera:", shot["camera"]["state"], [(round(m["distance"]), see.direction_word(m["dx"], m["dy"])) for m in shot["camera"]["moves"]][:5])



# --- Stepped motion, swaps that are cuts, pop-ins that aren't, and scattered small things. ---


def pan_frame(world, x):
    return cv2.warpAffine(world, np.float32([[1, 0, -x], [0, 1, 0]]), (W, H), flags=cv2.INTER_LINEAR)


def case_stepped_big_pan(tmp):
    """A fast pan held for 5 frames at a time: each release leaps 150 px and looks like a cut, but it's the same scene moving on."""
    world = noise_ground(141, W + 3200, H)
    def draw(t, i):
        k = i
        if 60 <= i < 90:
            k = 60 + (i - 60) // 5 * 5
        return pan_frame(world, 30.0 * k)
    film = tmp / "stepped.mp4"
    render(film, 4, draw)
    model = read(film, tmp / "stepped")
    equal("stepped_big_pan", "no cuts in it", len(model["shots"]), 1)
    spans = [c for shot in model["shots"] for c in shot["stepped"]]
    equal("stepped_big_pan", "one stepped stretch", len(spans), 1)
    assert spans
    equal("stepped_big_pan", "held for frames", spans[0]["hold_frames"], 5)
    near("stepped_big_pan", "start s", spans[0]["t0"], 2.0, 0.17)
    near("stepped_big_pan", "end s", spans[0]["t1"], 3.0, 0.2)
    equal("stepped_big_pan", "said in the transcript", "one new picture every 5 frames" in (tmp / "stepped" / "SEE.md").read_text(encoding="utf-8"), True)


def case_stepped_flat_graphic(tmp):
    """A card on a plain ground stuttering at 0.17 s holds, then moving smoothly again."""
    ground, card = flat_ground((28, 30, 36)), flat_sprite(340, 220, (236, 232, 220))
    def draw(t, i):
        k = i
        if 45 <= i < 85:
            k = 45 + (i - 45) // 5 * 5
        f = ground.copy()
        stamp(f, card, 40 + 9.0 * k, 240)
        return f
    film = tmp / "stepped_flat.mp4"
    render(film, 4, draw)
    model = read(film, tmp / "stepped_flat")
    equal("stepped_flat_graphic", "no cuts in it", len(model["shots"]), 1)
    spans = [c for shot in model["shots"] for c in shot["stepped"]]
    equal("stepped_flat_graphic", "one stepped stretch", len(spans), 1)
    assert spans
    equal("stepped_flat_graphic", "held for frames", spans[0]["hold_frames"], 5)


def case_held_montage_is_cuts(tmp):
    """Unrelated stills held 5 frames each: the rhythm of a stutter, but every change really is a new picture."""
    pics = [noise_ground(150 + k) for k in range(9)]
    def draw(t, i):
        return pics[min(i // 5, 8)].copy()
    film = tmp / "montage.mp4"
    render(film, 1.5, draw)
    model = read(film, tmp / "montage")
    equal("held_montage_is_cuts", "reports no stepped motion", sum(len(s["stepped"]) for s in model["shots"]), 0)
    joins = sum(s["join"].get("count", 1) for s in model["shots"][1:])
    note("held_montage_is_cuts", "every change is a cut", joins, 8, joins == 8)


def case_on_twos_throughout(tmp):
    """A whole film animated on twos is a film-wide cadence, not a fault in one place."""
    world = noise_ground(161, W + 1000, H)
    def draw(t, i):
        return pan_frame(world, 4.0 * (i // 2 * 2))
    film = tmp / "twos.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "twos")
    equal("on_twos_throughout", "said once for the film", model["cadence"].get("stepped_throughout"), 2)
    equal("on_twos_throughout", "not listed shot by shot", sum(len(s["stepped"]) for s in model["shots"]), 0)
    equal("on_twos_throughout", "one shot", len(model["shots"]), 1)


def case_graphic_swap_is_a_cut(tmp):
    """One small graphic replaced by another in a single frame on a plain ground: under a tenth of the pixels, still a cut."""
    ground = flat_ground((24, 24, 28))
    a, b = textured_sprite(260, 120, 171), textured_sprite(260, 120, 172)
    def draw(t, i):
        f = ground.copy()
        if t < 1.5:
            stamp(f, a, 200, 300)
        else:
            stamp(f, b, 760, 200)
        return f
    film = tmp / "swap.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "swap")
    equal("graphic_swap_is_a_cut", "two shots", len(model["shots"]), 2)
    if len(model["shots"]) == 2:
        near("graphic_swap_is_a_cut", "cut at s", model["shots"][1]["t0"], 1.5, 0.05)


def case_added_element_isnt_a_cut(tmp):
    """A second graphic joins one that stays: not a cut, however suddenly it arrives."""
    ground = flat_ground((24, 24, 28))
    a, b = textured_sprite(320, 160, 173), textured_sprite(320, 160, 174)
    def draw(t, i):
        f = ground.copy()
        stamp(f, a, 200, 280)
        if t >= 1.5:
            stamp(f, b, 720, 280)
        return f
    film = tmp / "added.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "added")
    equal("added_element_isnt_a_cut", "one shot", len(model["shots"]), 1)


def case_burst_is_one_change(tmp):
    """Four unrelated frames in a row between two pictures: one fast change, not a stack of no-length shots."""
    a, b = noise_ground(175), noise_ground(176)
    burst = [noise_ground(177 + k) for k in range(4)]
    def draw(t, i):
        if i < 45:
            return a.copy()
        return burst[i - 45].copy() if i < 49 else b.copy()
    film = tmp / "burst.mp4"
    render(film, 3, draw)
    model = read(film, tmp / "burst")
    equal("burst_is_one_change", "two shots", len(model["shots"]), 2)
    if len(model["shots"]) == 2:
        equal("burst_is_one_change", "one join", model["shots"][1]["join"]["kind"], "flurry")
        near("burst_is_one_change", "second shot starts s", model["shots"][1]["t0"], 49 / FPS, 0.1)


def dust_film(tmp, name, seed, count, radius, ground, grain=0.0):
    rng = np.random.default_rng(seed)
    x, y = rng.uniform(40, W - 40, count), rng.uniform(40, H - 40, count)
    angle = rng.uniform(0, 2 * np.pi, count)
    speed = rng.uniform(1.5, 4.0, count)
    vx, vy = speed * np.cos(angle), speed * np.sin(angle)
    noise = np.random.default_rng(seed + 1)
    def draw(t, i):
        f = ground.copy()
        for k in range(count):
            px = (x[k] + vx[k] * i) % W
            py = (y[k] + vy[k] * i) % H
            cv2.circle(f, (int(px), int(py)), radius, (235, 235, 235), -1, cv2.LINE_AA)
        if grain:
            f = np.clip(f.astype(np.float32) + noise.normal(0, grain, f.shape), 0, 255).astype(np.uint8)
        return f
    film = tmp / f"{name}.mp4"
    render(film, 3, draw)
    return film


def case_scattered_dust(tmp):
    """Thirty small dots drifting their own ways across a plain ground, each 12 px wide."""
    film = dust_film(tmp, "dust", 181, 30, 6, flat_ground((30, 32, 38)))
    model = read(film, tmp / "dust")
    sc = model["shots"][0].get("scattered")
    assert sc, "scattered small things not reported"
    note("scattered_dust", "count about 30", sc["count"], "30 within 40%", abs(sc["count"] - 30) <= 12)
    note("scattered_dust", "rough size", round(sc["size_px"], 1), "12 px across, within a factor of 2", 6 <= sc["size_px"] <= 24)
    note("scattered_dust", "spread over the frame", sc["cells"], "at least 12 of 24", sc["cells"] >= 12)
    equal("scattered_dust", "said in the transcript", "Scattered small things" in (tmp / "dust" / "SEE.md").read_text(encoding="utf-8"), True)


def case_scattered_on_texture(tmp):
    """Sparks over a detailed ground, which is harder: the sparks must still be counted."""
    film = dust_film(tmp, "sparks", 183, 18, 5, noise_ground(184))
    model = read(film, tmp / "sparks")
    sc = model["shots"][0].get("scattered")
    note("scattered_on_texture", "found", None if not sc else sc["count"], "reported", bool(sc))


def case_no_scatter_without_dust(tmp):
    """None reported for a plain moving card, a locked textured picture, or film grain."""
    ground, card = flat_ground((30, 32, 38)), flat_sprite(340, 200, (236, 232, 220))
    def draw(t, i):
        f = ground.copy()
        stamp(f, card, 100 + 6.0 * i, 240)
        return f
    moving = tmp / "card_only.mp4"
    render(moving, 3, draw)
    equal("no_scatter", "single moving card", read(moving, tmp / "card_only")["shots"][0].get("scattered"), None)
    grainy = dust_film(tmp, "grain_only", 185, 0, 1, noise_ground(186), grain=5.0)
    equal("no_scatter", "film grain only", read(grainy, tmp / "grain_only")["shots"][0].get("scattered"), None)



CASES = {k[5:]: v for k, v in list(globals().items()) if k.startswith("case_")}


def main():
    wanted = sys.argv[1:] or list(CASES)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in wanted:
            try:
                CASES[name](tmp)
                print(f"done {name}")
            except Exception:
                FAILED.append(f"{name}: error")
                traceback.print_exc()
    print()
    width = max((len(r[1]) for r in RESULTS), default=10)
    for case, what, measured, true, ok in RESULTS:
        print(f"{'ok ' if ok else 'BAD'} {case:<17} {what:<{width}}  measured {measured}  true {true}")
    print(f"\n{len(RESULTS) - len([r for r in RESULTS if not r[4]])} of {len(RESULTS)} checks passed; {len(FAILED)} failing or errored.")
    for f in FAILED:
        print("  FAIL " + f)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
