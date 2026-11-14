"""One picture of a composition at chosen moments, and what the engine knows did not draw there.

  python look.py ENTRY.tsx --at 2.3,10.4,12.9,15.0 -o look.jpg [--frames] [--composition ID] [--keep DIR] [--all]

Times are seconds (or frame numbers with --frames). All the moments are drawn by ONE raea process (`render --at`), so
start-up and bundling are paid once, not once a still. It waits its turn in the machine's render queue (raea_run's lock,
the same one raea_run.py takes) and times raea to the millisecond.

The picture: the moments as tiles in reading order, the time and frame printed on each, at most 1920 wide. A last row
that is not full is centred, so no empty square reads as a moment that did not draw.
The report, from raea's own data only (its render manifest and its layer masks, `--layers`), never from pixels:
  - text whose layout box is wholly outside the frame, or past an edge (clipped);
  - stamped layers (text, 3D parts, images, video) present at a moment that are frontmost on no pixel of it: not drawn,
    wholly covered or wholly off frame (the mask can't say which; a text box from the manifest narrows it);
  - a layer frontmost over nearly the whole frame, which blinds the mask to everything under it;
  - the render's own findings, anything it did not apply, and refusals.
What is printed is short: each kind of finding once, with how many there are, on which tiles, and its three worst cases,
text cut by the frame's edge first and marked as a fault. The whole report, every finding on every tile, is written
beside the picture (the picture's name and -report.txt: look-report.txt by default) and its path printed; --all prints it instead. A film whose camera moves over a page
printed hundreds of "outside the frame" lines, one per word per tile, and the few worth acting on were lost in them.
Engine: RAEA_BIN, else raea 0.1.1-rc4 (the first build with --layers), else raea on PATH.
"""
import argparse
import gzip
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import raea_run  # noqa: E402  the machine's render queue and the environment every agent renders with

DRAWN_KINDS = ("text", "mesh", "image", "video")


def engine():
    """raea, checked against the skill's pin and said on one line (raea_run.checked_binary): RAEA_BIN, else rc4 where
    this machine keeps it, else raea on PATH."""
    return raea_run.checked_binary()


def fps_of(entry: Path, comp, say=True):
    """The composition's fps before it is drawn, to turn seconds into frames: a number written in its <Composition ...
    fps={N}>, else the score.json beside the entry (the starters and the worked films write fps={FPS}, read from it),
    else 30, said on stderr. Only a guess: once raea has drawn, its manifest's fps is the truth, and the tiles use that.
    The plusone copy, at 60, read as 30 here, and its tiles said 4.00 s on frame 120."""
    import re
    src = entry.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"<Composition\b[^>]*>", src):
        tag = m.group(0)
        if comp and f'id="{comp}"' not in tag:
            continue
        f = re.search(r"fps=\{\s*([\d.]+)\s*\}", tag)
        if f:
            return float(f.group(1))
    score = entry.parent / "score.json"
    if score.is_file() and "score.json" in src + "".join(p.read_text(encoding="utf-8", errors="replace") for p in entry.parent.glob("*.tsx") if p != entry):
        try:
            fps = float(json.loads(score.read_text(encoding="utf-8")).get("fps") or 0)
        except (ValueError, AttributeError):
            fps = 0
        if fps > 0:
            return fps
    if say:
        print(f"look: {entry.name} gives no frame rate a look can read before drawing; seconds are read at 30 a second "
              "(the tiles say the composition's own times, from raea)", file=sys.stderr)
    return 30.0


def bundle_cache():
    """Where raea keeps the bundles it built, one .js per content key (seen on 0.1.1-rc4: %LOCALAPPDATA%/raea/cache/bundles)."""
    if os.environ.get("RAEA_BUNDLE_CACHE"):
        return Path(os.environ["RAEA_BUNDLE_CACHE"])
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "raea" / "cache" / "bundles" if base else Path.home() / ".cache" / "raea" / "bundles"


