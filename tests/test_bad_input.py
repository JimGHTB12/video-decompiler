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
    # C8: blur.py on an input shorter than --open removes the empty output file, and reads stream=nb_frames without -count_packets on valid MP4s
    two_frames = TMP / "two_frames.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:r=24:d=1", "-frames:v", "2", "-pix_fmt", "yuv420p", "-c:v", "libx264", two_frames)
    empty_blur = TMP / "empty_blur.mp4"
    refused(tool("blur.py", two_frames, empty_blur, "--sub", "8", "--open", "4", "--fps", "24"), "gave no frames")
    assert not empty_blur.exists(), "blur.py removed the empty output file"
    from unittest.mock import patch
    sys.path.insert(0, str(TOOLS))
    import blur
    assert not hasattr(blur, "groups"), "dead blur.groups removed"
    probe_cmds = []
    real_run = blur.subprocess.run
    good_blur = TMP / "good_blur.mp4"
    with patch.object(blur.subprocess, "run", side_effect=lambda cmd, *a, **k: (
            probe_cmds.append(list(cmd)) if cmd and cmd[0] == "ffprobe" else None, real_run(cmd, *a, **k))[1]), \
            patch.object(sys, "argv", ["blur.py", str(video), str(good_blur), "--sub", "4", "--open", "2", "--fps", "6"]):
        blur.main()
    assert good_blur.is_file() and len(probe_cmds) == 1 and "-count_packets" not in probe_cmds[0], probe_cmds


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
        for name, args in (("measure.py", [bad, "--out", TMP / "m"]), ("measure_film.py", [bad, TMP / "mf", "--no-voice"]),
                           ("see.py", [bad, "--out", TMP / "s"]), ("sheet.py", [bad, "-o", TMP / "s.jpg"]),
                           ("film_diff.py", [bad, video, "--out", TMP / "d"]), ("timecheck.py", [bad]), ("space.py", [bad])):
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
    sys.path.insert(0, str(TOOLS))
    import measure_film
    assert abs(measure_film.probe(webm)["duration"] - 3.0) < 0.05, "measure_film.probe reads streamed WebM length"
    rot = TMP / "rotated.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-display_rotation", "90", "-i", str(clip("up.mp4")), "-c", "copy", str(rot)], check=True)
    pr = measure_film.probe(rot)
    assert (pr["w"], pr["h"]) == (90, 160), f"measure_film.probe reads shown size of rotated clip: {pr}"
    import pack
    p_webm, key_webm, _ = pack.make(webm, [], TMP / "wpack_out", cache_root=TMP / "wpack_cache", reads_root=TMP / "wpack_reads")
    assert key_webm.is_file() and list((p_webm / "alone").glob("story-*.jpg")) and pack.spans_of(webm, first=1.0, last=1.0)[1][1] > 2.5


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


