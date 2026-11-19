#!/usr/bin/env python3
"""Real motion blur for a film made in code: draw extra pictures between frames, then average them.

  python blur.py IN.mp4 OUT.mp4 [--sub 8] [--open 4] [--fps 24] [--crf 12]

A frame drawn by code is perfectly sharp, so a fast move reads as a row of separate pictures. A camera's frame is the
sum of everything that passed while its shutter was open. To get that, render the film at `sub` times its frame rate,
with the film's clock running at the normal speed (divide the renderer's frame number by `sub`), then run this. It
averages the first `open` pictures of each group of `sub` and keeps one frame per group. 4 of 8 is a half-open shutter,
the usual look. Things that hold still stay sharp, and anything that steps a whole frame at a time (a photograph shown
for one frame, a counter) is unchanged as long as it steps on whole frame numbers.

Keep every function of the clock continuous, and take `Math.floor` of the clock before indexing a list with it.
"""
import argparse
import os
import subprocess
import sys

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--sub", type=int, default=8, help="pictures rendered for each frame of the film")
    ap.add_argument("--open", type=int, default=4, help="how many of them the shutter is open for")
    ap.add_argument("--fps", type=float, default=24)
    ap.add_argument("--crf", type=int, default=12)
    # a leading ~ is the home folder: the pages give paths that way, and PowerShell leaves ~ to the program
    a = ap.parse_args([os.path.expanduser(x) if x == "~" or x[:2] in ("~/", "~" + chr(92)) else x for x in sys.argv[1:]])
    if not 1 <= a.open <= a.sub:
        raise SystemExit("--open must be between 1 and --sub")
    weights = " ".join(["1"] * a.open)
    comma = chr(92) + ","                                   # ffmpeg wants the comma inside mod() escaped
    vf = f"tmix=frames={a.open}:weights='{weights}',select='not(mod(n-{a.open - 1}{comma}{a.sub}))',setpts=N/({a.fps:g}*TB)"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", a.src, "-vf", vf, "-r", f"{a.fps:g}", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True, creationflags=NO_WINDOW)
    count = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames", "-of", "csv=p=0", a.out],
                           capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip().strip(",")
    if not count.isdigit() or int(count) <= 0:
        count = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", a.out],
                               capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip().strip(",")
    if not count.isdigit() or int(count) <= 0:  # ffmpeg writes a file with no picture when the input has fewer than --open pictures
        os.remove(a.out)
        raise SystemExit(f"{a.src} gave no frames at --sub {a.sub} --open {a.open}: it holds fewer pictures than one group, or none. The empty file ffmpeg wrote was removed.")
    print(f"wrote {a.out}: one frame for every {a.sub} pictures, shutter open for {a.open}; {count} frames")


if __name__ == "__main__":
    import utf8  # noqa: F401
    main()