def bundles_now(folder: Path):
    """{name: (mtime, size)} of the bundles there, or None when there is no such folder."""
    if not folder.is_dir():
        return None
    return {f.name: (f.stat().st_mtime_ns, f.stat().st_size) for f in folder.glob("*.js")}


def bundle_said(before, after, lines, folder: Path):
    """What happened to the bundle, read from what raea wrote into its bundle cache while it held the queue (nothing
    else renders then). rc4 does not print its RAEA_BUNDLE_TRACE line on this path, so its silence was read as
    "cached" even after the film had changed; one film's maker saw "cached" on a first look and couldn't trust it."""
    built = [l.strip() for l in lines if l.strip().startswith("raea bundle:")]
    if built:
        return f"bundle: built afresh ({built[0][len('raea bundle:'):].strip()})"
    if before is None or after is None:
        return f"bundle: not known (no raea bundle cache at {folder})"
    # a bundle file is named by its content key; rc4 writes a file again even when it had the key, so a file that only
    # changed time says nothing; a name it did not have before is a bundle of sources it had never seen
    new = sorted(set(after) - set(before))
    if new:
        return f"bundle: built afresh, these sources had not been bundled before ({new[0]}, {after[new[0]][1] // 1024} KB)"
    again = sorted(n for n, v in after.items() if before.get(n) != v)
    return ("bundle: reused" + (f" ({again[0]})" if again else "") + ". raea keys its bundle cache on the sources' content, and these "
            "exact sources were bundled before: by an earlier look, or by another film made from the same starter")


LIGHT, DARK = 0.75, 0.15   # a ground at or over LIGHT is light on purpose, at or under DARK dark on purpose


def grounds(pngs):
    """{still name: the brightness (0-1) of its ground}: the median of a ring 4 % in from the edge. A film whose ground is
    light (one film's page) or dark (one film's space, 3 to 4 stops under mid grey) is so on purpose, and raea's exposure warnings,
    judged against mid grey, said so on every frame."""
    return light_frames(pngs, light=0.0)


def light_frames(pngs, light=LIGHT):
    """{still name: brightness} for the stills whose ground is at least `light` (see grounds)."""
    import numpy as np
    from PIL import Image
    out = {}
    for f in pngs:
        x = np.asarray(Image.open(f).convert("L"))
        h, w = x.shape
        e = max(4, round(min(w, h) * 0.04))
        ring = np.concatenate([x[:e].ravel(), x[-e:].ravel(), x[e:-e, :e].ravel(), x[e:-e, -e:].ravel()])
        g = float(np.median(ring)) / 255
        if g >= light:
            out[Path(f).name] = g
    return out


EXPOSURE = ("clip to white", "washed out", "over mid grey")
UNDER = ("under mid grey", "crush to black", "clip to black", "reads dark", "low-key")


def quiet_exposure(said, ground):
    """(lines kept, how many left out): over-exposure warnings about stills on a light ground, and under-exposure ones
    about stills on a dark ground, are left out. `ground`: {still name: brightness}."""
    kept, gone = [], 0
    for l in said:
        g = next((v for n, v in ground.items() if n in l), None)
        if g is not None and ((g >= LIGHT and any(k in l for k in EXPOSURE)) or (g <= DARK and any(k in l for k in UNDER))):
            gone += 1
        else:
            kept.append(l)
    return kept, gone