def test_a_header_that_gives_an_end_time_is_read_as_a_length():
    # a review's finding: a 5 s picture offset to 3600 s in Matroska says duration 3605 in its header (an end time, not
    # a length); measure.json said 3605 s and every rate per ten seconds was divided by it. A header that is a length
    # stays one: an MP4 whose sound runs 2 s past the picture and starts after 0, and a transport stream starting at -1 s.
    sys.path.insert(0, str(TOOLS))
    import film_diff
    import measure_film
    pulse = TMP / "pulse.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=5", "-c:v", "libx264", "-g", "30",
                    "-pix_fmt", "yuv420p", str(pulse)], check=True)
    made = {"late.mkv": ["-itsoffset", "3600", "-i", pulse, "-c:v", "copy", "-avoid_negative_ts", "disabled"],
            "late.mp4": ["-itsoffset", "3600", "-i", pulse, "-c:v", "copy"],
            "longer sound.mp4": ["-i", pulse, "-f", "lavfi", "-t", "7", "-i", "anullsrc=r=48000:cl=stereo", "-c:v", "copy", "-c:a", "aac", "-output_ts_offset", "2"],
            "before zero.ts": ["-copyts", "-itsoffset", "-1", "-i", pulse, "-c", "copy", "-avoid_negative_ts", "disabled", "-mpegts_copyts", "1", "-muxdelay", "0"]}
    for name, args in made.items():
        subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args), str(TMP / name)], check=True)
    for name in ("late.mkv", "late.mp4"):
        assert abs(film_diff.ffprobe(TMP / name)["duration"] - 5.0) < 0.05, (name, film_diff.ffprobe(TMP / name))
        assert abs(measure_film.probe(TMP / name)["duration"] - 5.0) < 0.05, (name, measure_film.probe(TMP / name))
    code, out = tool("measure.py", TMP / "late.mkv", "--out", TMP / "late")
    assert code == 0, out[-300:]
    import json
    said = json.loads((TMP / "late" / "measure.json").read_text(encoding="utf-8"))["duration"]
    assert abs(said - 5.0) < 0.05, f"measure.json's duration of a 5 s picture at 3600 s: {said}"
    longer = film_diff.ffprobe(TMP / "longer sound.mp4")
    assert longer["start_time"] > 1 and abs(longer["duration"] - 7.0) < 0.1, f"a header that is a length stays one: {longer}"
    before = film_diff.ffprobe(TMP / "before zero.ts")
    assert before["start_time"] < 0 and abs(before["duration"] - 5.0) < 0.1, f"a stream starting before 0 keeps its length: {before}"
    # a review's finding: in a cut-off file the last packet left ends far before the header's value, which was read as
    # a sign the header is an end time. A 5 s picture starting at 6 s, cut to a quarter, came out -1 s long, and
    # measure.py took the half that was left of a 10 s film starting at 5 s for a whole 5 s film
    for name, length, offset, keep in (("cut a.mp4", 5, 6.0, 0.25), ("cut b.mp4", 10, 5.0, 0.55)):
        whole = TMP / ("whole " + name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate=30:duration={length}", "-c:v", "libx264",
                        "-g", "15", "-pix_fmt", "yuv420p", "-output_ts_offset", str(offset), "-movflags", "+faststart", str(whole)], check=True)
        data = whole.read_bytes()
        (TMP / name).write_bytes(data[: int(len(data) * keep)])
        cut = film_diff.ffprobe(TMP / name)
        assert abs(cut["duration"] - length) < 0.05, f"a cut-off file keeps the length its header gives: {name} {cut}"
        code, out = tool("measure.py", TMP / name, "--out", TMP / ("out " + name))
        assert code != 0 and "stopped reading" in out, f"and measure.py refuses it, as it did: {name} {code} {out[-200:]}"
    # the re-check's finding: the same 10 s MP4 cut on a packet's edge, where the film had run as long as its header's
    # length says, gives ffprobe nothing to complain of, and its last packet ends at the header's value: it read as an
    # end time, and half the film passed for a whole 5 s one. An MP4's header is a length; only Matroska's is an end time
    import json
    whole = TMP / "whole edge.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=10", "-c:v", "libx264", "-g", "15",
                    "-bf", "0", "-pix_fmt", "yuv420p", "-output_ts_offset", "5.0", "-movflags", "+faststart", str(whole)], check=True)
    packets = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "packet=pts_time,pos,size", "-of", "json", str(whole)],
                                        capture_output=True, text=True, check=True).stdout)["packets"]
    edge = min(packets, key=lambda p: abs(float(p["pts_time"]) - 10.0))      # the frame shown at 10 s: 5 s into the film
    (TMP / "cut edge.mp4").write_bytes(whole.read_bytes()[: int(edge["pos"]) + int(edge["size"])])
    quiet = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(TMP / "cut edge.mp4")], capture_output=True, text=True)
    assert quiet.returncode == 0 and not quiet.stderr.strip(), f"the fixture is a cut ffprobe reads without complaint: {quiet.stderr[-200:]}"
    edge_cut = film_diff.ffprobe(TMP / "cut edge.mp4")
    assert abs(edge_cut["duration"] - 10.0) < 0.05, f"an MP4 cut on a packet's edge keeps the length its header gives: {edge_cut}"
    # an FLV's stored length is a length too: the same cut on a tag's edge (the tag's 16 bytes of headers after its
    # position, then its data) read as an end time before FLV was left out with MP4
    whole = TMP / "whole edge.flv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=10", "-c:v", "libx264", "-g", "15",
                    "-bf", "0", "-pix_fmt", "yuv420p", "-output_ts_offset", "5.0", str(whole)], check=True)
    packets = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "packet=pts_time,pos,size", "-of", "json", str(whole)],
                                        capture_output=True, text=True, check=True).stdout)["packets"]
    edge = min(packets, key=lambda p: abs(float(p["pts_time"]) - 10.0))
    (TMP / "cut edge.flv").write_bytes(whole.read_bytes()[: int(edge["pos"]) + int(edge["size"]) + 16])
    quiet = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(TMP / "cut edge.flv")], capture_output=True, text=True)
    assert quiet.returncode == 0 and not quiet.stderr.strip(), f"the fixture is an FLV cut ffprobe reads without complaint: {quiet.stderr[-200:]}"
    flv_cut = film_diff.ffprobe(TMP / "cut edge.flv")
    assert abs(flv_cut["duration"] - 10.0) < 0.05, f"an FLV cut on a tag's edge keeps the length its header gives: {flv_cut}"
    # the confirmation's finding: a Windows Media file's header is an end time as Matroska's is, and asking only
    # Matroska left a 5 s picture offset to an hour 3605 s long again
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=5", "-c:v", "wmv2", "-b:v", "200k",
                    "-pix_fmt", "yuv420p", "-output_ts_offset", "3600", str(TMP / "late.asf")], check=True)
    late_asf = film_diff.ffprobe(TMP / "late.asf")
    assert late_asf["start_time"] > 3599 and abs(late_asf["duration"] - 5.0) < 0.1, f"a Windows Media header that is an end time is read as a length: {late_asf}"


def test_a_film_is_probed_once_until_it_changes():
    # D5: ffprobe() was asked eight to ten times a film in one vd pack; it is asked once a process for a file as it stands,
    # and again once the file changes (a new picture written at the same path)
    sys.path.insert(0, str(TOOLS))
    from unittest.mock import patch
    import film_diff
    clip = TMP / "probed once.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=1", "-pix_fmt", "yuv420p", str(clip)], check=True)
    real, calls = film_diff.subprocess.run, []
    with patch.object(film_diff.subprocess, "run", lambda cmd, **k: ((calls.append(cmd[0]) if cmd[0] == "ffprobe" else None), real(cmd, **k))[1]):
        first = film_diff.ffprobe(clip)
        first["w"] = -1                                       # a caller changing its copy changes nothing kept
        again = film_diff.ffprobe(clip)
        assert calls == ["ffprobe"] and again["w"] == 160, (calls, again)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2", "-pix_fmt", "yuv420p", str(clip)], check=True)
        assert film_diff.ffprobe(clip)["w"] == 320 and calls == ["ffprobe", "ffprobe"], calls


TESTS = [test_a_film_is_probed_once_until_it_changes, test_a_window_or_rate_that_isnt_one_is_refused, test_keep_never_clears_a_folder_it_did_not_fill,
         test_a_still_or_a_missing_file_is_named, test_a_webm_with_no_length_in_its_header_is_read, test_a_length_from_packets_is_whole_or_refused,
         test_a_header_that_gives_an_end_time_is_read_as_a_length]


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
