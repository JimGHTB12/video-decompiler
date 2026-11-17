#!/usr/bin/env python3
"""tools/bridge.py (`vd bridge`) and tools/puppet.py (`vd capture`, `vd launch`) against planted faults.

Bridge: the same picture binds to the same hash twice, and the same picture encoded again binds to a different one, so
cues.json names the exact file it was timed on; a --video that does not exist, or a film with no export, is refused,
never bound to a picture the bridge made up. Capture: the command runs with no shell, so `;` and `&&` in it reach the
program as words and run nothing else; a command that hangs printing nothing is stopped at its timeout, and the record
says so; a program that is not on PATH is named. Bridge, on a copy of Stet: its sections and events are its named events
(CUES), not the step sizes and counts beside them in TIMES, and none is lost past the act its clock shifts; a picture
with non-square pixels is refused, since legible-film's reader would call the cues stale at once. Needs ffmpeg.

  python tests/test_bridge_capture_faults.py
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import json  # noqa: E402

import bridge  # noqa: E402
import lean  # noqa: E402
import puppet  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return fn(*args, **kwargs)
        except SystemExit as e:
            return e


def clip(path, crf):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2",
                    "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", str(path)], check=True)


def test_bridge_binds_to_the_exact_picture():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "a.mp4", Path(tmp) / "b.mp4"
        clip(a, 18)
        clip(b, 30)   # the same frames, encoded again: a different file an editor could mistake for it
        info_a, info_a2, info_b = (bridge.picture_identity_and_schedule(p) for p in (a, a, b))
        assert len(info_a["sha256"]) == 64 and info_a["frames"] == 60, (info_a["sha256"], info_a["frames"])
        assert info_a["sha256"] == info_a2["sha256"], "one file hashed twice gave two answers"
        assert info_a["sha256"] != info_b["sha256"], "a re-encoded picture bound to the same hash"


def test_bridge_refuses_a_picture_it_would_have_to_invent():
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "never-exported"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        out = Path(tmp) / "bridge-out"
        r = quiet(lean.main, ["bridge", "--film", str(film), "--video", str(Path(tmp) / "typo.mp4"), "-o", str(out)])
        assert isinstance(r, SystemExit) and "typo.mp4" in str(r.code), f"a missing --video was not refused: {r!r}"
        assert not (out / "cues.json").exists(), "cues.json was written for a picture that does not exist"
        old = lean.OUTROOT
        lean.OUTROOT = Path(tmp) / "out"   # no export of this film exists there
        try:
            r = quiet(lean.main, ["bridge", "--film", str(film), "-o", str(out)])
        finally:
            lean.OUTROOT = old
        assert isinstance(r, SystemExit) and "vd export" in str(r.code), f"a film with no export was bridged: {r!r}"
        assert not (out / "cues.json").exists(), "cues.json was bound to a made-up picture"



def test_bridge_timelines_carry_the_films_sound_and_agree_on_placement():
    # broke: the OTIO held no sound track; the XML named two channels at 48 kHz for every file, a silent one too; and
    # the XML counted the host's in-point into the sequence while the OTIO made it a start time
    import xml.etree.ElementTree as ET
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "film"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        voiced, silent = Path(tmp) / "voiced.mp4", Path(tmp) / "silent.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i",
                        "sine=f=440:d=2:sample_rate=44100", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1",
                        "-shortest", str(voiced)], check=True)
        clip(silent, 18)
        for video, sound in ((voiced, (1, 44100)), (silent, None)):
            out = Path(tmp) / f"out-{video.stem}"
            assert quiet(lean.main, ["bridge", "--film", str(film), "--video", str(video), "-o", str(out), "--host-in", "2.0"]) == 0
            otio = json.loads((out / "timeline.otio").read_text(encoding="utf-8"))
            tracks = otio["tracks"]["children"]
            assert [t["kind"] for t in tracks] == (["Video", "Audio"] if sound else ["Video"]), [t["kind"] for t in tracks]
            for t in tracks:   # the in-point is a 60-frame gap before the 60-frame clip in every track
                kinds = [c["OTIO_SCHEMA"] for c in t["children"]]
                assert kinds == ["Gap.1", "Clip.2"] and t["children"][0]["source_range"]["duration"]["value"] == 60.0, kinds
            assert otio["global_start_time"]["value"] == 0.0
            xml = ET.parse(out / "timeline.xml").getroot()
            seq = xml.find("sequence")
            assert seq.find("duration").text == "120" and seq.find("media/video/track/clipitem/start").text == "60"
            a_tracks = seq.findall("media/audio/track")
            assert len(a_tracks) == (sound[0] if sound else 0), len(a_tracks)
            rate = xml.find(".//file/media/audio/samplecharacteristics/samplerate")
            assert (rate.text if rate is not None else None) == (str(sound[1]) if sound else None)

def test_capture_runs_no_shell():
    py = sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        rec = puppet.capture_command(f'"{py}" -c "print(41 + 1)" ; echo INJECTED && echo AGAIN', Path(tmp), timeout=20)
        text = "\n".join(line["text"] for line in rec["lines"])
        assert "42" in text, rec
        assert "INJECTED" not in text and "AGAIN" not in text, f"a shell ran the rest of the line: {text!r}"
        assert rec["exit_code"] == 0 and rec["timed_out"] is False, rec
        # a quote can open inside a word, as in git's --format="%h %s": one argument, as the program's own shell would pass it
        rec = puppet.capture_command(f'"{py}" -c "import sys; print(sys.argv[1])" --format="%h %s"', Path(tmp), timeout=20)
        assert [line["text"] for line in rec["lines"]] == ["--format=%h %s"], rec["lines"]
        rec = puppet.capture_command([py, "-c", "import sys; print('x'); sys.exit(3)"], Path(tmp), timeout=20)
        assert rec["exit_code"] == 3 and [line["text"] for line in rec["lines"]] == ["x"], rec
        if os.name == "nt":
            # broke: Windows runs a batch file through cmd.exe, so `tool.cmd SAFE & echo INJECTED` ran the second command
            bat = Path(tmp) / "tool.cmd"
            bat.write_text("@echo BATCH %*\r\n", encoding="utf-8")
            try:
                puppet.capture_command([str(bat), "SAFE", "&", "echo", "INJECTED"], Path(tmp), timeout=20)
                raise AssertionError("a batch file was run with an argument cmd.exe reads as a command")
            except SystemExit as e:
                assert "batch file" in str(e), e
            # its own name too: a file called tool&echo.INJECTED&.cmd ran echo
            odd = Path(tmp) / "tool&echo.INJECTED&.cmd"
            odd.write_text("@echo BATCH %*" + chr(13) + chr(10), encoding="utf-8")
            try:
                puppet.capture_command([str(odd), "SAFE"], Path(tmp), timeout=20)
                raise AssertionError("a batch file named with & was run")
            except SystemExit as e:
                assert "batch file" in str(e), e
            rec = puppet.capture_command([str(bat), "SAFE", "--flag"], Path(tmp), timeout=20)
            assert [line["text"] for line in rec["lines"]] == ["BATCH SAFE --flag"], rec["lines"]


def test_capture_stops_a_silent_hang():
    py = sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.monotonic()
        rec = puppet.capture_command([py, "-c", "import time; time.sleep(60)"], Path(tmp), timeout=1.5)
        took = time.monotonic() - t0
        assert took < 10, f"a command that printed nothing ran {took:.0f} s past a 1.5 s timeout"
        assert rec["timed_out"] is True and rec["exit_code"] != 0, rec
        # a command that closes its output and keeps running is held to the same deadline, and called stopped
        t0 = time.monotonic()
        rec = puppet.capture_command([py, "-c", "import os, time; os.close(1); os.close(2); time.sleep(60)"], Path(tmp), timeout=1.0)
        assert time.monotonic() - t0 < 4 and rec["timed_out"] is True, (time.monotonic() - t0, rec)
        # an empty command is refused, not read as the running program; a leading space is no part of the program's name
        r = quiet(puppet.capture_command, "  ", Path(tmp))
        assert isinstance(r, SystemExit) and "empty" in str(r.code), r
        assert puppet.command_argv(f' "{py}" -V')[1:] == ["-V"]
        r = quiet(puppet.capture_command, "no-such-program-vd --version", Path(tmp))
        assert isinstance(r, SystemExit) and "no-such-program-vd" in str(r.code), r


def test_bridge_times_events_by_the_films_named_cues():
    stet_mp4 = ROOT / "docs" / "media" / "stet.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "stet-copy"
        quiet(lean.main, ["new", str(film), "--like", "stet"])
        out = Path(tmp) / "b"
        assert quiet(lean.main, ["bridge", "--film", str(film), "--video", str(stet_mp4), "-o", str(out)]) == 0
        doc = json.loads((out / "cues.json").read_text(encoding="utf-8"))
        ids = {e["id"] for e in doc["events"]} | {sec["id"] for sec in doc["sections"]}
        assert not any("step" in i.lower() or i.lower().endswith("_nt") for i in ids), sorted(ids)
        dur = doc["sections"][-1]["b"]
        named = [n for n, t in lean.gen_data(film)["CUES"] if t <= dur]
        got = {e.get("role") for e in doc["events"]}
        assert set(named) <= got, f"named events lost: {sorted(set(named) - got)}"
        assert "END" in named, "the last act's END cue should be inside the film"


def test_bridge_refuses_non_square_pixels():
    with tempfile.TemporaryDirectory() as tmp:
        wide = Path(tmp) / "sar.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1", "-vf", "setsar=2/1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(wide)], check=True)
        r = quiet(bridge.picture_identity_and_schedule, wide)
        assert isinstance(r, SystemExit) and "non-square" in str(r.code), r



def test_a_picture_on_another_drive_is_named_by_its_whole_path():
    # broke (Windows CI): the export on D: and the bundle on C: have no relative path, and the bridge raised ValueError
    import os
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "film"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        v = Path(tmp) / "c.mp4"
        clip(v, 18)
        out = Path(tmp) / "out"

        def other_drive(*a, **k):
            raise ValueError("path is on mount 'D:', start on mount 'C:'")
        with patch.object(os.path, "relpath", other_drive):
            assert quiet(lean.main, ["bridge", "--film", str(film), "--video", str(v), "-o", str(out)]) == 0
        cues = json.loads((out / "cues.json").read_text(encoding="utf-8"))
        assert v.resolve().as_posix() in json.dumps(cues), "the picture is named by its whole path"


def test_a_rotate_tag_of_zero_is_upright():
    assert not bridge.is_turned({"tags": {"rotate": "0"}}) and not bridge.is_turned({})
    assert bridge.is_turned({"tags": {"rotate": "90"}}) and bridge.is_turned({"side_data_list": [{"rotation": -90}]})


def test_bridge_names_ntsc_rates_rightly():
    # broke: 29.97 given as 2997/100 was written timebase 29 NTSC (28.97 fps), and 12.5 fps was marked NTSC
    import xml.etree.ElementTree as ET
    with tempfile.TemporaryDirectory() as tmp:
        v = Path(tmp) / "c.mp4"
        clip(v, 18)
        cues = {"events": []}
        for rate, base, ntsc in (("30000/1001", "30", "TRUE"), ("2997/100", "30", "TRUE"), ("25/2", "12", "FALSE"), ("30", "30", "FALSE")):
            info = {"fps_exact": rate, "frames": 60, "width": 320, "height": 180}
            xml_path, _ = bridge.build_xmeml_and_otio(Path(tmp), v, info, cues, Path(tmp), 0.0)
            r = ET.parse(xml_path).getroot().find("sequence/rate")
            assert (r.find("timebase").text, r.find("ntsc").text) == (base, ntsc), (rate, r.find("timebase").text, r.find("ntsc").text)



def test_bridge_gives_every_channel_a_track():
    # broke: a six-channel film was given two audio tracks in the XML
    import xml.etree.ElementTree as ET
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "film"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        v = Path(tmp) / "six.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i",
                        "sine=f=440:d=2", "-filter_complex", "[1]pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0[a]", "-map", "0:v", "-map", "[a]",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(v)], check=True)
        out = Path(tmp) / "out"
        assert quiet(lean.main, ["bridge", "--film", str(film), "--video", str(v), "-o", str(out)]) == 0
        assert len(ET.parse(out / "timeline.xml").getroot().findall("sequence/media/audio/track")) == 6


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("bridge and capture fault checks passed")