def draw(entry: Path, frames, out_dir: Path, comp=None):
    """raea renders every frame in one process. (queue wait s, raea s, rc, lines, what happened to the bundle)."""
    args = [engine(), "render", entry.name, "-o", str(out_dir) + os.sep, "--at", ",".join(map(str, frames)),
            "--manifest", str(out_dir / "render.json"), "--layers"]
    if comp:
        args += ["--composition", comp]
    t_q = time.monotonic()
    lock = raea_run.one_at_a_time(what=f"look {entry} {len(frames)} moments", kind="look")
    waited = time.monotonic() - t_q
    try:
        cache = bundle_cache()
        before = bundles_now(cache)
        env = raea_run.raea_env()
        env["RAEA_BUNDLE_TRACE"] = "1"   # so the look can say whether the bundle was cached or built again
        t0 = time.monotonic()
        p = subprocess.Popen(args, cwd=entry.parent, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=raea_run.NO_WINDOW, text=True, encoding="utf-8", errors="replace")
        job = raea_run.die_with_us(p)  # noqa: F841  raea ends if this process is stopped
        lines = []
        th = threading.Thread(target=lambda: lines.extend(l.rstrip() for l in p.stdout), daemon=True)
        th.start()
        try:
            p.wait(timeout=600)
        except subprocess.TimeoutExpired:
            raea_run.kill_tree(p)
        th.join(timeout=5)
        return waited, time.monotonic() - t0, p.returncode, lines, bundle_said(before, bundles_now(cache), lines, cache)
    finally:
        if lock is not None:
            lock.close()


def read_layers(path: Path):
    """(header, {frame: flat mask of layer values}) from NAME.layers (raea-wt systems/layers/src/file.rs, v1)."""
    d = gzip.decompress(path.read_bytes())
    assert d[:8] == b"RAEALAYR", "not a raea layers file"
    n = struct.unpack("<I", d[8:12])[0]
    head = json.loads(d[12:12 + n])
    at = head.get("at") or list(range(head["frames"]))
    p, masks, before = 12 + n, {}, None
    for f in at:
        c = struct.unpack("<I", d[p:p + 4])[0]
        p += 4
        if c == 0:
            masks[f] = before
            continue
        runs = struct.unpack(f"<{2 * c}H", d[p:p + 4 * c])
        p += 4 * c
        flat = []
        for v, k in zip(runs[::2], runs[1::2]):
            flat.extend([v] * k)
        masks[f] = before = flat
    return head, masks


def overlay(masks, frames, total, share=0.99):
    """The layer frontmost on `share` or more of the frame at every moment looked at, or None. Two films in one night met
    "mask blind" on every tile (a grain in an entry of its own; a soft dark patch drawn full-frame behind the words):
    the message said why and not what to do."""
    tops = []
    for f in frames:
        mask = masks.get(f)
        if mask is None:
            return None
        counts = {}
        for v in mask:
            counts[v] = counts.get(v, 0) + 1
        top, n = max(counts.items(), key=lambda kv: kv[1])
        if top in (0, 65535) or n / total < share:
            return None
        tops.append(top)
    return tops[0] if tops and len(set(tops)) == 1 else None


FLOOR = 30 / 1080   # the one floor the pages give: 30 px on a 1080-high frame, scaled with the frame's height


def small_words(man, floor=FLOOR):
    """One line naming the smallest words under the floor (raea's manifest gives each text box's size in px), or None.
    One film's look said "ok" on tiles holding small labels. The size is the text's own, before any scale a parent or a camera
    puts on it (the manifest has no other), and the line says so: it can miss words a camera shrinks (Stet's 19 px
    labels under a 1.2 camera are about 23 px on screen) and can name words a camera enlarges."""
    H = man["height"]
    seen = {}
    for fd in man.get("frames", []):
        for t in fd.get("text", []):
            size = t.get("size")
            if not size or t.get("opacity", 1) <= 0.01 or t["text"].startswith("[[") or size >= floor * H - 0.5:
                continue
            key = (t.get("loc", "?"), t["text"][:30])
            seen[key] = min(size, seen.get(key, size))
    if not seen:
        return None
    worst = sorted(seen.items(), key=lambda kv: kv[1])[:3]
    return (f"small words: {len(seen)} texts set under {floor * H:.0f} px ({floor * 1080:.0f} px at 1080), by their own size before any camera "
            "or parent scale (it misses words a camera shrinks and names words a camera enlarges; read the tiles): "
            + "; ".join(f"\u201c{txt}\u201d {size:.0f} px ({loc})" for (loc, txt), size in worst))


