#!/usr/bin/env python3
"""A contact sheet of a video, every frame stamped: how a reader that can't play a film watches it.

  python sheet.py VIDEO -o sheet.jpg [--from A --to B] [--every 0.25] [--cols 6] [--width 320]
  python sheet.py VIDEO -o sheets/move.jpg --native [--from A --to B] [--cols 8] [--rows 6] [--width 240]
  python sheet.py VIDEO -o sheets/film.jpg --fps 6 [--cols 8] [--rows 8]
  python sheet.py FOLDER -o stills.jpg [--labels 12,40,96] [--cols 4] [--width 480]

--every is seconds between frames, one frame looked up at a time: fine for a glance.
--native is every frame of the window, sought half way before its first frame (film_diff.seek_frame, so rounding never
lands a frame late) and stopped after its last, each stamped with its frame number and time.
--fps is an even sample of the whole film, for the overview.
A FOLDER of stills (the frames a render wrote with --at) becomes one sheet in file-name order, each stamped with its
label, or its file name when no labels are given: twenty frames looked at in one glance.

Read motion from --native sheets. Tiles are equal steps of time, so how far a thing moved between two tiles is its
speed, and a tile equal to the one before is a held frame. Measured on films with planted faults: a reader given ten
frames a second missed a stutter that the same reader found at once from every frame. Use --fps 4 to 6 to find the
moments, then --native through each change and each join.

With --native or --fps a long stretch is split across several files (NAME_000.jpg, NAME_001.jpg, ...), --cols by --rows
tiles each, and each file is printed.

--native stamps each frame with its own time from the file, so a variable-rate video (a screen recording, often) reads
true. Frame number over frame rate stamped 3.00 s on a frame shown at 4.00 s. Because --native decodes only the stretch
asked for, damage outside that stretch no longer fails a standalone --native sheet (scan.windows still checks the whole
film first when vd pack builds motion sheets).
"""
import argparse
import functools
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from film_diff import NO_WINDOW, check_window, ffprobe, fps_of, frame_times, seek_frame, shown_index, variable_rate  # noqa: E402

MAX_FRAMES = 240


def probe(video):
    raw = ffprobe(video)
    return raw["w"], raw["h"], fps_of(raw, "r_frame_rate"), raw["duration"]


