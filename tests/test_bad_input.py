#!/usr/bin/env python3
"""A tool given the input a careless first run gives it says what is wrong, and never answers with nothing.

  python tests/test_bad_input.py

The tools are run by an agent. A traceback on a wrong argument is survivable: the agent reads it and tries again. A tool
that exits 0 having made nothing, or something wrong, is not, because the agent builds on it and nobody is told. Each
test here feeds one tool an input a tester gave it, and asserts the tool refuses with a message, or keeps the user's file.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler"
TOOLS = SKILL / "tools"
TMP = Path(tempfile.mkdtemp())


def tool(name, *args, cwd=None, env=None):
    p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / name), *map(str, args)], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def clip(name, seconds=3.0, size="160x90", rate=24, audio=False):
    """A small moving clip, with a tone when audio is asked for."""
    out = TMP / name
    if not out.exists():
        tone = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"] if audio else []
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=s={size}:r={rate}:d={seconds}", *tone, "-pix_fmt", "yuv420p", "-c:v", "libx264", out)
    return out


def still(name="still.mp4"):
    """A PNG picture with a video's name, as a careless run gives one."""
    out = TMP / name
    if not out.exists():
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:r=1:d=1", "-frames:v", "1", "-c:v", "png", "-f", "image2", out)
    return out


def refused(result, *words):
    code, out = result
    assert code != 0, f"exit 0 for a bad input: {out[-500:]}"
    assert "Traceback" not in out, f"a message, not a traceback: {out[-800:]}"
    for w in words:
        assert w in out, f"the message says {w!r}: {out[-500:]}"


def test_a_window_or_rate_that_isnt_one_is_refused():
    # broke: measure.py --fps -1 wrote analysed_fps -1 and no segments, --fps 0 was ignored, and --from 2 --to 1 or a window
    # past the clip's end was moved to the end; film_diff.py compared the start of the clip for a window past its end
    video = clip("window.mp4")
    for args, words in ((["--fps", "-1"], "--fps"), (["--fps", "0"], "--fps"), (["--from", "2", "--to", "1"], "isn't after"),
                        (["--from", "0", "--to", "9"], "past the end"), (["--from", "9"], "outside")):
        out = TMP / "measured"
        refused(tool("measure.py", video, "--out", out, *args), words)
        assert not (out / "measure.json").exists(), f"{args} wrote measure.json"
    for args, words in ((["--from", "9"], "outside"), (["--from", "1", "--to", "9"], "past the end"), (["--from", "2", "--to", "1"], "isn't after")):
        refused(tool("film_diff.py", video, video, "--out", TMP / "diff", *args), words)
    code, out = tool("film_diff.py", video, clip("window1.mp4", seconds=1), "--out", TMP / "diff", "--from", "1", "--to", "2")
    assert code == 0, f"a window inside the clip still compares: {out[-300:]}"


def test_keep_never_clears_a_folder_it_did_not_fill():
    # a review's finding: look.py --keep DIR removed DIR and everything in it before drawing, the film's own folder too
    film = TMP / "keepfilm"
    film.mkdir()
    (film / "main.tsx").write_text("// a film", encoding="utf-8")
    (film / "score.json").write_text('{"fps": 30, "width": 64, "height": 36, "duration": 1.0}', encoding="utf-8")
    mine = TMP / "notes"
    mine.mkdir()
    (mine / "unrelated.txt").write_text("a person's own file", encoding="utf-8")
    for keep, word in ((film, "the film's folder"), (TMP, "holds it"), (mine, "did not put there")):
        code, out = tool("look.py", film / "main.tsx", "--at", "0", "-o", TMP / "keep-look.jpg", "--keep", keep)
        assert code != 0 and "--keep" in out and word in out and "Traceback" not in out, (keep, code, out[-400:])
        assert (film / "main.tsx").exists() and (mine / "unrelated.txt").exists(), f"--keep {keep} removed a file that was not its own"


def test_a_still_or_a_missing_file_is_named():
    # broke: film_diff.ffprobe raised KeyError: 'duration' for a picture named like a video, and that traceback came out of
    # every tool that reads a video; a path that isn't there was "no video stream that ffprobe can read", and timecheck
    # printed the raw ffprobe command
    video = clip("named.mp4")
    for bad, words in ((still(), "is a still image, not a video"), (TMP / "not here.mp4", "no such file")):
        for name, args in (("measure.py", [bad, "--out", TMP / "m"]), ("see.py", [bad, "--out", TMP / "s"]), ("sheet.py", [bad, "-o", TMP / "s.jpg"]),
                           ("film_diff.py", [bad, video, "--out", TMP / "d"]), ("timecheck.py", [bad])):
            refused(tool(name, *args), words)


def test_a_webm_with_no_length_in_its_header_is_read():
    # broke: a browser's screen recording is a webm written as a stream, with no duration in its header; the shared probe
    # took a missing duration for a still picture, so timecheck.py and vd.py new refused a video they used to read
    import json
    webm = TMP / "recording.webm"
    with open(webm, "wb") as out:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=3", "-c:v", "libvpx", "-b:v", "300k", "-f", "webm", "-"], stdout=out, check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(webm)], capture_output=True, text=True).stdout.strip()
    assert probe in ("", "N/A"), f"the test file has no duration in its header: {probe}"
    for name, args in (("timecheck.py", [webm]), ("measure.py", [webm, "--out", TMP / "wm"]), ("sheet.py", [webm, "-o", TMP / "w.jpg"]), ("see.py", [webm, "--out", TMP / "wsee"])):
        code, out = tool(name, *args)
        assert code == 0 and "Traceback" not in out, f"{name} reads it: {out[-400:]}"
    assert abs(json.loads((TMP / "wm" / "measure.json").read_text(encoding="utf-8"))["duration"] - 3.0) < 0.05, "at its real length"


def test_a_length_from_packets_is_whole_or_refused():
    # broke: for a video with no length in its header, the last packet's time was taken as the length, so 75 frames at
    # 25 fps with times 0.00 to 2.96 and no packet durations (an MKV written as a stream) read as 2.96 s and a window
    # --to 3 was refused; and a probe of the packets that reported "File ended prematurely" was believed
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch
    sys.path.insert(0, str(TOOLS))
    import film_diff
    packets = "".join(f"{k / 25:.6f},N/A\n" for k in range(75))
    with patch.object(film_diff.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=packets, stderr="")):
        assert abs(film_diff.last_packet_end("stream.mkv", 0.0, 25.0) - 3.0) < 1e-6, "the last frame shows for one frame's interval, from the rate"
        assert abs(film_diff.last_packet_end("stream.mkv", 0.0, 0.0) - 3.0) < 1e-6, "or from the gap before it"
    whole = TMP / "stream.mkv"
    with open(whole, "wb") as out:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "matroska", "-"], stdout=out, check=True)
    data = whole.read_bytes()
    half = TMP / "stream half.mkv"
    half.write_bytes(data[:len(data) // 2])
    refused(tool("measure.py", half, "--out", TMP / "half"), "reading its frames for one failed")
    code, out = tool("film_diff.py", whole, whole, "--out", TMP / "streamdiff", "--from", "0", "--to", "3")
    assert code == 0, f"and the whole one compares to its end: {out[-300:]}"


TESTS = [test_a_window_or_rate_that_isnt_one_is_refused,
         test_a_still_or_a_missing_file_is_named, test_a_webm_with_no_length_in_its_header_is_read, test_a_length_from_packets_is_whole_or_refused]


def main():
    try:
        for t in TESTS:
            t()
            print("ok", t.__name__)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("bad input checks passed")


if __name__ == "__main__":
    main()