class Note(str):
    """One finding on one tile: its line, and what kind it is (KINDS), how bad (rank: larger is worse) and what it is
    about (key: the same text or layer seen on several tiles is one case)."""
    def __new__(cls, kind, rank, key, line):
        n = super().__new__(cls, line)
        n.kind, n.rank, n.key = kind, rank, key
        return n


# (kind, the heading it is printed under, a fault at a moment the viewer sees), in the order printed
KINDS = (("cut", "FAULT, text cut by the frame's edge while on screen", True),
         ("nothing", "drew no pixels (not drawn, wholly covered or wholly off frame)", False),
         ("box", "a text's layout box runs past the frame's edge while its letters, by their size and alignment, lie inside (look at the tile)", False),
         ("blind", "mask blind (one layer covers nearly the whole frame, so nothing under it can be checked)", False),
         ("3d", "not known for 3D parts (a part with no pixels in the mask may still have drawn: look at the tile)", False),
         ("outside", "text wholly outside the frame, not seen at that moment (a camera moving over a page puts much of it there)", False))


def outside_share(box, W, H):
    """How much of a box lies outside a W x H frame, 0 to 1."""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return 0.0
    ix, iy = max(0.0, min(x + w, W) - max(x, 0.0)), max(0.0, min(y + h, H) - max(y, 0.0))
    return 1.0 - ix * iy / (w * h)


INK = 0.6   # a letter's width as a share of the type's size, on the wide side so a cut word is not called whole (at 0.7 Plus One's whole "Dress", its display serif, was called cut)


def ink_box(t):
    """Where a text's letters are, estimated from its layout box, size, line count and alignment: raea's manifest gives
    the box, and a box can be far wider than its words. Plus One's "19", set right-aligned in a box 1311 px wide that ran
    870 px past the left edge, was whole on its tile and was called cut. A text on several lines fills its box's width."""
    x, y, w, h = t["box"]
    size, lines = t.get("size") or 0, t.get("lines") or 1
    if not size or lines > 1:
        return x, y, w, h
    ink = min(w, INK * size * max(len(l) for l in t["text"].split("\n")))
    align = (t.get("align") or "left").lower()
    x0 = x if align in ("left", "start", "justify") else x + w - ink if align in ("right", "end") else x + (w - ink) / 2
    return x0, y, ink, h


def distance_out(box, W, H):
    """How far a box wholly outside the frame lies from its nearest edge, in px."""
    x, y, w, h = box
    return max(0.0, -(x + w), -(y + h), x - W, y - H)


def edge_note(t, W, H):
    """What a text's place against a W x H frame's edge is, as a Note, or None when it lies inside. Four cases: the box
    wholly outside; the box reaching in while its letters stay wholly outside (nothing of the text is seen, so nothing
    is cut: the accepted Plus One's side cards, mostly off the frame, were called FAULT for this on its first look);
    letters across the edge (cut, the one fault); and the box across the edge with its letters inside."""
    x, y, w, h = t["box"]
    where = t.get("loc", "?")
    key, said = (where, t["text"][:40]), f"text \u201c{t['text'][:40]}\u201d"
    if x + w <= 0 or y + h <= 0 or x >= W or y >= H:
        far = distance_out(t["box"], W, H)
        # nearest the frame first: a word just off the edge is the likeliest mistake; one 2000 px away is the page
        return Note("outside", -far, key, f"outside the frame: {said} box {x:.0f},{y:.0f} {w:.0f}x{h:.0f}, {far:.0f} px from the edge ({where})")
    if not (x < -1 or y < -1 or x + w > W + 1 or y + h > H + 1):
        return None
    ix, iy, iw, ih = ink = ink_box(t)
    if ix + iw <= 0 or iy + ih <= 0 or ix >= W or iy >= H:
        far = distance_out(ink, W, H)
        return Note("outside", -far, key, f"outside the frame: {said} box {x:.0f},{y:.0f} {w:.0f}x{h:.0f} reaches in, its letters "
                                          f"{far:.0f} px outside the edge ({where})")
    if ix < -1 or iy < -1 or ix + iw > W + 1 or iy + ih > H + 1:
        share = outside_share(ink, W, H)
        return Note("cut", share, key, f"clipped: {said} layout box {x:.0f},{y:.0f} {w:.0f}x{h:.0f} runs past the frame, about "
                                       f"{100 * share:.0f}% of its letters outside ({where})")
    share = outside_share(t["box"], W, H)
    return Note("box", share, key, f"layout box past the edge: {said} box {x:.0f},{y:.0f} {w:.0f}x{h:.0f}, {100 * share:.0f}% of the box "
                                   f"outside, its {t.get('align') or 'left'}-aligned letters inside ({where})")