@functools.lru_cache(maxsize=8)
def strip_font(size=13):
    """The stamp's face: a bold at `size` px where the system has one, else Pillow's own at `size` px (Pillow 10.1 and
    later), else its small bitmap face. Cached by size across every tile and sheet."""
    from PIL import ImageFont
    for face in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(face, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


STRIP = 18   # px: the band above each tile that holds its stamp


def stamp(im, text):
    """The picture with a band of STRIP px above it holding `text` (its time and frame): nothing of the picture is
    covered. The stamp sat on the picture's top-left corner, where a film's act lines often are, and two readers could not
    check those words."""
    out = Image.new("RGB", (im.width, im.height + STRIP), (0, 0, 0))
    out.paste(im, (0, STRIP))
    ImageDraw.Draw(out).text((3, 2), text, fill=(255, 255, 0), font=strip_font())
    return out


MAX_MP = 40   # megapixels: one film's maker asked for --width 3200 and got a 403-megapixel sheet that nothing could open


def sane(cols, rows, w, h):
    """Refuse a sheet nobody can open, saying what --width means."""
    mp = cols * w * rows * h / 1e6
    if mp > MAX_MP:
        raise SystemExit(f"a sheet of {cols * w} x {rows * h} ({mp:.0f} megapixels) is past what an image viewer opens (the limit "
                         f"here is {MAX_MP}). --width is the width of one tile, not of the sheet: with {cols} columns, "
                         f"--width {max(80, int(1920 / cols))} makes a sheet about 1920 wide.")


def board(tiles, cols, out):
    w, h = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sane(cols, rows, w, h)
    sheet = Image.new("RGB", (w * cols, h * rows), (40, 40, 40))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(Path(out), quality=85)


def folder(a):
    """A folder of stills on one sheet, in file-name order."""
    files = sorted(p for p in Path(a.video).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if not files:
        raise SystemExit(f"no pictures in {a.video}")
    labels = [x.strip() for x in a.labels.split(",")] if a.labels else [p.stem for p in files]
    if len(labels) != len(files):
        raise SystemExit(f"{len(labels)} labels for {len(files)} pictures")
    tiles = []
    for p, label in zip(files, labels):
        im = Image.open(p).convert("RGB")
        tiles.append(stamp(im.resize((a.width, int(round(a.width * im.height / im.width / 2) * 2)), Image.LANCZOS), label))
    board(tiles, a.cols, a.out)
    print(f"{len(tiles)} stills -> {a.out}")


_UNSET = object()


def every_frame(a, src_w, src_h, rate, duration, times=_UNSET, quiet=False):
    """One decode pass: every frame of the window (--native) or an even sample of it (--fps)."""
    end = min(a.end if a.end is not None else duration, duration)
    h = int(round(a.width * src_h / src_w / 2) * 2)
    vf = f"scale={a.width}:{h}:flags=area"
    step = 1.0 / rate
    if a.fps:
        vf, step = f"fps={a.fps}," + vf, 1.0 / a.fps
        # an even sample is stamped by its own clock (from + n / fps): no frame's packet time is read (D8)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{a.start:.4f}", "-to", f"{end:.4f}", "-i", a.video, "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        times = first = last = None
    else:
        # every frame's own time, so a stamp is true when frames don't come at one rate; a regular clock when the file has none
        if times is _UNSET:
            if getattr(a, "frame_times", None):
                loaded = np.load(a.frame_times)
                times = None if len(loaded) == 0 else loaded
            else:
                times = frame_times(a.video)
        # only the file's own packet times say where a seek lands: with an estimated clock (a raw H.264 stream has no packet
        # times and no seek index) frames are picked by number from a decode from the start (an R2 review's finding)
        # and packets before 0 (preroll) are never shown, so where there are any the frames are picked the same way
        seekable = times is not None and bool(times[0] >= 0)
        times = np.arange(int(duration * rate) + 2) / rate if times is None else times
        first = int(np.searchsorted(times, a.start - 1e-6))    # the first source frame at or after --from
        first = max(first, int(np.count_nonzero(times < 0)))   # a preroll packet is never shown: the window starts at the first shown
        # seek half way before `first` (seek_frame): a plain -ss rounded past `first` landed a frame late and shifted stamps
        if first >= len(times):
            raise SystemExit("no frames in that window")
        last = max(first, int(np.searchsorted(times, end - 1e-6)) - 1)
        count = last - first + 1
        # setpts=N/TB gives rawvideo monotonic frame numbers after a seek on 1 ms-timebase WebM files (frames stay 1-to-1)
        if seekable:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{seek_frame(times, first):.6f}", "-i", str(a.video),
                   "-vf", f"{vf},setpts=N/TB", "-fps_mode", "passthrough", "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        else:
            a0, b0 = shown_index(times, first), shown_index(times, last)    # packet numbers as the decode counts its pictures
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(a.video), "-vf", f"select='between(n\\,{a0}\\,{b0})',{vf},setpts=N/TB",
                   "-fps_mode", "passthrough", "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    import decode
    size, per = a.width * h * 3, a.cols * a.rows
    out = Path(a.out)
    tiles, files, n = [], [], 0

    def flush():
        if not tiles:
            return
        name = out.with_name(f"{out.stem}_{len(files):03d}{out.suffix}")
        board(tiles, a.cols, name)
        files.append(name)
        tiles.clear()

    # checked (decode.py): a decoder that fails or stops early leaves no sheets, so no reader is given half a film
    try:
        for buf in decode.pictures(cmd, size, a.video, expect=None if a.fps else last - first + 1):
            t = a.start + n * step
            label = f"{t:6.2f}s" if a.fps else f"f{first + n} {times[min(first + n, len(times) - 1)]:.2f}s"
            tiles.append(stamp(Image.frombytes("RGB", (a.width, h), buf), label))
            n += 1
            if len(tiles) == per:
                flush()
    except SystemExit:
        for f in files:
            f.unlink(missing_ok=True)
        raise
    flush()
    if not files:
        raise SystemExit("no frames in that window")
    if len(files) == 1:                                     # one sheet keeps the name it was asked for
        files[0].replace(out)
        files[0] = out
    if not quiet:
        for f in files:
            print(f)
        pace = None if a.fps else "at a variable rate, each stamped with its own time" if variable_rate(times) else f"{rate:g} a second"
        print(f"{n} frames -> {len(files)} sheet{'s' if len(files) > 1 else ''}" + ("" if a.fps else f" (every frame, {pace})"))


def native_stretch(video, out, start, end, cols=6, rows=8, width=320, probed=None, times=_UNSET):
    """Write one --native stretch in-process without starting a new Python interpreter (pack.py)."""
    src_w, src_h, rate, duration = probed or probe(str(video))
    check_window(start, end, duration, str(video))
    tile_h = int(round(width * src_h / src_w / 2) * 2)
    sane(cols, rows, width, tile_h)
    a = argparse.Namespace(video=str(video), out=str(out), start=start, end=end, fps=None, cols=cols, rows=rows, width=width, frame_times=None)
    every_frame(a, src_w, src_h, rate, duration, times=times, quiet=True)


BATCH = 48   # stills per ffmpeg call: under ffmpeg's select parser limit and Windows's command line (as measure.BATCH)


def one_still(video, t, width):
    """The picture `-ss t` lands on, as one ffmpeg call made it: the first frame at or after t, scaled to width."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-vf", f"scale={width}:-2",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, creationflags=NO_WINDOW)
    return Image.open(io.BytesIO(p.stdout)).convert("RGB") if p.stdout else None


def every_still(video, times, width, src_w, src_h):
    """[(t, picture)] for --every: for each time the frame one `-ss t` call returned (the first frame at or after t,
    read from the file's packet times), fetched in batches of BATCH from one seek each instead of one ffmpeg a tile.
    A time past the last frame gives nothing, as before. A file that can't be sought by frame (packet_clock) keeps one
    call a still."""
    from film_diff import packet_clock, seek_frame
    clock, seekable = packet_clock(video)
    if not seekable:
        return [(t, im) for t in times for im in [one_still(video, t, width)] if im is not None]
    # the height scale=W:-2 gives: the source's shape at this width, rounded to the nearest even number as ffmpeg rounds
    h = (width * src_h + src_w) // (2 * src_w) * 2
    # the first frame at or after t, as ffmpeg finds it in whole ticks; a frame time here is its packet time less the
    # file's start, which can come out a hair under t (2.8 - 2.5 = 0.29999999999999982), so a millionth is allowed: a real
    # frame before t is at least one tick (1/90000 s or more) earlier
    want = [int(np.searchsorted(clock, round(t, 3) - 1e-6, side="left")) for t in times]
    frames, got, size = sorted({f for f in want if f < len(clock)}), {}, width * h * 3
    for b in range(0, len(frames), BATCH):
        part = frames[b:b + BATCH]
        pick = "+".join(f"eq(n\\,{f - part[0]})" for f in part)
        p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{seek_frame(clock, part[0]):.6f}", "-i", video,
                            "-vf", f"select='{pick}',scale={width}:{h}", "-fps_mode", "passthrough", "-frames:v", str(len(part)),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, creationflags=NO_WINDOW)
        got.update({f: Image.frombytes("RGB", (width, h), p.stdout[k * size:(k + 1) * size]) for k, f in enumerate(part) if (k + 1) * size <= len(p.stdout)})
    return [(t, got[f]) for t, f in zip(times, want) if f in got]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--to", dest="end", type=float)
    ap.add_argument("--every", type=float, default=0.25)
    ap.add_argument("--native", action="store_true", help="every frame of the source, once each")
    ap.add_argument("--fps", type=float, help="an even sample, this many frames a second")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--rows", type=int, default=8, help="rows on each sheet with --native or --fps")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--labels", help="for a folder of stills: one label a picture, separated by commas")
    ap.add_argument("--frame-times", help=argparse.SUPPRESS)  # pre-read packet times from pack.py, so one pack reads them once
    a = ap.parse_args()
    if Path(a.video).is_dir():
        return folder(a)
    if a.native and a.fps:
        raise SystemExit("--native is every frame; --fps is a sample. Choose one.")
    src_w, src_h, rate, duration = probe(a.video)
    if a.every <= 0 or (a.fps is not None and a.fps <= 0):  # --every 0 laid out 240 copies of one frame
        raise SystemExit(f"--every {a.every:g}" + (f" --fps {a.fps:g}" if a.fps is not None else "") + ": the spacing of frames is a number above 0")
    check_window(a.start, a.end, duration, a.video)
    tile_h = int(round(a.width * src_h / src_w / 2) * 2)
    if a.native or a.fps:
        sane(a.cols, a.rows, a.width, tile_h)                      # one sheet of --cols by --rows, checked before any work
    else:
        n = min(MAX_FRAMES, int(((a.end if a.end is not None else duration) - a.start) / a.every) + 1)
        sane(a.cols, (n + a.cols - 1) // a.cols, a.width, tile_h)
    if a.native or a.fps:
        return every_frame(a, src_w, src_h, rate, duration)
    end = a.end if a.end is not None else duration
    times, t = [], a.start
    while t < end and len(times) < MAX_FRAMES:
        times.append(round(t, 3))
        t += a.every
    if len(times) == MAX_FRAMES:
        print(f"capped at {MAX_FRAMES} frames: use a shorter window, a larger --every, or --native, which has no cap")
    tiles = []
    for t, im in every_still(a.video, times, a.width, src_w, src_h):
        tiles.append(stamp(im, f"{t:6.2f}s"))
    if not tiles:
        raise SystemExit("no frames in that window")
    board(tiles, a.cols, a.out)
    print(f"{len(tiles)} frames -> {a.out}")


if __name__ == "__main__":
    import utf8  # noqa: F401
    main()