def report(out_dir: Path, frames, fps):
    """{frame: [Note]} and general lines, from the manifest and layer masks raea wrote."""
    per = {f: [] for f in frames}
    general = []
    man = json.loads((out_dir / "render.json").read_text(encoding="utf-8"))
    W, H = man["width"], man["height"]
    for fd in man.get("frames", []):
        f = fd["frame"]
        for t in fd.get("text", []):
            if t.get("opacity", 1) <= 0.01 or t["text"].startswith("[["):
                continue
            note = edge_note(t, W, H)
            if note:
                per.setdefault(f, []).append(note)
    small = small_words(man)
    if small:
        general.append(small)
    for x in man.get("findings") or []:
        general.append(f"render {x.get('level')}: {x.get('says')}")
    for x in man.get("not_applied") or []:
        general.append(f"not applied: {json.dumps(x)[:200]}")
    lp = out_dir / (man.get("layers") or "")
    if not man.get("layers") or not lp.is_file():
        general.append("no layer masks were written, so nothing can be said about what drew no pixels")
        return per, general
    head, masks = read_layers(lp)
    layers = head["layers"]
    parents = {l["parent"] for l in layers if l.get("parent")}
    parents |= {k.split("|")[0] for k in list(parents)}  # a parent named by its stamp alone
    total = head["mask"]["w"] * head["mask"]["h"]
    over = overlay(masks, frames, total)
    if over and not layers[over - 1].get("parent"):
        general.append("nothing is drawn over the film's ground at the moments looked at")   # its root, alone: a bare start
    elif over:
        l = layers[over - 1]
        general.append(f"overlay set aside: {l['kind']} {l['name']} ({l['loc']}) is frontmost on 99% or more of every moment looked at, "
                       "and the masks keep only the frontmost layer, so nothing under it can be checked for drawing. To check it, "
                       "look at a composition without it (the starter's film-look leaves out its grain; give your own overlay the same switch)")
    for f in frames:
        mask = masks.get(f)
        if mask is None:
            continue
        counts = {}
        for v in mask:
            counts[v] = counts.get(v, 0) + 1
        top, n_top = max(counts.items(), key=lambda kv: kv[1])
        if top == over:
            continue                                  # said once above, not on every tile
        if top not in (0, 65535) and n_top / total > 0.97:
            l = layers[top - 1]
            per[f].append(Note("blind", n_top / total, l["loc"], f"mask blind: {l['kind']} {l['name']} ({l['loc']}) is frontmost on {100 * n_top / total:.0f}% of the frame, "
                               "so nothing under it can be told apart (the masks keep only the frontmost layer)"))
            continue
        texts = {}
        for fd in man.get("frames", []):
            if fd["frame"] == f:
                texts = {t.get("loc"): t for t in fd.get("text", [])}
        # 3D parts: where no part covers a pixel the mask holds 0 (nothing stamped), not the page element behind the 3D
        # picture, so a root fill behind 3D always "drew nothing" (a false alarm on every 3D shot). And when the mask holds
        # none of the frame's 3D parts at all, it can't say anything about them.
        present = [i for i, l in enumerate(layers, start=1) if l["frames"][0] <= f <= l["frames"][1]]
        meshes = [i for i in present if layers[i - 1]["kind"] not in ("element", "text", "image", "video")]   # 3D: meshes, models and the like
        # A 3D part with no pixels in the mask is no evidence: makers saw every part of a lit instrument named "drew no
        # pixels" on tiles where it plainly drew. So 3D parts get one line, never one each.
        unseen = [i for i in meshes if not counts.get(i)]
        if unseen:
            per[f].append(Note("3d", len(unseen), f, f"not known for 3D parts: {len(unseen)} of {len(meshes)} hold no pixels in the mask, which also happens to parts that drew; look at the tile"))
        for i, l in enumerate(layers, start=1):
            a, b = l["frames"]
            if not (a <= f <= b) or counts.get(i):
                continue
            if l["kind"] not in ("element", "text", "image", "video") or (meshes and l["kind"] == "element" and not l.get("parent")):
                continue
            leaf = l["key"] not in parents and l["loc"] not in parents
            if l["kind"] in DRAWN_KINDS or (l["kind"] == "element" and leaf):
                sure = "" if f in (a, b) else " (it is present at another looked-at moment; it may be absent here)"
                t = texts.get(l["loc"])
                why = "not drawn, wholly covered or wholly off frame"
                if t is not None:
                    x, y, w, h = t["box"]
                    inside = x + w > 0 and y + h > 0 and x < head["width"] and y < head["height"]
                    why = "covered or not drawn (its box is in the frame)" if inside else "its box is off the frame"
                # text, pictures and video before bare elements; one at the edge of its life (sure) before one that may be absent
                per[f].append(Note("nothing", 2 * (l["kind"] in DRAWN_KINDS) + (not sure), (l["loc"], l["name"]),
                                   f"drew no pixels: {l['kind']} {l['name']!r} at {l['loc']}: {why}{sure}"))
    return per, general


def summary(per, frames, fps, worst=3):
    """The short report: for each kind with findings, one heading with how many cases (a text or a layer seen on several
    tiles is one case, at its worst), on which tiles, and its `worst` worst cases, each with the time of its worst tile."""
    tile_of = {f: k + 1 for k, f in enumerate(frames)}
    lines = []
    for kind, heading, fault in KINDS:
        cases = {}
        for f in frames:
            for n in per.get(f) or []:
                if getattr(n, "kind", None) != kind:
                    continue
                c = cases.setdefault(n.key, {"tiles": set(), "best": None})
                c["tiles"].add(tile_of[f])
                if c["best"] is None or n.rank > c["best"][0].rank:
                    c["best"] = (n, f)
        if not cases:
            continue
        tiles = sorted({t for c in cases.values() for t in c["tiles"]})
        ranked = sorted(cases.values(), key=lambda c: -c["best"][0].rank)
        lines.append(f"{'!! ' if fault else ''}{heading}: {len(cases)} on tile{'s' if len(tiles) > 1 else ''} {', '.join(map(str, tiles))}"
                     + (f"; the worst {min(worst, len(ranked))}:" if len(ranked) > 1 else ":"))
        for c in ranked[:worst]:
            n, f = c["best"]
            more = f" (and on {len(c['tiles']) - 1} more tile{'s' if len(c['tiles']) > 2 else ''})" if len(c["tiles"]) > 1 else ""
            lines.append(f"    {f / fps:6.2f} s  {n}{more}")
    return lines


def one_each(lines):
    """General lines, each said once: a warning raea gives for several stills (frame-00004.png, frame-00007.png) is one
    line with how many."""
    import re
    seen = {}
    for l in lines:
        k = re.sub(r"frame-\d+\.png", "frame-*.png", l)
        seen.setdefault(k, []).append(l)
    return [v[0] if len(v) == 1 else f"{k}  (on {len(v)} stills)" for k, v in seen.items()]


def tile_labels(frames, out_dir: Path, guess):
    """(a label per tile, the composition's fps): each frame's time is the frame over the frame rate raea drew the
    composition at (its manifest's fps), and only without a manifest over the guess made before drawing. lean passes
    frames, and look.py divided them by fps_of's 30 for a film at 60: "18.00 s f540" on a frame at 9 s."""
    fps = guess
    try:
        fps = float(json.loads((out_dir / "render.json").read_text(encoding="utf-8")).get("fps") or guess)
    except (OSError, ValueError):
        pass
    return [f"{f / fps:.2f} s  f{f}" for f in frames], fps


def sheet(pngs, labels, out: Path):
    from PIL import Image, ImageDraw, ImageFont
    n = len(pngs)
    cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4
    rows = -(-n // cols)
    first = Image.open(pngs[0])
    tw = min(first.width, 1920 // cols)
    th = round(first.height * tw / first.width)
    size = max(16, tw // 22)
    strip = size + 12          # the band above each tile that holds its time and frame: the stamp covered the picture's
    font = None                # top-left corner, where a film's act lines often are
    for face in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(face, size)
            break
        except OSError:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size)
        except TypeError:
            font = ImageFont.load_default()
    img = Image.new("RGB", (cols * tw, rows * (th + strip)), (16, 16, 16))
    d = ImageDraw.Draw(img)
    # a last row that is not full is centred: three moments in a grid of four left a dark square where a fourth tile
    # would be, and the first person shown one asked which moment had not drawn
    slack = (rows * cols - n) * tw // 2
    for k, (p, lab) in enumerate(zip(pngs, labels)):
        im = Image.open(p).convert("RGB")
        if im.size != (tw, th):
            im.draft("RGB", (tw, th))
            im = im.resize((tw, th), Image.BILINEAR)
        x, y = (k % cols) * tw + (slack if k // cols == rows - 1 else 0), (k // cols) * (th + strip)
        img.paste(im, (x, y + strip))
        d.rectangle((x, y, x + tw - 1, y + strip - 1), fill=(0, 0, 0))
        d.text((x + 8, y + 5), lab, fill=(255, 220, 60), font=font)
    img.save(out, quality=85)
    return img.size


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("entry")
    ap.add_argument("--at", required=True, help="moments, seconds (or frames with --frames), comma separated")
    ap.add_argument("--frames", action="store_true", help="--at is frame numbers")
    ap.add_argument("--composition")
    ap.add_argument("-o", dest="out", required=True)
    ap.add_argument("--keep", help="keep raea's stills, manifest and masks in this folder")
    ap.add_argument("--all", action="store_true", help="print every finding on every tile (always written beside the picture, as its name and -report.txt)")
    a = ap.parse_args()
    t_all = time.monotonic()
    entry = Path(a.entry).resolve()
    fps = fps_of(entry, a.composition, say=not a.frames)    # given frames, only the labels need it, and raea's manifest gives those
    raw = [float(v) for v in a.at.split(",") if v.strip()]
    frames = [int(round(v)) if a.frames else int(round(v * fps)) for v in raw]
    work = Path(a.keep).resolve() if a.keep else Path(tempfile.mkdtemp(prefix="look-"))
    if a.keep:
        # --keep once emptied whatever folder it was given, the film's own included, before anything was drawn. It now
        # takes only a folder that is new or empty, or one an earlier look kept (it holds this tool's mark), and never
        # the film's folder or one above it
        mark = work / ".look-kept"
        if work in (entry.parent, *entry.parent.parents):
            raise SystemExit(f"--keep {work} is the film's folder or holds it, and --keep clears the folder it is given: name a folder of its own")
        if work.exists() and not work.is_dir():
            raise SystemExit(f"--keep {work} is a file: name a folder")
        if work.is_dir() and any(work.iterdir()) and not mark.exists():
            raise SystemExit(f"--keep {work} holds files this tool did not put there, and --keep clears the folder it is given: name a new or empty folder")
        if entry.parent in work.parents:
            print(f"warning: --keep {work} is inside the film's folder; raea's render.json there makes the next look bundle again (keep it outside)", file=sys.stderr)
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        mark.write_text("kept by look.py --keep: the next --keep on this folder clears it\n", encoding="utf-8")
    work.mkdir(parents=True, exist_ok=True)
    uniq = sorted(set(frames))
    Path(a.out).resolve().parent.mkdir(parents=True, exist_ok=True)   # before the render: a missing folder once threw the stills away after it
    waited, ran, rc, lines, bundled = draw(entry, uniq, work, a.composition)
    pngs = sorted(work.glob("frame-*.png"))
    if rc != 0 or len(pngs) != len(uniq):
        bad = [l for l in lines if "REFUSED" in l or "error" in l.lower() or "panicked" in l] or lines[-6:]
        print(f"FAILED raea rc {rc}, {len(pngs)} of {len(uniq)} stills ({ran:.2f}s): " + " | ".join(bad[:4]))
        sys.exit(1)
    by_frame = dict(zip(uniq, pngs))  # raea names --at stills by their place in the list, not their frame
    t_sheet = time.monotonic()
    guess = fps
    labels, fps = tile_labels(frames, work, guess)
    if not a.frames and abs(fps - guess) > 1e-6:
        print(f"look: the composition runs at {fps:g} a second, not the {guess:g} the seconds were read at: the tiles are frames "
              f"{', '.join(map(str, frames))}, labelled with their true times; ask again with those times", file=sys.stderr)
    size = sheet([by_frame[f] for f in frames], labels, Path(a.out))
    t_sheet = time.monotonic() - t_sheet
    per, general = report(work, uniq, fps)
    full = []                                   # every finding on every tile: the file, and the screen with --all
    names = {"cut": "cut by the edge", "nothing": "drew no pixels", "box": "box past the edge", "blind": "mask blind", "3d": "3D not known", "outside": "outside the frame"}
    for k, f in enumerate(frames):
        notes = per.get(f) or []
        head = f"tile {k + 1}: {f / fps:6.2f} s  frame {f:4d}  "
        if not notes:
            print(head + "ok: nothing the engine knows went wrong")
        else:
            counts = {}
            for n in notes:
                counts[n.kind] = counts.get(n.kind, 0) + 1
            print(head + f"{len(notes)} to see: " + ", ".join(f"{c} {names[kd]}" for kd, c in sorted(counts.items(), key=lambda kv: [k for k, _, _ in KINDS].index(kv[0]))))
        full.append(head + ("ok" if not notes else f"{len(notes)} to see"))
        full += [f"    {n}" for n in notes]
        if a.all:
            for n in notes:
                print(f"    {n}")
    ground = grounds(pngs)
    general, gone = quiet_exposure(general, ground)
    said, gone2 = quiet_exposure([f"raea: {l.strip()}" for l in lines if "REFUSED" in l or l.lstrip().startswith(("warn", "error"))], ground)
    refused = [s for s in said if "REFUSED" in s]
    for g in refused:                                                     # what raea refused, before anything else
        print(f"  {g}")
    if not a.all:
        for l in summary(per, frames, fps):
            print(f"  {l}")
    for g in (general + [s for s in said if s not in refused] if a.all else one_each(general + [s for s in said if s not in refused])):
        print(f"  {g}")
    full += [""] + general + said
    if gone + gone2:
        n_light, n_dark = sum(g >= LIGHT for g in ground.values()), sum(g <= DARK for g in ground.values())
        print(f"  exposure: {gone + gone2} warnings left out: {n_light} of {len(pngs)} stills stand on a light ground (brightness {LIGHT} or more "
              f"at the edges) and {n_dark} on a dark one ({DARK} or less), light or dark on purpose; mid grey is not their measure")
    print(f"  {bundled}")
    whole = Path(a.out).resolve().with_name(Path(a.out).stem + "-report.txt")
    whole.write_text("\n".join(full) + "\n", encoding="utf-8")
    if not a.all:
        print(f"  everything, every finding on every tile: {whole} (or --all)")
    print(f"LOOK {Path(a.out).resolve()} {size[0]}x{size[1]}, {len(frames)} tiles  total {time.monotonic() - t_all:.2f}s "
          f"(queue {waited:.2f}s, raea {ran:.2f}s, sheet {t_sheet:.2f}s)")
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    import utf8  # noqa: F401
    main()
