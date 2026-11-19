#!/usr/bin/env python3
"""tools/lean.py's pure parts, with known answers: splice and export intermediates, the usage log line, the gap table's
order, where a planted hit peaks, the level in a planted pause, a planted silent hole, and the splice's frame cuts.
No raea and no ffmpeg needed.

  python tests/test_lean.py
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import lean  # noqa: E402

# A temp folder can be spelled with a short name (RUNNER~1 for runneradmin on a hosted Windows machine). The tools resolve a
# film's folder and so spell it in full, and the tests below compare what a tool reports with paths they built from the
# temp folder: give every test here the full spelling.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())


def test_splice_unlinks_range_intermediates_and_export_unlinks_part_manifests():
    import contextlib
    import io
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        out = Path(tmp) / "out"

        def draw(dd, entry, target, *flags, env=None):
            target = Path(target)
            target.write_bytes(b"mp4")
            target.with_name(target.name + ".render.json").write_text("{}", encoding="utf-8")
            return True, 0.1, "OK"

        def fake_heavy(args, **kw):
            # args ends with splice_args(..., tmp_mp4) where tmp_mp4 is picture.splice.mp4
            Path(args[-1]).write_bytes(b"spliced")

        with patch.object(lean, "OUTROOT", out), patch.object(lean, "raea_render", draw), \
                patch.object(lean, "must_preflight", lambda *a, **k: None), patch.object(lean, "mux", lambda *a, **k: None), \
                patch.object(lean, "hand_in", lambda dest: (dest, [])), \
                patch.object(lean, "build_sound", lambda dd, s: Path(lean.outdir(dd) / "sound.wav").write_bytes(b"w")), \
                patch.object(lean, "comp_frames", lambda e, c: None), \
                patch.object(lean, "run", fake_heavy), patch.object(lean, "join_report", lambda *a: "joins ok"), \
                contextlib.redirect_stdout(io.StringIO()):
            lean.cmd_export(Args(film=str(d)))
            o = lean.outdir(d)
            assert not list(o.glob("*.render.json")), list(o.glob("*.render.json"))
            lean.cmd_render(Args(film=str(d), from_="0.2", to="0.6"))
            assert not list(o.glob("range-*")), list(o.glob("range-*"))


def test_clean_takes_a_range_only_when_an_interrupted_splice_left_it():
    # a review's finding: range-*.mp4 as a pattern also matched a film named range-demo's finished film, an export
    # named so, and a range rendered alone, and plain `vd clean --yes` deleted them
    import contextlib
    import io
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wav = root / "sound.wav"
        wav.write_bytes(b"stand-in sound")

        def film(name):
            d = root / name
            d.mkdir()
            (d / "main.tsx").write_text("// fake", encoding="utf-8")
            (d / "score.json").write_text(json.dumps({"fps": 30, "duration": 1, "composition": "film", "beats": []}), encoding="utf-8")
            return d

        def draw(d, entry, target, *flags, env=None):
            Path(target).write_bytes(b"drawn")
            Path(str(target) + ".render.json").write_text("{}", encoding="utf-8")
            return True, 0.1, "OK"

        def stopped(args, **kw):
            raise KeyboardInterrupt  # the splice's encode, stopped part way

        mux = lambda pic, w, dest, **kw: Path(dest).write_bytes(b"finished muxed film")
        with patch.object(lean, "OUTROOT", root / "out"), patch.object(lean, "raea_render", draw), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "comp_frames", lambda *a: None), patch.object(lean, "room", lambda *a, **k: None), \
                patch.object(lean, "film_sound", lambda *a: (wav, None)), patch.object(lean, "mux", mux), \
                patch.object(lean, "held_under_peak", lambda *a, **kw: None), patch.object(lean, "hand_in", lambda dest: (dest, [])), \
                patch.object(lean, "scanned", lambda *a, **kw: root / "scan.txt"), patch.object(lean, "range_entry", lambda d, *a: d / "main.tsx"), \
                contextlib.redirect_stdout(io.StringIO()):
            demo = film("range-demo")
            lean.main(["export", "--film", str(demo)])
            o = root / "out" / "range-demo"
            finished, cut = o / "range-demo.mp4", o / "cuts" / "range-demo-cut1.mp4"
            assert finished.is_file() and cut.is_file(), sorted(p.name for p in o.rglob("*"))
            # an export named like a range part, beside them
            named = o / "range-12-30.mp4"
            lean.main(["export", "--film", str(demo), "-o", str(named)])
            assert named.is_file()
            lean.main(["clean", "range-demo", "--yes"])
            assert finished.is_file() and cut.is_file() and named.is_file(), sorted(p.name for p in o.rglob("*"))
            # a range rendered alone (no picture to splice into yet) is the person's to keep
            alone = film("alone")
            lean.main(["render", "--film", str(alone), "--from", "0", "--to", "0.5"])
            part = root / "out" / "alone" / "range-0-15.mp4"
            assert part.is_file() and not list(part.parent.glob("*.splicing"))
            lean.main(["clean", "alone", "--yes"])
            assert part.is_file(), "a standalone range render survives clean"
            # a splice stopped after its range was drawn: the part it recorded goes with its record
            cut_short = film("cut-short")
            lean.main(["export", "--film", str(cut_short)])
            with patch.object(lean, "run", stopped):
                try:
                    lean.main(["render", "--film", str(cut_short), "--from", "0", "--to", "0.5"])
                except KeyboardInterrupt:
                    pass
            left = root / "out" / "cut-short" / "range-0-15.mp4"
            assert left.is_file() and Path(str(left) + ".splicing").is_file()
            planned = {p.name for p, _, _ in lean.clean_plan(left.parent)}
            assert {"range-0-15.mp4", "range-0-15.mp4.render.json", "range-0-15.mp4.splicing"} <= planned, planned
            lean.main(["clean", "cut-short", "--yes"])
            assert not left.exists() and not list(left.parent.glob("range-*")), sorted(p.name for p in left.parent.iterdir())
            assert (left.parent / "cut-short.mp4").is_file(), "and the finished film beside it stays"


def test_a_wav_vd_wrote_is_read_without_ffmpeg_and_reads_the_same():
    # A8: a 16-bit stereo WAV at 48 kHz is read directly; the samples must be ffmpeg's to the bit, from the same first
    # sample, at starts on either side of a sample's edge (ffmpeg reads -ss to the microsecond and takes the nearest).
    # Anything else (mono, which ffmpeg spreads at -3 dB; 44.1 kHz; 24-bit) still goes through ffmpeg
    import subprocess
    import wave
    from unittest.mock import patch
    rng = np.random.default_rng(7)
    with tempfile.TemporaryDirectory() as tmp:
        made = {}
        for name, ch, rate, width in (("st", 2, 48000, 2), ("mono", 1, 48000, 2), ("r441", 2, 44100, 2), ("w24", 2, 48000, 3)):
            made[name] = Path(tmp) / f"{name}.wav"
            with wave.open(str(made[name]), "wb") as w:
                w.setnchannels(ch); w.setsampwidth(width); w.setframerate(rate)
                w.writeframes(rng.integers(0, 256, rate * 2 * ch * width, dtype=np.uint8).tobytes())

        def by_ffmpeg(p, s):
            done = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(s), "-i", str(p), "-vn", "-ac", "2", "-ar", "48000", "-f", "f32le", "-"], capture_output=True)
            return None if done.returncode else np.frombuffer(done.stdout, np.float32).reshape(-1, 2)
        ran = []
        real_run = lean.run
        with patch.object(lean, "run", lambda args, **k: (ran.append(args), real_run(args, **k))[1]):
            for s in (0.0, 0.5, 1 / 3, 1.2345678, 1.000010, 1.0000104, 1.000011, 0.999989, 0.99999, 2.0):
                got, want = lean.read_audio(made["st"], s), by_ffmpeg(made["st"], s)
                assert np.array_equal(got, want), (s, got.shape, want.shape)
            assert not ran, f"a 16-bit stereo 48 kHz WAV is read without ffmpeg: {ran[:1]}"
            for name in ("mono", "r441", "w24"):
                ran.clear()
                assert np.array_equal(lean.read_audio(made[name]), by_ffmpeg(made[name], 0.0)) and ran, name
        assert lean._wav_samples(made["st"], 1.04e-05) is None, "a start ffmpeg refuses (1.04e-05) is left to ffmpeg"
        # a review's finding: a WAV written to a pipe leaves its sizes unfilled and says it holds 4 GB; reading the
        # frames its header claims asked for all of it at once (MemoryError). It is ffmpeg's to read, as it was
        piped = Path(tmp) / "piped.wav"
        piped.write_bytes(subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=0.1:r=48000", "-ac", "2", "-c:a", "pcm_s16le",
                                          "-f", "wav", "-"], capture_output=True, check=True).stdout)
        with wave.open(str(piped), "rb") as w:
            assert w.getnframes() * 4 > piped.stat().st_size, "the fixture is a WAV whose header claims more than it holds"
        assert lean._wav_samples(piped, 0.0) is None, "a WAV whose header claims more than the file holds is left to ffmpeg"
        assert np.array_equal(lean.read_audio(piped), by_ffmpeg(piped, 0.0)) and lean.read_audio(piped).shape == (4800, 2)
        # the re-check's finding: a stream's header left at 0 frames, with the sound after it, read as no sound at all
        import struct
        unsized = Path(tmp) / "unsized.wav"
        sound = rng.integers(-2000, 2000, 4800 * 2, dtype=np.int16).tobytes()
        unsized.write_bytes(struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 2, 48000, 192000, 4, 16, b"data", 0) + sound)
        assert lean._wav_samples(unsized, 0.0) is None, "a WAV that says it holds no frames is left to ffmpeg"
        assert lean.read_audio(unsized).shape == (4800, 2) and np.array_equal(lean.read_audio(unsized), by_ffmpeg(unsized, 0.0))


def test_usage_log():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "u" / "usage.log"
        lean.usage_log("look", Path(tmp) / "film", 2.345, path=log)
        lean.usage_log("sound", None, 1, path=log)
        rows = [l.split("\t") for l in log.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 2 and rows[0][1] == "look" and rows[0][3] == "2.3" and rows[1][2] == "-"
        import os
        import subprocess
        fake_home, iso = Path(tmp) / "fake_home", Path(tmp) / "iso"
        fake_home.mkdir()
        clip = Path(tmp) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
        env = {**{k: v for k, v in os.environ.items() if k != "VD_READS"},
               "VD_OUT": str(iso / "out"), "USERPROFILE": str(fake_home), "HOME": str(fake_home)}
        p1 = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "new", str(Path(tmp) / "f"), "--kind", "launch", "--bare"],
                            capture_output=True, text=True, env=env)
        p2 = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "pack.py"), str(clip), "--against", str(clip)],
                            capture_output=True, text=True, env=env)
        assert p1.returncode == 0 and p2.returncode == 0, (p1.stdout + p1.stderr, p2.stdout + p2.stderr)
        assert not list(fake_home.iterdir()), f"VD_OUT keeps everything out of ~/.vd: {list(fake_home.rglob('*'))}"
        assert (iso / "usage.log").is_file() and (iso / "out" / "clip" / "pack-1-KEY.txt").is_file() and (iso / "measures").is_dir() and (iso / "reads").is_dir()


def test_gap_rows_order():
    ours = {"A": {"x": 10.0, "y": 1.0, "times": [1.0, 2.0]}, "B": 5, "flag": True, "E_sound": {"gap_db": -20.0}, "Z": {"tiny": 0.2}}
    ref = {"A": {"x": 10.0, "y": 2.0, "times": [1.0, 2.0, 3.0, 4.0]}, "B": 50, "E_sound": {"gap_db": -18.0}, "Z": {"tiny": 0.002}}
    rows = lean.gap_rows(ours, ref)
    names = [r[0] for r in rows]
    assert names[0] == "E_sound.gap_db", "sound besides the voice leads, by importance"
    assert names.index("B") < names.index("A.y") < names.index("A.x") and "flag" not in names
    tiny = next(r for r in rows if r[0] == "Z.tiny")
    assert tiny[5] <= 1.0, "a near-zero reference can't blow the gap up past 1"
    assert "A.times (count)" in names
    table = lean.gap_table(rows)
    assert "| 1 | 1 | E_sound.gap_db | -20 | -18 | 0.1 |" in table and "Times (s):" in table, table


def test_gap_rows_in_spreads_of_a_bare_pass():
    ref = {"m": 10.0, "n": 1.0, "same": 4.0}
    bare = {"m": 0.0, "n": 0.9, "same": 4.0}       # direction moved m by 10 and n by 0.1
    ours = {"m": 9.0, "n": 0.5, "same": 3.0}
    rows = lean.gap_rows(ours, ref, bare)
    assert [r[0] for r in rows] == ["n", "m", "same"], rows   # n: 0.5 off in a spread of 0.1 = 5; m: 1 in 10 = 0.1; same: no spread
    assert abs(rows[0][5] - 5.0) < 1e-9 and "bare pass" in lean.gap_table(rows, bare=True)


def mix_with(events, dur=4.0):
    x = np.zeros((int(dur * lean.SR), 2), np.float32)
    for at, kind in events:
        lean.place(x, lean.made(kind, 440), at, -6)
    return x


def test_hit_report_finds_planted_peaks():
    x = mix_with([(0.5, "ping"), (2.0, "tick")])
    env = lean.env_db(x)
    rows = lean.hit_report(env, [("ping", 0.5), ("tick", 2.0), ("late", 2.2)])
    assert abs(rows[0][3]) <= 20 and abs(rows[1][3]) <= 20, rows
    assert rows[2][3] < -50, rows  # a hit wanted 0.2 s after the real one is reported early


def test_a_hit_is_checked_where_it_starts_not_where_it_peaks():
    # G: a whoosh placed at 6.45 s peaks at 6.75 s and was flagged 300 ms off; so was a tick under a piano note
    x = np.zeros((int(4.0 * lean.SR), 2), np.float32)
    lean.place(x, lean.made("whoosh", 0), 1.0, -6)                       # slow attack: loudest in its middle
    lean.place(x, lean.made("ping", 440, dur=2.0), 2.4, -6)              # a note ringing on...
    lean.place(x, lean.made("tick", 1800), 2.7, -6)                       # ...with a tick on top of it
    rows = lean.hit_report(lean.env_db(x), [("whoosh", 1.0), ("tick", 2.7)])
    assert abs(rows[0][3]) <= 40, f"the whoosh starts where it was placed: {rows[0]}"
    assert abs(rows[1][3]) <= 40, f"the tick is found under the note: {rows[1]}"


def test_pause_and_holes():
    sr = lean.SR
    x = np.zeros((int(4.0 * sr), 2), np.float32)
    t = np.arange(int(1.0 * sr)) / sr
    loud = 0.3 * np.sin(2 * np.pi * 200 * t)
    x[0:sr, :] += loud[:, None]                 # words 0-1 s
    x[int(1.5 * sr):int(2.5 * sr), :] += loud[:, None]   # words 1.5-2.5 s
    x[sr:int(1.5 * sr), :] += 0.03 * np.sin(2 * np.pi * 200 * t[: int(0.5 * sr)])[:, None]   # a bed 20 dB under
    env = lean.env_db(x)
    words = [{"start": 0.0, "end": 1.0}, {"start": 1.5, "end": 2.5}]
    (g0, g1, diff), = lean.pause_report(env, words)
    assert g0 == 1.0 and g1 == 1.5 and -21.5 < diff < -18.5, diff
    hs = lean.holes(env)
    assert hs and hs[0][0] == 2.5 and hs[0][1] >= 3.6, hs   # silence from 2.5 s to the tail


def test_word_mask_ducks_only_while_speaking():
    m = lean.word_mask([{"start": 1.0, "end": 2.0}], 4 * lean.SR)
    assert m[int(1.5 * lean.SR)] > 0.999 and m[int(3.0 * lean.SR)] < 1e-6 and m[int(0.5 * lean.SR)] < 1e-6


def test_splice_args_cut_at_frames():
    a = lean.splice_args("old.mp4", "part.mp4", "new.mp4", 30, 90)
    fc = a[a.index("-filter_complex") + 1]
    assert "trim=end_frame=30" in fc and "trim=start_frame=90" in fc and "concat=n=3" in fc
    assert a[-1] == "new.mp4" and "-an" in a


def test_starter_scores_are_whole():
    for kind in lean.KINDS:
        s = json.loads((lean.STARTER / "scores" / f"{kind}.json").read_text(encoding="utf-8"))
        beats = s["beats"]
        assert beats[0]["from"] == 0 and abs(beats[-1]["to"] - s["duration"]) < 1e-9, kind
        assert all(a["to"] == b["from"] for a, b in zip(beats, beats[1:])), f"{kind}: beats leave a gap or overlap"
        assert all(e["at"] < s["duration"] for e in s["sounds"])


def test_new_copies_the_kit_beside_the_entry():
    with tempfile.TemporaryDirectory() as tmp:
        class A: pass
        a = A(); a.name = str(Path(tmp) / "f"); a.kind = "launch"
        d = lean.cmd_new(a)
        assert (d / "kit" / "base.tsx").exists() and (d / "kit" / "lib" / "core.ts").exists() and (d / "kit" / "motions" / "hold-drift.ts").exists()
        assert (d / "kit" / "finish.gen.ts").exists() and (d / "kit" / "transitions").is_dir()
        assert '"./kit/base"' in (d / "film.tsx").read_text(encoding="utf-8")
        # app: one film's light interface, cut to its skeleton, is the film; its times are the score's beats
        a = A(); a.name = str(Path(tmp) / "h"); a.kind = "app"
        d = lean.cmd_new(a)
        film = (d / "film.tsx").read_text(encoding="utf-8")
        assert "function Cursor" in film and 'beat("zoom")' in film and (d / "kit" / "base.tsx").exists()
        ids = [b["id"] for b in json.loads((d / "score.json").read_text(encoding="utf-8"))["beats"]]
        assert all(f'beat("{i}")' in film for i in ("open", "press", "drag", "zoom")) and ids[:4] == ["open", "press", "drag", "zoom"]


class Args:
    def __init__(self, **kw):
        self.__dict__.update(dict(entry=None, film=None, composition=None, o=None, again=False, sound=None, onto=None, from_score=False), **kw)


def fake_film(tmp):
    """A film folder with an entry and a score, its outputs under tmp, raea and ffmpeg replaced: (folder, list of renders)."""
    d = Path(tmp) / "film"
    d.mkdir()
    (d / "main.tsx").write_text("// two compositions", encoding="utf-8")
    (d / "score.json").write_text(json.dumps({"fps": 30, "width": 64, "height": 36, "duration": 1.0, "beats": [], "sounds": []}), encoding="utf-8")
    rendered = []

    def render(dd, entry, out, *flags, env=None):
        rendered.append((Path(out).name, flags))
        Path(out).write_bytes(b"x")
        return True, 0.1, "OK"
    return d, rendered, render


def test_export_renders_each_composition_once_not_the_first_for_both():
    # a review's finding: exporting composition A then B from one entry, sources unchanged, reused A's picture for B
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None),                 patch.object(lean, "mux", lambda *a, **k: None), patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")),                 patch.object(lean, "comp_frames", lambda e, c: None):
            lean.cmd_export(Args(film=str(d), composition="A"))
            lean.cmd_export(Args(film=str(d), composition="B"))
            lean.cmd_export(Args(film=str(d), composition="B"))
        pictures = [name for name, flags in rendered if ".picture" in name and name.endswith(".mp4")]
        assert len(pictures) == 2 and pictures[0] != pictures[1], f"A and B each rendered once, B not twice: {rendered}"


def test_sound_of_an_entry_goes_onto_the_film_asked_for():
    # a review's finding: `vd sound ENTRY.tsx --onto FILM.mp4` rendered the sound and returned without putting it on the film
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        film, muxed = Path(tmp) / "cut.mp4", []
        film.write_bytes(b"v")
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None),                 patch.object(lean, "check_sound", lambda *a, **k: "checked"), patch.object(lean, "mux", lambda f, w, dest, **k: muxed.append((Path(f), Path(dest)))):
            lean.cmd_sound(Args(entry=str(d / "main.tsx"), composition="film", onto=str(film)))
        assert muxed and muxed[0][0] == film.resolve(), f"the sound is put on the film asked for: {muxed}"


def test_export_rebuilds_the_sound_when_a_file_it_uses_changes():
    # a review's finding: export rebuilt the sound only when score.json changed, so an edited voice, stem or Tone source shipped stale
    import os
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        (d / "media").mkdir()
        stem = d / "media" / "bed.wav"
        stem.write_bytes(b"one")
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
        score["stems"] = [{"file": "media/bed.wav", "at": 0}]
        (d / "score.json").write_text(json.dumps(score), encoding="utf-8")
        built = []

        def build(dd, s):
            built.append(1)
            Path(lean.outdir(dd) / "sound.wav").write_bytes(b"w")
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None),                 patch.object(lean, "mux", lambda *a, **k: None), patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "build_sound", build):
            lean.cmd_export(Args(film=str(d)))
            lean.cmd_export(Args(film=str(d)))
            assert len(built) == 1, "nothing changed: the sound is not built again"
            later = (Path(tmp) / "out" / "film" / "sound.wav").stat().st_mtime + 5
            os.utime(stem, (later, later))              # the stem is edited after the sound was built
            lean.cmd_export(Args(film=str(d)))
        assert len(built) == 2, f"an edited stem rebuilds the sound: built {len(built)} times"


def test_every_file_vd_new_writes_resolves_its_imports():
    # one film's maker: kit/standins/orbit.tsx imported ../methods/card-orbit, which vd new doesn't copy (the cut removed methods/)
    import re
    from unittest.mock import patch
    films = lean.worked_films()
    assert {"plusone", "stet", "onoma", "linden"} <= set(films), films
    with tempfile.TemporaryDirectory() as tmp, patch.object(lean, "OUTROOT", Path(tmp) / "out"):
        broken = []
        for kind, like in [(k, None) for k in lean.KINDS] + [(None, f) for f in films]:
            class A: pass
            a = A(); a.name = str(Path(tmp) / (kind or "like-" + like)); a.kind = kind; a.like = like
            d = lean.cmd_new(a)
            notice = d / "LICENSE-video-decompiler.txt"
            assert notice.is_file() and notice.read_bytes() == lean.CODE_NOTICE.read_bytes(), f"{kind or like}: the MIT notice goes with the copied code"
            for f in list(d.rglob("*.ts")) + list(d.rglob("*.tsx")):
                for spec in re.findall(r"""(?:from|import)\s+["'](\.[^"']+)["']""", f.read_text(encoding="utf-8", errors="replace")):
                    base = (f.parent / spec).resolve()
                    if not any(Path(str(base) + ext).is_file() for ext in ("", ".ts", ".tsx", ".js", "/index.ts", "/index.tsx")):
                        broken.append(f"{kind or like}: {f.relative_to(d)} imports {spec}")
            if like:
                # a worked film's sound.py ran in the copy: its wav (not shipped) is there and is the score's sound, which export copies on
                s = json.loads((d / "score.json").read_text(encoding="utf-8"))
                wav = d / "media" / "sound.wav"
                assert wav.is_file() and wav.stat().st_size > 48000 * 4 * s["duration"] * 0.9, f"{like}: sound.py wrote the whole sound"
                assert s.get("sound_file") == "media/sound.wav", s
                if like == "plusone":
                    assert (d / "kit" / "times.gen.ts").is_file(), "plusone's sound.py writes the times its picture imports"
                    gen = lean.gen_data(d)
                    assert gen["CLOCK"] == {"FPS": s["fps"], "FB": 32, "BEATS": 72, "DURATION": s["duration"], "BPM": s["bpm"]}, (gen["CLOCK"], s)
                    assert len(gen["CUES"]) == 32 and all(isinstance(t, float) for _, t in gen["CUES"]), gen["CUES"][:3]
                    shipped = (lean.FILMS / like / "kit" / "times.gen.ts").read_text(encoding="utf-8")
                    assert (d / "kit" / "times.gen.ts").read_text(encoding="utf-8") == shipped, "the library's times.gen.ts is what its sound.py writes"
                assert lean.default_moments(s) and max(lean.default_moments(s)) < s["duration"], "a score with no beats still has moments to look at"
        assert not broken, "; ".join(broken)


def test_vd_new_like_refuses_a_name_that_exists_and_kind_with_like():
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "taken").mkdir()
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "new", "taken", "--like", "stet"], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        assert p.returncode != 0 and "exists" in p.stderr and not list((Path(tmp) / "taken").iterdir()), p.stderr
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "new", "x", "--like", "stet", "--kind", "launch"], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        assert p.returncode != 0 and "not allowed with" in p.stderr and not (Path(tmp) / "x").exists(), p.stderr
    help_ = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "new", "--help"], capture_output=True, text=True, encoding="utf-8").stdout
    for name, line in lean.worked_films().items():
        assert f"  {name:10} {line}" in help_, help_
    # the one line comes from the README's first line that is not a heading, else the folder's name
    with tempfile.TemporaryDirectory() as tmp:
        from unittest.mock import patch
        for name, readme in (("told", "# Told\n\nA film about a thing.\n\nMore."), ("bare", None)):
            (Path(tmp) / name).mkdir()
            (Path(tmp) / name / "main.tsx").write_text("//", encoding="utf-8")
            if readme:
                (Path(tmp) / name / "README.md").write_text(readme, encoding="utf-8")
        with patch.object(lean, "FILMS", Path(tmp)):
            assert lean.worked_films() == {"bare": "bare", "told": "A film about a thing."}


def test_look_labels_a_tile_with_the_compositions_own_time():
    # the plusone copy at 60 a second: --at 2,9 drew frames 120 and 540, labelled "4.00 s f120" and "18.00 s f540",
    # because look.py divided by the 30 fps_of falls back to for fps={FPS}
    import look
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "main.tsx").write_text('import { FPS } from "./film";\n<Composition id={FILM_ID} component={Film} width={W} height={H} fps={FPS} durationInFrames={F} />', encoding="utf-8")
        (d / "film.tsx").write_text('import score from "./score.json" with { type: "json" };\nexport const FPS = score.fps;', encoding="utf-8")
        (d / "score.json").write_text(json.dumps({"fps": 60}), encoding="utf-8")
        assert look.fps_of(d / "main.tsx", "film") == 60.0, "the frame rate the entry reads from its score.json"
        (d / "render.json").write_text(json.dumps({"width": 1920, "height": 1080, "fps": 60.0}), encoding="utf-8")
        labels, fps = look.tile_labels([120, 540], d, 30.0)
        assert fps == 60.0 and labels == ["2.00 s  f120", "9.00 s  f540"], (labels, fps)
        (d / "render.json").unlink()
        assert look.tile_labels([120], d, 24.0) == (["5.00 s  f120"], 24.0), "with no manifest, the rate it was asked at"
        (d / "score.json").unlink()
        assert look.fps_of(d / "main.tsx", "film", say=False) == 30.0
        (d / "main.tsx").write_text('<Composition id="film" component={F} fps={50} />', encoding="utf-8")
        assert look.fps_of(d / "main.tsx", "film") == 50.0


def test_a_range_splice_encodes_in_the_queue_at_its_turn():
    # the splice re-encodes the whole picture: it goes through heavy.py, which gives ffmpeg its turn at once and says what it waits for
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        ran = []
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None),                 patch.object(lean, "range_entry", lambda d, s, f0, n: d / "main.tsx"), patch.object(lean, "run", lambda args, **k: ran.append([str(x) for x in args])):
            pic = lean.picture_path(lean.outdir(d), d.name, lean.entry_of(d), "film")
            pic.write_bytes(b"p")
            try:
                lean.cmd_render(Args(film=str(d), from_="0", to="0.5"))
            except FileNotFoundError:
                pass                      # the fake splice wrote nothing to move into place
        enc = [a for a in ran if any(x.endswith("heavy.py") for x in a)]
        assert enc and "ffmpeg" in enc[0], f"the splice runs as python heavy.py -- ffmpeg ...: {ran}"


def test_a_splice_from_the_start_or_to_the_end_has_no_empty_piece():
    a = lean.splice_args("old.mp4", "part.mp4", "new.mp4", 0, 90, total=300)
    fc = a[a.index("-filter_complex") + 1]
    assert "end_frame=0" not in fc and "concat=n=2" in fc, fc
    b = lean.splice_args("old.mp4", "part.mp4", "new.mp4", 30, 300, total=300)
    fc = b[b.index("-filter_complex") + 1]
    assert "start_frame=300" not in fc and "concat=n=2" in fc, fc


def test_a_range_mid_film_is_its_own_frames_and_each_join_is_checked():
    # one film's cut 3 jumped at frames 270 and 360, cause unknown: the range is rendered as itself (a lead-in changed
    # nothing measurable) and after the splice both joins are checked, so a seam is named whatever caused it
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        ranges, ran, checked = [], [], []

        def fake_run(args, **k):
            ran.append([str(x) for x in args])
            Path(str(args[-1])).write_bytes(b"spliced")          # the splice's output, moved into place after
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), \
                patch.object(lean, "must_preflight", lambda *a, **k: None), patch.object(lean, "run", fake_run), \
                patch.object(lean, "range_entry", lambda d, s, f0, n: ranges.append((f0, n)) or d / "main.tsx"), \
                patch.object(lean, "join_report", lambda film, joins: checked.append(joins) or "joins: checked"):
            pic = lean.picture_path(lean.outdir(d), d.name, lean.entry_of(d), "film")
            pic.write_bytes(b"p")
            lean.cmd_render(Args(film=str(d), from_="0.3", to="0.6"))
        assert ranges == [(9, 9)], f"the range starts at its own first frame: {ranges}"
        fc = ran[-1][ran[-1].index("-filter_complex") + 1]
        assert "[1:v]setpts=PTS-STARTPTS[b]" in fc and "[1:v]trim" not in fc, fc
        assert checked == [[9, 18]], f"both joins are checked after the splice: {checked}"


def made_film(path, pop_at=None, n=60):
    """A slow gradient pan; with pop_at, one frame that jumps, as a join that pops does."""
    import subprocess
    w, h = 160, 90
    frames = []
    for i in range(n):
        x = np.tile(np.linspace(0, 255, w), (h, 1)) * 0.6 + i * 0.8
        if pop_at is not None and i == pop_at:
            x = x + 40
        frames.append(np.clip(x, 0, 255).astype(np.uint8))
    raw = np.stack([np.stack([f, f, f], -1) for f in frames]).tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                    "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", str(path)], input=raw, check=True)
    return path


def test_the_join_check_names_a_join_that_pops_and_passes_a_clean_one():
    import subprocess
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        bad = lean.join_report(made_film(Path(tmp) / "bad.mp4", pop_at=30), [30])
        good = lean.join_report(made_film(Path(tmp) / "good.mp4"), [30])
    assert "changes more than the frames round it" in bad and "frame 30" in bad, bad
    assert "clean" in good and "pops" not in good, good
    # A4: frames are counted in the file's own frames on a variable-rate film (40 at 20 fps, then 80 at 60 fps) with
    # a pop at frame 60; read at one rate the 20 fps frames came three times over and frame 60 was a held frame
    w, h = 160, 90
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for k, (first, count, fps) in enumerate(((0, 40, 20), (40, 80, 60))):
            frames = []
            for i in range(first, first + count):
                x = np.tile(np.linspace(0, 255, w), (h, 1)) * 0.6 + i * 0.8 + (45 if i == 60 else 0)
                frames.append(np.clip(x, 0, 255).astype(np.uint8))
            part = Path(tmp) / f"part{k}.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                            "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", "-video_track_timescale", "600", str(part)],
                           input=np.stack(frames).tobytes(), check=True)
            parts.append(part)
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{q.as_posix()}'\n" for q in parts), encoding="utf-8")
        vfr = Path(tmp) / "vfr.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(vfr)], check=True)
        said = lean.join_report(vfr, [60])
        quiet = lean.join_report(vfr, [90])
    assert "frame 60 changes more than the frames round it" in said, said
    assert "frame 90 clean" in quiet, quiet
    ran = []
    with patch.object(lean, "run", lambda *a, **k: ran.append(a)):
        assert lean.join_report(Path("no-such.mp4"), []) == "joins: none inside the film" and not ran, ran


def test_a_look_that_raea_refuses_ends_on_raeas_plain_reason():
    # A1b: with no preflight before a page film's look, a composition that throws is said by look.py: one line naming
    # the composition and raea's own reason, not the JS stack lines raea prints before it
    import contextlib
    import io
    import look
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        entry = Path(tmp) / "main.tsx"
        entry.write_text("// a film\n", encoding="utf-8")
        said = ["[ERROR raea_runtime_react::thread] [js] [js] react error:     at Film (bundle.js:15091:54)",
                "REFUSED  the composition threw at frame 239: Error: planted at frame 239"]
        out = io.StringIO()
        with patch.object(look, "draw", lambda *a, **k: (0.0, 0.3, 1, said, "")), patch.object(look, "fps_of", lambda *a, **k: 60), \
                patch.object(sys, "argv", ["look.py", str(entry), "--at", "60,239", "--frames", "--composition", "film-look", "-o", str(Path(tmp) / "l.jpg")]), \
                contextlib.redirect_stdout(out):
            try:
                look.main()
                raise AssertionError("a refused look exits 1")
            except SystemExit as e:
                assert e.code == 1, e.code
        line = out.getvalue().strip().splitlines()[-1]
        assert line.startswith("FAILED raea rc 1 drawing film-look") and line.endswith("the composition threw at frame 239: Error: planted at frame 239"), line
        assert "bundle.js" not in line, line
        # a bare REFUSED line is no reason: the error line is said, not an empty reason (a review's finding)
        out = io.StringIO()
        with patch.object(look, "draw", lambda *a, **k: (0.0, 0.3, 1, ["error: the real reason", "REFUSED"], "")), patch.object(look, "fps_of", lambda *a, **k: 60), \
                patch.object(sys, "argv", ["look.py", str(entry), "--at", "60,239", "--frames", "--composition", "film-look", "-o", str(Path(tmp) / "l.jpg")]), \
                contextlib.redirect_stdout(out):
            try:
                look.main()
                raise AssertionError("a refused look exits 1")
            except SystemExit as e:
                assert e.code == 1, e.code
        assert out.getvalue().strip().splitlines()[-1].endswith("error: the real reason"), out.getvalue()


def test_a_remixed_export_reuses_the_hand_in_only_of_the_same_picture():
    # A2: an export of an unchanged picture under a new sound reuses the last hand-in's share video and sheets; a picture
    # drawn again, replaced, or a share copy changed since gets a fresh encode
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pic = tmp / "f.main.film.picture.mp4"

        def draw(colour):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=128x72:r=30:d=2,hue=h={colour}", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(pic)], check=True)
            lean.picture_note(pic).write_text(json.dumps({"files": {}, "drawn": lean.drawn_record(pic)}), encoding="utf-8")   # as a draw writes it

        def sound(name, hz):
            wav = tmp / name
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={hz}:d=2", "-ac", "2", "-ar", "48000", str(wav)], check=True)
            return wav

        def cut(n, wav):
            c = tmp / "cuts" / f"f-cut{n}.mp4"
            c.parent.mkdir(exist_ok=True)
            lean.mux(pic, wav, c, tag601=True)
            return c

        def frames(f, sel):
            return subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-map", sel, "-f", "framemd5", "-"], capture_output=True, text=True).stdout

        draw(0)
        one = cut(1, sound("a.wav", 440))
        lean.hand_in(one)
        lean.note_hand_in(one, pic)
        two = cut(2, sound("b.wav", 660))
        got = lean.hand_in_again(two, pic)
        assert got, "an unchanged picture's hand-in is reused"
        share, sheets = got
        fresh = tmp / "fresh" / two.name
        fresh.parent.mkdir()
        fresh.write_bytes(two.read_bytes())
        fresh_share, fresh_sheets = lean.hand_in(fresh)
        assert frames(share, "0:v:0") == frames(fresh_share, "0:v:0") and frames(share, "0:a:0") == frames(fresh_share, "0:a:0")
        assert [p.read_bytes() for p in sheets] == [p.read_bytes() for p in fresh_sheets] and sheets
        lean.note_hand_in(two, pic)
        three = cut(3, sound("c.wav", 330))
        one_share = one.with_name(one.stem + "-share.mp4")
        draw(120)                                  # the picture drawn again: the note keeps no hand-in
        assert lean.hand_in_again(three, pic) is None, "a picture drawn again gets a fresh encode"
        lean.hand_in(three)
        lean.note_hand_in(three, pic)
        four = cut(4, sound("d.wav", 550))
        three_share = three.with_name(three.stem + "-share.mp4")
        three_share.write_bytes(one_share.read_bytes())      # the last share copy is no longer the one made
        assert lean.hand_in_again(four, pic) is None, "a share copy changed since is not reused"
        lean.hand_in(three)
        lean.note_hand_in(three, pic)
        pic.write_bytes(pic.read_bytes() + b"\0")             # something put at the picture's name, not drawn
        assert lean.hand_in_again(four, pic) is None, "a picture not as drawn is not reused"
        # a damaged note (no cut name, or a path where the name belongs) is made afresh, not a crash (a review's finding)
        for name in ("", "sub/cut.mp4"):
            note = {"drawn": lean.drawn_record(pic), "hand_in": {"cut": name, "drawn": lean.drawn_record(pic)}}
            lean.picture_note(pic).write_text(json.dumps(note), encoding="utf-8")
            assert lean.hand_in_again(four, pic) is None, f"a note naming the cut {name!r} is not reused"


def test_look_says_what_happened_to_the_bundle():
    # rc4 prints no bundle line on look's path, and its silence was read as "cached" after the film changed
    import look
    folder = Path("cache")
    assert "built afresh" in look.bundle_said({"a.js": (1, 10)}, {"a.js": (1, 10), "b.js": (2, 4096)}, [], folder)
    assert look.bundle_said({"a.js": (1, 10)}, {"a.js": (5, 10)}, [], folder).startswith("bundle: reused (a.js)")   # rc4 rewrites a key it had
    same = look.bundle_said({"a.js": (1, 10)}, {"a.js": (1, 10)}, [], folder)
    assert same.startswith("bundle: reused") and "same starter" in same and "cached" not in same
    assert "not known" in look.bundle_said(None, None, [], folder)
    assert "built afresh (x in 9 ms" in look.bundle_said({}, {}, ["raea bundle: x in 9 ms"], folder)


def test_look_leaves_out_exposure_warnings_on_a_light_ground():
    # one film's light page drew 20 "clip to white / washed out" warnings a look; a dark film's blown light still warns
    import look
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        light, dark = Path(tmp) / "frame-00000.png", Path(tmp) / "frame-00001.png"
        a = np.full((180, 320), 241, np.uint8); a[40:140, 100:300] = 255
        b = np.full((180, 320), 20, np.uint8); b[40:140, 100:300] = 255
        Image.fromarray(a).save(light); Image.fromarray(b).save(dark)
        lit = look.light_frames([light, dark])
        ground = look.grounds([light, dark])
        # B6: look decodes each still once and hands the pictures round; the grounds from them are the ones read from
        # the files (RGB stills and a grey one, as Pillow reads each to grey with one matrix)
        rgb = Path(tmp) / "frame-00002.png"
        c = np.random.default_rng(2).integers(0, 256, (180, 320, 3), dtype=np.uint8)
        Image.fromarray(c).save(rgb)
        pngs = [light, dark, rgb]
        decoded = {p: Image.open(p).convert("RGB") for p in pngs}
        assert look.grounds(pngs, decoded) == look.grounds(pngs) and look.light_frames(pngs, decoded=decoded) == look.light_frames(pngs)
    assert list(lit) == ["frame-00000.png"] and lit["frame-00000.png"] > 0.9
    said = ["render warn: frame-00000.png: 30% of the pixels clip to white", "raea: warn exposure: frame-00000.png: +2.3 stops over mid grey: the frame reads washed out",
            "render warn: frame-00001.png: 31% of the pixels clip to white", "render warn: frame-00000.png: text overflows its box"]
    kept, gone = look.quiet_exposure(said, lit)
    assert gone == 2 and kept == said[2:], kept
    # one film's space: 3 to 4 stops under mid grey on every frame, dark on purpose; its blown light still warns
    said = ["raea: warn exposure: frame-00001.png: -3.4 stops under mid grey", "render warn: frame-00001.png: 31% of the pixels clip to white",
            "raea: warn exposure: frame-00000.png: -3.4 stops under mid grey"]
    kept, gone = look.quiet_exposure(said, ground)
    assert gone == 1 and kept == said[1:], kept


def test_every_command_ends_on_the_path_it_made():
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "new", "f", "--kind", "app"], cwd=tmp,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stdout
        lines = p.stdout.strip().splitlines()
        assert lines[-1] == str((Path(tmp) / "f").resolve()) and lines[-2].startswith("vd new:"), lines[-3:]
    # each command that makes something records it; main prints the last one
    src = (TOOLS / "lean.py").read_text(encoding="utf-8")
    for cmd in ("cmd_new", "cmd_look", "cmd_sound", "cmd_render", "cmd_export", "cmd_measure", "cmd_pin", "cmd_pack", "cmd_profile", "cmd_scan",
                "cmd_borrow", "cmd_capture", "cmd_launch", "cmd_foley", "cmd_evolve", "cmd_playable", "cmd_audio", "cmd_bridge"):
        body = src.split(f"def {cmd}(", 1)[1].split("\ndef ", 1)[0]
        assert "made_it(" in body, f"{cmd} doesn't say what it made"


def _clean(*args):
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = lean.main(["clean", *args])
    return code, out.getvalue()


def _out_root():
    root = Path(tempfile.mkdtemp())
    keep, lean.OUTROOT = lean.OUTROOT, root / "out"
    lean.OUTROOT.mkdir()
    return root, keep


def _refused(*args):
    try:
        _clean(*args)
    except SystemExit:
        return True
    return False


def _drawn(pic, data=b"x" * 1000):
    """A picture as an export leaves it: the file, and its note recording what was drawn."""
    pic.write_bytes(data)
    lean.picture_note(pic).write_text(json.dumps({"files": {}, "drawn": lean.drawn_record(pic)}), encoding="utf-8")
    return pic


def test_clean_lists_first_and_removes_only_what_is_made_again():
    # ~/.vd/out grew without end (13 GB in 107 folders on the laptop these films were made on): vd clean lists what an
    # export makes again, removes it only with --yes, and never a finished cut, a share copy, a sheet or a note
    root, keep = _out_root()
    try:
        film = root / "film"
        film.mkdir()
        o = lean.OUTROOT / "f"
        (o / "cuts").mkdir(parents=True)
        (o / "sub").mkdir()
        (o / "frames").mkdir()
        (o / lean.OWNER).write_text(str(film) + "\n", encoding="utf-8")
        rebuilt = ["f.main.film.picture.mp4", "f.main.film.picture.mp4.sources.json", "f.main.film.picture.part.render.json"]
        # a finished film in sub/ (Linden's linden-sub.mp4 is one), frames nothing remakes, and what vd sound writes
        # without the lock all stay: plain clean had removed them (a review's finding)
        kept = ["f.mp4", "f-share.mp4", "scan.txt", "sound.wav", "sound-raw.wav", "GAP.md", "pack-1-KEY.txt",
                "sub/f-sub.mp4", "frames/frame-00001.png", "look.jpg.render.json"]
        cuts = [f"cuts/{stem}-cut{n}{tail}" for stem in ("f", "g") for n in (1, 2, 10) for tail in (".mp4", "-share.mp4", "-sheet_000.jpg")]
        for rel in rebuilt + kept + cuts:
            (o / rel).write_bytes(b"x" * 1000)
        _drawn(o / "f.main.film.picture.mp4")
        code, said = _clean()
        assert code == 0 and all((o / r).exists() for r in rebuilt + kept + cuts), "without --yes nothing goes"
        assert "f.main.film.picture.mp4" in said and "-cut" not in said, said
        _clean("--yes")
        assert not any((o / r).exists() for r in rebuilt), "what is made again goes"
        assert all((o / r).exists() for r in kept + cuts), "cuts, exports, scans, the mix and notes stay"
        # cuts are dropped one named folder at a time, and --keep goes with --keep-cuts and names a cut that is there
        assert _refused("--keep-cuts", "2", "--yes"), "--keep-cuts across every folder"
        (lean.OUTROOT / "g2").mkdir()
        assert _refused("f", "g2", "--keep-cuts", "2", "--yes"), "--keep-cuts across two named folders"
        (o / "cuts" / "f-cut99.mp4").mkdir()   # a folder named like a cut is no cut to keep
        assert _refused("f", "--keep-cuts", "1", "--keep", "99", "--yes"), "--keep of a folder named like a cut"
        (o / "cuts" / "f-cut99.mp4").rmdir()
        assert _refused("f", "--keep", "1", "--yes"), "--keep without --keep-cuts"
        assert _refused("f", "--keep-cuts", "1", "--keep", "20", "--yes"), "--keep of a cut that is not there"
        for bad in ("0", "-1"):
            assert _refused("f", "--keep-cuts", bad, "--yes"), f"--keep-cuts {bad}"
        assert all((o / r).exists() for r in cuts), "a refused run removes nothing"
        # --keep-cuts 2 keeps each film name's two newest: 2 and 10 of f and of g (cut 1's files are not cut 10's)
        _clean("f", "--keep-cuts", "2", "--yes")
        for stem in ("f", "g"):
            assert not any((o / f"cuts/{stem}-cut1{t}").exists() for t in (".mp4", "-share.mp4", "-sheet_000.jpg")), stem
            assert all((o / f"cuts/{stem}-cut{n}{t}").exists() for n in (2, 10) for t in (".mp4", "-share.mp4", "-sheet_000.jpg")), stem
        # --keep protects a cut whatever its age
        (o / "cuts/f-cut1.mp4").write_bytes(b"accepted")
        _clean("f", "--keep-cuts", "1", "--keep", "1", "--yes")
        assert (o / "cuts/f-cut1.mp4").exists() and (o / "cuts/f-cut10.mp4").exists() and not (o / "cuts/f-cut2.mp4").exists()
        # a folder an export holds is skipped, not cleared under it
        _drawn(o / "f.main.film.picture.mp4")
        with lean.held(o, "export"):
            code, said = _clean("--yes")
            assert (o / "f.main.film.picture.mp4").exists() and "in use" in said, said
    finally:
        lean.OUTROOT = keep


def test_clean_matches_names_as_text_and_keeps_a_films_own_export():
    # broke: a cut's files were found with a glob built from the film's name, so film[1]'s old cut took film1's only
    # cut; and a film folder called x.picture exports x.picture.mp4, which matched the pattern of what is made again
    root, keep = _out_root()
    try:
        o = lean.OUTROOT / "f"
        (o / "cuts").mkdir(parents=True)
        q = __import__("os").name != "nt"   # Windows does not allow ? in a file name; [ it does
        for name in ("film[1]-cut1.mp4", "film[1]-cut2.mp4", "film1-cut1.mp4") + (("film?-cut1.mp4", "film?-cut2.mp4") if q else ()):
            (o / "cuts" / name).write_bytes(b"film")
        # cut 1 of foo goes with what an export wrote beside it, and foo-cut1-alt's only cut is not one of them
        foo1 = ["foo-cut1.mp4", "foo-cut1-share.mp4", "foo-cut1-sheet.jpg", "foo-cut1-sheet_000.jpg", "foo-cut1.part.mp4"]
        for name in foo1 + ["foo-cut2.mp4", "foo-cut1-alt-cut1.mp4", "foo-cut1-alt-cut1-share.mp4"]:
            (o / "cuts" / name).write_bytes(b"film")
        _clean("f", "--keep-cuts", "1", "--yes")
        assert not any((o / "cuts" / n).exists() for n in foo1), "foo's cut 1 and its companions go"
        assert all((o / "cuts" / n).exists() for n in ("foo-cut2.mp4", "foo-cut1-alt-cut1.mp4", "foo-cut1-alt-cut1-share.mp4")), \
            "foo-cut1-alt's only cut stays"
        assert (o / "cuts/film1-cut1.mp4").exists(), "film1's only cut stays"
        assert not (o / "cuts/film[1]-cut1.mp4").exists() and (o / "cuts/film[1]-cut2.mp4").exists()
        if q:
            assert not (o / "cuts/film?-cut1.mp4").exists() and (o / "cuts/film?-cut2.mp4").exists()
        p = lean.OUTROOT / "x.picture"
        p.mkdir()
        (p / "x.picture.mp4").write_bytes(b"the export")
        (p / "x.picture-share.mp4").write_bytes(b"its share copy")
        _drawn(p / "x.picture.main.film.picture.mp4")
        # the film's own export, even beside a note: a note that does not record this very file does not make it a picture
        lean.picture_note(p / "x.picture.mp4").write_text(json.dumps({"files": {}, "drawn": {"size": 1, "mtime_ns": 1}}), encoding="utf-8")
        # vd export -o OUT/custom.picture.mp4 is a finished film: no note says an export drew it, so it stays
        (p / "custom.picture.mp4").write_bytes(b"a finished film")
        # a finished film published at a former picture's name, its old note still there: it stays (a review's finding)
        _drawn(p / "y.main.film.picture.mp4", b"the old picture")
        (p / "film.mp4").write_bytes(b"a finished film, longer than the picture")
        lean.publish(p / "film.mp4", p / "y.main.film.picture.mp4")
        code, said = _clean("--yes")
        assert (p / "x.picture.mp4").exists() and (p / "x.picture-share.mp4").exists(), "the film's own export stays"
        assert (p / "custom.picture.mp4").exists(), "a finished film named like a picture stays"
        assert (p / "y.main.film.picture.mp4").read_bytes() == b"a finished film, longer than the picture", "a film published over a picture stays"
        assert not (p / "x.picture.main.film.picture.mp4").exists()
        assert "left 3 *.picture.mp4" in said, said
    finally:
        lean.OUTROOT = keep


def test_clean_never_reaches_outside_its_folder():
    # broke: `vd clean ../outside --yes` cleaned a folder beside VD_OUT, and a linked folder took it anywhere
    import os
    import subprocess
    root, keep = _out_root()
    try:
        outside = root / "outside"
        outside.mkdir()
        (outside / "f").mkdir()
        _drawn(outside / "film.main.film.picture.mp4", b"precious")     # drawn: a clean that went there would take it
        _drawn(outside / "f" / "f.main.film.picture.mp4", b"precious")
        for name in ("../outside", str(outside), "..", "a/b"):
            assert _refused(name, "--yes"), f"{name} was taken"
        link = lean.OUTROOT / "linked"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=True)
        else:
            os.symlink(outside, link)
        _clean("--yes")
        assert _refused("linked", "--yes"), "a linked folder named is refused"
        assert (outside / "film.main.film.picture.mp4").exists(), "nothing through a link"
        # VD_OUT itself a link: everything under it is through the link, named or not (a review's finding)
        lean.OUTROOT = root / "linked-out"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(lean.OUTROOT), str(outside)], capture_output=True, check=True)
        else:
            os.symlink(outside, lean.OUTROOT)
        assert _refused("--yes") and _refused("f", "--yes") and _refused(), "a linked VD_OUT is refused"
        assert (outside / "f" / "f.main.film.picture.mp4").exists(), "nothing through a linked VD_OUT"
        # a relative VD_OUT, from a folder reached through the link: the walk up stopped at "." (a council's finding).
        # Windows keeps the junction in the current folder's path; Linux and macOS give the real folder, so there a
        # relative VD_OUT crosses no link and is not refused
        (outside / "inner" / "rel" / "g").mkdir(parents=True)
        _drawn(outside / "inner" / "rel" / "g" / "g.main.film.picture.mp4", b"precious")
        here = os.getcwd()
        os.chdir(lean.OUTROOT / "inner")
        try:
            lean.OUTROOT = Path("rel")
            if os.name == "nt":
                assert _refused("--yes") and _refused(), "a relative VD_OUT under a link is refused"
        finally:
            os.chdir(here)
        if os.name == "nt":
            assert (outside / "inner" / "rel" / "g" / "g.main.film.picture.mp4").exists(), "nothing through a relative VD_OUT"
        # link/.. in VD_OUT: the path as written passes through the link, though abspath folds it away (a council's finding)
        lean.OUTROOT = root / "linked-out" / ".." / "outside"
        assert _refused("--yes") and _refused(), "a VD_OUT that passes through a link is refused"
        if os.name == "nt":
            # a drive-relative VD_OUT (C:rel) while the current folder is on another drive: joined to that folder it
            # stays C:rel, and only Windows's own resolution (the drive's current folder, here inside the junction)
            # shows the link (a council's finding)
            from unittest.mock import patch
            os.chdir(root / "linked-out" / "inner")
            try:
                lean.OUTROOT = Path(Path(os.getcwd()).drive + "rel")
                with patch("os.getcwd", lambda: r"Z:\elsewhere"):
                    assert _refused("--yes") and _refused(), "a drive-relative VD_OUT under a link is refused"
            finally:
                os.chdir(here)
    finally:
        lean.OUTROOT = keep


def test_clean_orphans_are_named_never_removed():
    # broke: --orphans removed whole folders whose film folder read as gone: an unplugged drive, a moved project, a
    # film saved as .MOV or .MP4 (not matched on Linux), and blind-read and evolve keys that nothing else holds
    root, keep = _out_root()
    try:
        o = lean.OUTROOT / "gone"
        (o / "cuts").mkdir(parents=True)
        (o / lean.OWNER).write_text(str(root / "no-such-film") + "\n", encoding="utf-8")
        held_things = ["final.MP4", "take.mov", "pack-1-KEY.txt", "evolve-1-KEY.txt", "sound.wav", "cuts/gone-cut1.mp4"]
        for rel in held_things:
            (o / rel).write_bytes(b"keep me")
        _drawn(o / "gone.main.film.picture.mp4")
        code, said = _clean("--orphans", "--yes")
        assert "no-such-film is not there" in said, said
        assert all((o / r).exists() for r in held_things), "an orphan folder keeps everything but what is made again"
        assert not (o / "gone.main.film.picture.mp4").exists()
    finally:
        lean.OUTROOT = keep


def test_clean_skips_a_file_open_elsewhere_and_goes_on():
    # broke: a picture open in a player on Windows stopped clean with a traceback, and later folders were not cleaned
    import os
    if os.name != "nt":
        return   # elsewhere an open file can be removed
    root, keep = _out_root()
    try:
        a, b = lean.OUTROOT / "a", lean.OUTROOT / "b"
        a.mkdir()
        b.mkdir()
        _drawn(a / "a.main.film.picture.mp4", b"open")
        _drawn(b / "b.main.film.picture.mp4", b"closed")
        with open(a / "a.main.film.picture.mp4", "rb"):
            code, said = _clean("--yes")
        assert code == 0 and "open elsewhere" in said and not (b / "b.main.film.picture.mp4").exists(), said
        assert (a / "a.main.film.picture.mp4.sources.json").exists(), "the open picture keeps its note"
        assert not (b / "b.main.film.picture.mp4.sources.json").exists()
        code, said = _clean("--yes")   # closed now, it is still known as drawn and goes
        assert not (a / "a.main.film.picture.mp4").exists(), said
    finally:
        lean.OUTROOT = keep


def test_clean_removes_only_what_it_listed():
    # broke: what goes was decided again under the lock and all of it removed, so a cut that finished between the list
    # and the lock made cut 2 "older" and it went without being named (a review's finding); and a picture replaced in
    # that moment must stay too
    from contextlib import contextmanager
    from unittest.mock import patch
    root, keep = _out_root()
    try:
        o = lean.OUTROOT / "f"
        (o / "cuts").mkdir(parents=True)
        for n in (1, 2):
            (o / "cuts" / f"f-cut{n}.mp4").write_bytes(b"cut")
        _drawn(o / "f.main.film.picture.mp4")
        real = lean.held

        @contextmanager
        def meanwhile(folder, what):
            (o / "cuts" / "f-cut3.mp4").write_bytes(b"cut 3, finished just now")
            (o / "film.mp4").write_bytes(b"a finished film put at the picture's name")
            lean.publish(o / "film.mp4", o / "f.main.film.picture.mp4")
            with real(folder, what):
                yield
        with patch.object(lean, "held", meanwhile):
            code, said = _clean("f", "--keep-cuts", "1", "--yes")
        assert not (o / "cuts/f-cut1.mp4").exists(), "the listed cut goes"
        assert (o / "cuts/f-cut2.mp4").exists() and "f-cut2.mp4" in said.split("not in the list above")[-1], said
        assert (o / "f.main.film.picture.mp4").read_bytes().startswith(b"a finished film"), "a picture replaced since the list stays"
    finally:
        lean.OUTROOT = keep


def test_takeover_moves_the_other_films_work_aside():
    # broke: when B/Twin took over A/Twin's output folder, A's cuts stayed in cuts/ under the same name, so B's cut 2 made
    # A's only cut "older" and vd clean Twin --keep-cuts 1 removed it; and takeover deleted a finished final.picture.mp4
    # (a review's finding)
    root, keep = _out_root()
    try:
        a, b = root / "A" / "Twin", root / "B" / "Twin"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        o = lean.outdir(a)
        (o / "cuts").mkdir()
        (o / "bridge").mkdir()
        for rel, data in (("cuts/Twin-cut1.mp4", b"A's only cut"), ("Twin.mp4", b"A's latest"), ("Twin-share.mp4", b"A's share"),
                          ("Twin-sheet.jpg", b"A's sheet"), ("final.picture.mp4", b"A's finished film"), ("bridge/cues.xml", b"A's timeline"),
                          ("sound.wav", b"A's built sound")):
            (o / rel).write_bytes(data)
        _drawn(o / "Twin.main.film.picture.mp4", b"A's drawn picture")
        assert lean.outdir(b) == o
        aside = o / "earlier-folder" / "1"
        for rel in ("cuts/Twin-cut1.mp4", "Twin.mp4", "Twin-share.mp4", "Twin-sheet.jpg", "final.picture.mp4", "bridge/cues.xml"):
            assert (aside / rel).exists() and not (o / rel).exists(), f"{rel} moved aside"
        assert not (o / "Twin.main.film.picture.mp4").exists() and not (o / "sound.wav").exists(), "what an export makes again goes"
        assert lean.cut_of(o, "Twin")[0] == 1, "B's cuts start again at 1"
        (o / "cuts").mkdir()
        for n in (1, 2):
            (o / "cuts" / f"Twin-cut{n}.mp4").write_bytes(b"B's cut")
        _clean("Twin", "--keep-cuts", "1", "--yes")
        assert (aside / "cuts/Twin-cut1.mp4").read_bytes() == b"A's only cut", "A's cut is not B's to drop"
        assert not (o / "cuts/Twin-cut1.mp4").exists() and (o / "cuts/Twin-cut2.mp4").exists()
    finally:
        lean.OUTROOT = keep


def test_a_failed_export_never_removes_a_cut_already_filed():
    # broke: cut_of globbed draft[1]-cut*.mp4, where [1] is a set of characters, so draft[1]'s cut 1 was not seen, cut 1
    # was given again, and the failed export's rollback deleted the cut already filed (a review's finding)
    import argparse
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "cuts").mkdir()
        for name in ("draft[1]-cut1.mp4", "draft[1]-cut1-share.mp4", "draft[1]-cut1-sheet.jpg", "draft1-cut4.mp4", "Draft-cut1.mp4",
                     "solo-cut2-share.mp4"):
            (out / "cuts" / name).write_bytes(b"filed")
        assert lean.cut_of(out, "draft[1]")[0] == 2 and lean.cut_of(out, "draft1")[0] == 5
        # does this filesystem keep names that differ only in case apart? found by writing one and looking for the other
        probe = out / "CaseProbe.txt"
        probe.write_bytes(b"x")
        blind = (out / "caseprobe.txt").exists()
        probe.unlink()
        # clean groups cuts by the name as written: never two films as one (STRASSE and Straße are two on Windows, and
        # grouping without case removed one's only cut: a council's finding); Draft and draft keep more than asked
        o = out / "f"
        (o / "cuts").mkdir(parents=True)
        for name in ("Draft-cut1.mp4", "draft-cut2.mp4", "draft-cut3.mp4", "STRASSE-cut1.mp4", "Straße-cut2.mp4"):
            (o / "cuts" / name).write_bytes(b"cut")
        gone = sorted(f.name for f, _, _ in lean.clean_plan(o, keep_cuts=1))
        assert gone == ["draft-cut2.mp4"], gone
        # on Windows Draft-cut1.mp4 is draft-cut1.mp4, so draft's next cut is 2 there (a council's finding); where names
        # keep their case (Linux, a case-sensitive Mac volume) Draft is another film and draft's next cut is 1. And a
        # number whose share copy is already there is passed over
        assert lean.cut_of(out, "draft")[0] == (2 if blind else 1) and lean.cut_of(out, "solo")[0] == 1
        assert lean.cut_of(out, "Straße")[0] == 1, "STRASSE's cuts are not Straße's"
        (out / "cuts" / "solo-cut1-share.mp4").write_bytes(b"filed")
        assert lean.cut_of(out, "solo")[0] == 3
        assert [f.name for f in lean.sheets_of(out / "cuts" / "draft[1]-cut1.mp4")] == ["draft[1]-cut1-sheet.jpg"]
        # where names differ only in case are one file (Windows, macOS), Draft's sheets are draft's: a re-export as Draft
        # left draft's old sheets behind (a council's finding); on Linux they are another film's
        (out / "draft-sheet_000.jpg").write_bytes(b"sheet")
        assert [f.name for f in lean.sheets_of(out / "Draft.mp4")] == (["draft-sheet_000.jpg"] if blind else []), blind
        # in a folder whose own name swaps case badly (Straße -> sTRASSE), the filesystem is still asked file by file
        # (a council's finding: the folder test said case-sensitive there and draft's sheets were missed)
        u = out / "Straße"
        u.mkdir()
        (u / "draft-sheet_000.jpg").write_bytes(b"sheet")
        (u / "STRASSE-sheet.jpg").write_bytes(b"another film's sheet")
        assert [f.name for f in lean.sheets_of(u / "Draft.mp4")] == (["draft-sheet_000.jpg"] if blind else []), blind
        assert [f.name for f in lean.sheets_of(u / "Straße.mp4")] == [], "STRASSE's sheet is not Straße's"
        # a name Python's case-blind matching takes for another but the filesystem may keep apart: the Kelvin sign K
        # matches k in a pattern without case, while Windows names Kiln and kiln as two files. The filesystem's
        # own answer decides (macOS, which folds the sign to K, may say they are one)
        (out / "kiln-sheet.jpg").write_bytes(b"kiln's sheet")
        kelvin = out / "Kiln-sheet.jpg"
        one = kelvin.exists() and __import__("os").path.samefile(kelvin, out / "kiln-sheet.jpg")
        assert [f.name for f in lean.sheets_of(out / "Kiln.mp4")] == (["kiln-sheet.jpg"] if one else []), one
        # whatever the numbering says, what was there under the cut's names before the export stays when it fails
        dest = out / "draft[1].mp4"

        def fails(a, cut=None, done=None):
            cut.with_name(cut.stem + ".part.mp4").write_bytes(b"begun")
            raise SystemExit("no sound")
        with patch.object(lean, "export_paths", lambda a: (out, out / "film.tsx", None, None, out, dest)), \
                patch.object(lean, "cut_of", lambda o, stem: (1, out / "cuts" / "draft[1]-cut1.mp4")), patch.object(lean, "_export", fails):
            try:
                lean.cmd_export(argparse.Namespace())
                raise AssertionError("the export failed")
            except SystemExit:
                pass
        for name in ("draft[1]-cut1.mp4", "draft[1]-cut1-share.mp4", "draft[1]-cut1-sheet.jpg"):
            assert (out / "cuts" / name).read_bytes() == b"filed", f"{name} was removed"
        assert not (out / "cuts" / "draft[1]-cut1.part.mp4").exists(), "what the export began is removed"


def test_not_proven_commands_say_so_where_they_run():
    # the newer commands were quarantined in prose only: each now says so on every run, and the list in the code is the
    # list SKILL.md marks "not proven", so the two cannot drift apart
    import re
    import subprocess
    skill = (TOOLS.parent / "SKILL.md").read_text(encoding="utf-8")
    marked = set()
    for line in skill.splitlines():
        if re.match(r"\|\s*`vd ", line) and "| not proven" in line:
            marked |= set(re.findall(r"`vd (\w+)", line.split("|")[1]))
    assert marked == lean.NOT_PROVEN, (marked, lean.NOT_PROVEN)
    with tempfile.TemporaryDirectory() as tmp:
        for cmd in sorted(lean.NOT_PROVEN):
            # --help: said before the arguments are read, so a call that only asks for help hears it, and nothing is made
            # (run bare, vd launch made a whole film folder in the folder the tests ran from)
            p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), cmd, "--help"], capture_output=True, cwd=tmp,
                               text=True, encoding="utf-8", env={**__import__("os").environ, "VD_OUT": tmp})
            assert f"vd {cmd} is not proven on a film yet" in p.stderr, (cmd, p.stderr)
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "clean"], capture_output=True, text=True,
                           encoding="utf-8", env={**__import__("os").environ, "VD_OUT": tmp})
        assert "not proven" not in p.stderr, "a proven command says nothing"


def test_steal_still_runs_as_borrow():
    # 0.2.0 called vd borrow vd steal: a person's `vd steal` still runs, through the front door, and says the new name
    import subprocess
    p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "steal", "--help"], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0 and "vd steal is now vd borrow" in p.stderr and "--like" in p.stdout, (p.stdout, p.stderr)


def test_export_help_says_where_the_film_goes():
    import subprocess
    out = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "export", "--help"], capture_output=True, text=True, encoding="utf-8").stdout
    flat = " ".join(out.split())
    assert "NAME.mp4" in flat and "unless -o names it" in flat, flat
    out = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "look", "--help"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "One moment gives that frame at full size" in " ".join(out.split()), out


def test_vd_profile_passes_the_window_on():
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        got = []

        class Done:
            returncode, stdout, stderr = 0, "", ""
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "run", lambda args, **k: got.append([str(x) for x in args]) or Done()):
            lean.cmd_profile(Args(film=str(d), transcript=[str(Path(tmp) / "s.jsonl")], since="2026-11-12T10:19:00Z", until="2026-11-12T10:37:00Z"))
        a = got[0]
        assert a[a.index("--since") + 1] == "2026-11-12T10:19:00Z" and a[a.index("--until") + 1] == "2026-11-12T10:37:00Z", a


def test_look_names_a_part_whose_shape_changes_between_its_moments():
    # one film's ring: <Torus major_radius={r(t)} /> kept its first radius, and looks taken in one call disagreed
    def frame(f, half):
        return {"frame": f, "entities": [{"components": {"Part": {"name": "ring", "own": [[-half, -half, -0.1], [half, half, 0.1]]}}},
                                         {"components": {"Part": {"name": "earth", "own": [[-1, -1, -1], [1, 1, 1]]}}}]}
    said = lean.shape_changes(json.dumps([frame(0, 1.1), frame(45, 1.8), frame(90, 2.6)]), fps=30)
    assert len(said) == 1 and said[0].startswith("ring: its own size 2.2 x 2.2 x 0.2 at 0.0 s, 5.2 x 5.2 x 0.2 at 3.0 s"), said
    assert "withScale" in said[0]
    assert lean.shape_changes(json.dumps([frame(0, 1.1), frame(90, 1.1)])) == [] and lean.shape_changes("REFUSED") == []


def test_look_draws_the_starter_film_without_its_grain():
    # G: "mask blind: element Grain ... frontmost on 100% of the frame" on every tile of a film keeping the starter's finish
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        for kind in ("launch", "app"):
            class A: pass
            a = A(); a.name = str(Path(tmp) / kind); a.kind = kind
            d = lean.cmd_new(a)
            assert "finish={false}" in (d / "main.tsx").read_text(encoding="utf-8") and "finish ?" in (d / "film.tsx").read_text(encoding="utf-8")
            asked = []

            class Done:
                returncode, stdout, stderr = 0, "LOOK", ""
            with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                    patch.object(lean, "streamed", lambda args, **k: asked.append([str(x) for x in args]) or Done()):
                lean.cmd_look(Args(film=str(d), at="1", out=None))
                lean.cmd_look(Args(film=str(d), at="1", out=None, composition="film"))
            first, second = asked
            assert first[first.index("--composition") + 1] == "film-look", first
            assert second[second.index("--composition") + 1] == "film", "a composition the maker names is the one drawn"


def test_export_says_how_long_it_waited_and_makes_the_hand_in():
    # G: "picture rendered once in 557.1 s" on cut 2 against 87 s on cut 1, with nothing to tell waiting from rendering;
    # and the hand-in (a share copy, a 4 fps sheet) made by hand
    from unittest.mock import patch
    assert lean.split_wait(557.1, "OK 87.0s APPLIED  300 frames rendered to x.mp4") == (557.1 - 87.0, 87.0)
    assert lean.split_wait(10.0, "something else") is None
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "moon.mp4"
        ran = []
        with patch.object(lean, "run", lambda args, **k: ran.append([str(x) for x in args])):
            share, _ = lean.hand_in(dest)
    assert share.name == "moon-share.mp4"
    enc, sheet = ran
    assert enc[3].endswith("heavy.py") and "ffmpeg" in enc and "-crf" in enc and enc[-1].endswith("moon-share.mp4"), "the encode takes its turn"
    assert sheet[3].endswith("sheet.py") and sheet[sheet.index("--fps") + 1] == "4" and sheet[sheet.index("--width") + 1] == "480"


def test_a_sheet_nobody_can_open_is_refused_before_any_work():
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        film = made_film(Path(tmp) / "f.mp4")
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "sheet.py"), str(film), "-o", str(Path(tmp) / "s.jpg"), "--fps", "4", "--cols", "8",
                            "--width", "3200"], capture_output=True, text=True, encoding="utf-8")
        assert p.returncode != 0 and "--width is the width of one tile" in p.stderr and not list(Path(tmp).glob("s*.jpg")), p.stderr
        ok = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "sheet.py"), str(film), "-o", str(Path(tmp) / "t.jpg"), "--fps", "4", "--cols", "4",
                             "--rows", "4", "--width", "480"], capture_output=True, text=True, encoding="utf-8")
        assert ok.returncode == 0 and list(Path(tmp).glob("t*.jpg")), ok.stderr


def test_every_kind_is_a_page_film_that_draws_as_it_comes():
    # Round: `--kind type` wanted a page film of type and got a lit 3D scene whose textures and models were not shipped.
    # The four 3D kinds are gone: a kind that cannot draw as it comes is refused by name, with the kinds that can.
    assert lean.KINDS == ("explainer", "launch", "vertical", "app") and all("page film" in lean.kind_line(k) for k in lean.KINDS)
    assert not (lean.LIBRARY / "kinds").exists(), "library/kinds held the 3D starters"
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        for kind in ("type", "place", "interface", "music"):
            p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "new", "x", "--kind", kind], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            assert p.returncode != 0 and "invalid choice" in p.stderr and "explainer" in p.stderr and not (Path(tmp) / "x").exists(), (kind, p.stderr)


def test_the_starter_palette_does_not_clip():
    # H and pass 9: a look at the untouched explainer said "12.0% of the pixels clip to white": the card's accents had a
    # full red channel. A colour with a channel at 255 is what raea counts as clipped, so the palette stays under it.
    import re
    base = (lean.STARTER / "base.tsx").read_text(encoding="utf-8")
    palette = base[base.index("export const C"):base.index("};", base.index("export const C"))]
    full = [c for c in re.findall(r"#([0-9a-fA-F]{6})", palette) if "ff" in [c[i:i + 2].lower() for i in (0, 2, 4)]]
    assert not full, f"palette colours with a channel at 255: {full}"
    film = (lean.STARTER / "film.tsx").read_text(encoding="utf-8")
    assert "left: 0, width: W," not in film, "the starter's number box runs the frame's width and its drift pushes it past the frame"


def test_a_layer_over_every_moment_is_an_overlay_said_once():
    # H and Round: "mask blind" on every tile, for a grain in an entry of its own and a full-frame soft patch
    import look
    total = 100
    grain = {0: [3] * 100, 30: [3] * 99 + [1]}
    assert look.overlay(grain, [0, 30], total) == 3
    assert look.overlay({0: [3] * 100, 30: [1] * 50 + [3] * 50}, [0, 30], total) is None, "covering one moment only is not an overlay"
    assert look.overlay({0: [0] * 100}, [0], total) is None, "nothing stamped is not an overlay"


def test_look_names_words_under_the_floor():
    # H: four tiles said "ok" while holding small labels. C2: the pages say 30 px on screen, the starter 3.6% (38.9 px)
    # and look warned under 38.9 px of the text's own size: one floor now, 30 px at 1080, and the line says what it measures
    import look
    man = {"height": 1080, "frames": [{"frame": 0, "text": [{"text": "push", "size": 28.0, "loc": "rig.tsx:9:3"},
                                                             {"text": "A line", "size": 34.0, "loc": "kit/base.tsx:54:5"}]}]}
    said = look.small_words(man)
    assert said and "push" in said and "28 px (rig.tsx:9:3)" in said and "A line" not in said, said
    assert "under 30 px (30 px at 1080)" in said and "before any camera or parent scale" in said and "misses words a camera shrinks" in said \
        and "names words a camera enlarges" in said, said
    assert look.small_words({"height": 1080, "frames": [{"frame": 0, "text": [{"text": "big", "size": 60.0}]}]}) is None
    tall = look.small_words({"height": 2160, "frames": [{"frame": 0, "text": [{"text": "x", "size": 50.0, "loc": "a"}, {"text": "y", "size": 61.0, "loc": "b"}]}]})
    assert tall and "under 60 px" in tall and "\u201cx\u201d" in tall and "\u201cy\u201d" not in tall, f"scaled with the frame's height: {tall}"


def test_a_bare_page_starter_is_the_frame_and_the_finish():
    # Round: for a film that is a diagram the maker deleted all of the page starter but the frame, finish and grain, twice
    with tempfile.TemporaryDirectory() as tmp:
        class A: pass
        a = A(); a.name = str(Path(tmp) / "b"); a.kind = "launch"; a.bare = True
        d = lean.cmd_new(a)
        film = (d / "film.tsx").read_text(encoding="utf-8")
        assert "finish = true" in film and "Grain" in film and "Drift" not in film and "Ground" not in film
        assert all(lean.resolves(d / "film.tsx", spec) for spec in lean.IMPORT.findall(film))


def test_each_export_is_a_numbered_cut_and_a_failed_one_deletes_no_finished_cut():
    # Round's cut 3 threw at frame 423 of 513 after a check of one frame, and cut 2's files under the same names were
    # filed as cut 3; the fix then deleted cut 2 on any failure, though the cut ledger and the second reading need it
    import io
    from contextlib import redirect_stderr, redirect_stdout
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        out = Path(tmp) / "out" / "film"
        made = iter(range(1, 100))

        def mux(pic, wav, dest, **k):
            Path(dest).write_bytes(f"film {next(made)}".encode())

        def hand_in(dest):
            share, sheet = dest.with_name(dest.stem + "-share.mp4"), dest.with_name(dest.stem + "-sheet.jpg")
            share.write_bytes(b"share " + dest.read_bytes())
            sheet.write_bytes(b"sheet " + dest.read_bytes())
            return share, [sheet]
        fails = lambda *a, **k: (False, 1.0, "FAILED TypeError at frame 423")
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "mux", mux), patch.object(lean, "hand_in", hand_in), patch.object(lean, "scanned", lambda *a: None), \
                patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                lean.cmd_export(Args(film=str(d)))
            assert f"this is cut 1, kept as {out / 'cuts' / 'film-cut1.mp4'}" in buf.getvalue(), buf.getvalue()
            lean.cmd_export(Args(film=str(d)))
            cuts = out / "cuts"
            assert sorted(f.name for f in cuts.iterdir()) == ["film-cut1-share.mp4", "film-cut1-sheet.jpg", "film-cut1.mp4",
                                                                "film-cut2-share.mp4", "film-cut2-sheet.jpg", "film-cut2.mp4"], list(cuts.iterdir())
            assert (cuts / "film-cut1.mp4").read_bytes() == b"film 1" and (cuts / "film-cut2.mp4").read_bytes() == b"film 2", "each cut is its own"
            latest = [out / "film.mp4", out / "film-share.mp4", out / "film-sheet.jpg"]
            assert [f.read_bytes() for f in latest] == [b"film 2", b"share film 2", b"sheet film 2"], "NAME.mp4 and its hand-in are the latest cut"
            # a render that fails: nothing finished goes, no cut 3 is made, and it says what NAME.mp4 still is
            err = io.StringIO()
            with patch.object(lean, "raea_render", fails), redirect_stderr(err):
                try:
                    lean.cmd_export(Args(film=str(d), again=True))
                    raise AssertionError("a failed render must not return as if it worked")
                except SystemExit as e:
                    assert "render failed" in str(e)
            assert "no cut 3 was made; film.mp4 is still cut 2" in err.getvalue(), err.getvalue()
            # a failure after the cut's film was written (its share copy fails): what it began of cut 3 goes, nothing else
            with patch.object(lean, "hand_in", lambda dest: (_ for _ in ()).throw(RuntimeError("encoder gone"))), redirect_stderr(io.StringIO()):
                try:
                    lean.cmd_export(Args(film=str(d)))
                    raise AssertionError("a failed hand-in must not return as if it worked")
                except RuntimeError:
                    pass
            assert not list(cuts.glob("film-cut3*")), list(cuts.iterdir())
            assert [f.read_bytes() for f in latest] == [b"film 2", b"share film 2", b"sheet film 2"] and (cuts / "film-cut1.mp4").read_bytes() == b"film 1"
            lean.cmd_export(Args(film=str(d)))
            assert (cuts / "film-cut3.mp4").is_file() and (out / "film.mp4").read_bytes() == (cuts / "film-cut3.mp4").read_bytes(), "the next that works is cut 3"
            # -o names the latest; its cuts are kept the same way, under its own name
            mine = Path(tmp) / "elsewhere" / "mine.mp4"
            lean.cmd_export(Args(film=str(d), o=str(mine)))
            assert mine.is_file() and (cuts / "mine-cut1.mp4").read_bytes() == mine.read_bytes()


def test_export_checks_the_composition_it_draws_not_the_score():
    # a 2.5 s composition exported beside Plus One's 38.4 s score was checked out to frame 2303 and refused
    from unittest.mock import patch
    assert lean.spread({"duration": 17.1, "fps": 30})[0] == 0 and lean.spread({"duration": 17.1, "fps": 30})[-1] == 512
    assert len(lean.spread({"duration": 17.1, "fps": 30})) == 12 and lean.spread(None, total=150)[-1] == 149
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        (d / "score.json").write_text(json.dumps({"fps": 60, "width": 64, "height": 36, "duration": 38.4, "beats": [], "sounds": []}), encoding="utf-8")
        asked, counted = [], []

        def frames_of(entry, comp):
            counted.append(comp)
            return 150
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "comp_frames", frames_of), \
                patch.object(lean, "must_preflight", lambda *a, **k: asked.append(a)), patch.object(lean, "mux", lambda *a, **k: None), \
                patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "scanned", lambda *a: None), \
                patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")):
            lean.cmd_export(Args(film=str(d)))
            lean.cmd_export(Args(entry=str(d / "main.tsx"), composition="short"))
        assert counted == ["short"], f"the score's own composition is timed by the score, another by raea: {counted}"
        assert asked[0][1] == "film" and asked[0][3][-1] == 2303, asked[0]
        assert asked[1][1] == "short" and asked[1][3] == lean.spread(None, total=150) and asked[1][3][-1] == 149, asked[1]


def test_look_and_export_refuse_before_the_queue_when_a_drive_is_nearly_full():
    # 05:51: drive C at 0 bytes free, and a look learnt it from raea after its checks had passed
    from types import SimpleNamespace
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "out" / "old-film").mkdir(parents=True)
        (Path(tmp) / "out" / "old-film" / "old.mp4").write_bytes(b"x" * 1000)
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean.shutil, "disk_usage", lambda p: SimpleNamespace(free=0.2e9)):
            try:
                lean.room(Path(tmp) / "film" / "main.tsx", 1.3, "export")
                raise AssertionError("a nearly full drive is refused before the queue")
            except SystemExit as e:
                said = str(e)
        assert "0.2 GB free" in said and "needs about 1.3 GB" in said and "old-film" in said and "keeps no frame folders" in said, said
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean.shutil, "disk_usage", lambda p: SimpleNamespace(free=50e9)):
            lean.room(Path(tmp) / "film" / "main.tsx", 1.3, "export")



def test_a_full_disk_mounted_elsewhere_is_seen():
    # a review's finding: disks were told apart by a path's anchor, which is "/" for every folder on macOS and Linux, so
    # only the first place's free space was kept and a full volume mounted elsewhere was never looked at
    import os
    from types import SimpleNamespace
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "elsewhere" / "out"
        out.mkdir(parents=True)
        real, same = os.stat, lambda p: os.path.normcase(os.path.abspath(str(p))) == os.path.normcase(os.path.abspath(str(out)))

        def stat(path, *a, **k):                              # the out folder is on a disk of its own, with no room
            r = real(path, *a, **k)
            return SimpleNamespace(st_dev=9001, st_mode=r.st_mode) if same(path) else r
        free = lambda p: SimpleNamespace(free=0.1e9 if same(p) else 80e9)
        with patch.object(lean, "OUTROOT", out), patch.object(lean.os, "stat", stat), patch.object(lean.shutil, "disk_usage", free):
            try:
                lean.room(Path(tmp) / "film" / "main.tsx", 1.3, "export")
                raise AssertionError("the full disk the outputs go to is refused, whatever the film's own disk has")
            except SystemExit as e:
                assert "0.1 GB free" in str(e), e


def test_a_source_whose_name_starts_with_an_underscore_makes_the_picture_stale_and_an_export_is_an_mp4():
    # two of a review's findings: every file starting "_" was left out of the freshness check, though only the two stubs
    # this tool writes are not sources; and -o film.mov wrote film.mp4 and then scanned whatever film.mov was there
    import os
    import time
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        base = lean.source_files(d)
        later = time.time() + 600
        for name in lean.STUBS:
            (d / name).write_text("// a stub", encoding="utf-8")
            os.utime(d / name, (later, later))
        (d / "out").mkdir()
        (d / "out" / "ignored.tsx").write_text("// in out", encoding="utf-8")
        assert lean.source_files(d) == base, "the tool's own stubs and out/ are not sources"
        (d / "_scene.tsx").write_text("// imported by main.tsx", encoding="utf-8")
        os.utime(d / "_scene.tsx", (later, later))
        after = lean.source_files(d)
        assert "_scene.tsx" in after and after["_scene.tsx"][0] >= later - 1, "an edited _scene.tsx is recorded in source_files"
        from unittest.mock import patch
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"):
            try:
                lean.export_paths(Args(film=str(d), o=str(Path(tmp) / "final.mov")))
                raise AssertionError("an export under another kind of name is refused before any work")
            except SystemExit as e:
                assert ".mp4" in str(e) and "final.mov" in str(e), e
            assert lean.export_paths(Args(film=str(d), o=str(Path(tmp) / "final.MP4")))[-1].name == "final.MP4"


def test_a_preflight_check_that_times_out_has_not_passed():
    # a review's finding: a check killed at its time limit was never waited for, its return code stayed None, None read
    # as success, and the render was let into the queue
    import subprocess
    from unittest.mock import patch

    class Hung:
        returncode = None
        calls = 0

        def communicate(self, timeout=None):
            Hung.calls += 1
            raise subprocess.TimeoutExpired("raea", timeout)

        def kill(self):
            pass
    import raea_run
    with tempfile.TemporaryDirectory() as tmp:
        entry = Path(tmp) / "main.tsx"
        entry.write_text("// nothing", encoding="utf-8")
        with patch.object(raea_run, "checked_binary", lambda say=False: "raea"), patch.object(raea_run, "raea_env", lambda: {}), \
                patch.object(lean.subprocess, "Popen", lambda *a, **k: Hung()), patch.dict(lean.os.environ, {"VD_NO_PREFLIGHT": "0"}):
            ok, _, why = lean.preflight(entry, "film", 0)
        assert not ok and why.count("timed out") == 2 and "checked nothing" in why, (ok, why)


def test_vd_profile_reads_the_session_that_made_the_film():
    # the first profile printed hundreds of runs of another session, newer and naming the folder in a brief
    import os
    import time
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        home, film = Path(tmp), Path(tmp) / "films" / "quiet"
        proj = home / ".claude" / "projects" / "x"
        proj.mkdir(parents=True)
        maker, director = proj / "maker.jsonl", proj / "director.jsonl"
        maker.write_text(json.dumps({"cwd": str(film.parent), "message": {"content": [{"type": "tool_use", "input": {"command": "python vd.py new quiet --kind explainer"}}]}}) + "\n", encoding="utf-8")
        director.write_text(json.dumps({"message": {"content": f"make a film in {film.as_posix()}"}}) + "\n", encoding="utf-8")
        os.utime(maker, (1e9, time_now() - 100)); os.utime(director, (1e9, time_now()))
        # A5: a newer session run in a folder named "New folder", every tool call a vd command, is read quickly: the
        # film's folder was resolved again for each of its lines (7.6 s over 30,000)
        decoy = proj / "decoy.jsonl"
        tool = {"cwd": str(Path(tmp) / "New folder"), "message": {"content": [{"type": "tool_use", "input": {"command": "python vd.py look films/x"}}]}}
        decoy.write_text((json.dumps(tool) + "\n") * 3000, encoding="utf-8")
        os.utime(decoy, (1e9, time_now()))
        with patch.object(Path, "home", lambda: home):
            t0 = time.perf_counter()
            assert lean.newest_transcript(film) == maker
            took = time.perf_counter() - t0
            assert took < 0.25, f"3,000 tool calls of another session took {took:.2f} s"
            decoy.unlink()
            maker.unlink()
            assert lean.newest_transcript(film) == director, "with no session that made it, the newest that names it"


def test_the_maker_is_found_by_the_folder_it_made_not_its_name():
    # a review's finding: `vd new C:/films/quiet` was missed, and another folder's `new quiet` accepted
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "films" / "quiet"
        line = lambda cmd, cwd=None: json.dumps({"cwd": cwd or tmp, "message": {"content": [{"type": "tool_use", "input": {"command": cmd}}]}})
        assert lean.made_here(line(f'python vd.py new "{film.as_posix()}" --kind explainer'), film), "absolute"
        assert lean.made_here(line("python vd.py new films/quiet --kind explainer"), film), "relative to the session's folder"
        assert lean.made_here(line(f'cd "{(Path(tmp) / "films").as_posix()}" && $VD new quiet --kind launch'), film), "after a cd"
        assert not lean.made_here(line("python vd.py new quiet --kind explainer", cwd=str(Path(tmp) / "elsewhere")), film), "another folder's quiet"
        # a review's finding: every `cd` before the command counts, in order, from the session's folder
        deep = Path(tmp) / "films" / "shots" / "quiet"
        assert lean.made_here(line("cd films && cd shots && $VD new quiet"), deep), "two folder changes in a row"
        assert not lean.made_here(line("cd films && cd shots && $VD new quiet"), Path(tmp) / "shots" / "quiet"), "not the last one alone"
        assert lean.made_here(line(f'cd elsewhere && cd "{(Path(tmp) / "films").as_posix()}" && $VD new quiet'), film), "an absolute one starts again"
        import os
        if os.name == "nt":                                    # Git Bash writes the drive as /c/
            films = (Path(tmp).resolve() / "films").as_posix()
            assert lean.made_here(line(f'cd "/{films[0].lower()}{films[2:]}" && $VD new quiet'), film), "a Git Bash path"


def time_now():
    import time
    return time.time()



def test_a_render_that_fails_part_way_leaves_no_picture():
    # a review's finding: a render that failed after writing bytes left a truncated picture that the next export took as current
    from unittest.mock import patch

    def half(dd, entry, out, *flags, env=None):
        Path(out).write_bytes(b"half a film")
        return False, 1.0, "FAILED There is not enough space on the disk"
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "raea_render", half):
            try:
                lean.cmd_export(Args(film=str(d)))
            except SystemExit:
                pass
        left = [f.name for f in (Path(tmp) / "out" / "film").glob("*.mp4")]
        assert left == [], f"nothing half-rendered is left to be taken as the picture: {left}"



def test_a_re_export_of_a_current_picture_still_checks_the_room():
    # a review's finding: the free-space check ran only when the picture needed drawing, though every export writes the film and
    # its share copy
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        checked = []
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), \
                patch.object(lean, "must_preflight", lambda *a, **k: None), patch.object(lean, "mux", lambda *a, **k: None), \
                patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "room", lambda e, need, what, out=None: checked.append(need)), \
                patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")):
            lean.cmd_export(Args(film=str(d)))
            lean.cmd_export(Args(film=str(d)))           # the picture is current now: not drawn again
        assert len([n for n, f in rendered if ".picture" in n]) == 1 and len(checked) == 2, (rendered, checked)
        assert checked[1] < checked[0], f"less room asked when nothing is drawn: {checked}"



def test_a_picture_is_current_only_while_its_sources_are_what_it_was_drawn_from():
    # broke: freshness compared the picture's mtime with the newest source left, so deleting a scene the film imported
    # kept the old picture; and a vd render splice made the whole picture look new though the frames outside the
    # stretch were drawn from older sources
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        (d / "scene.tsx").write_text("// a scene main.tsx imports", encoding="utf-8")
        out = Path(tmp) / "out" / "film"

        def splice(args, **k):                          # heavy.py's ffmpeg splice, standing in: it writes the joined picture
            (out / "picture.splice.mp4").write_bytes(b"spliced")
        pictures = lambda: len([n for n, f in rendered if ".picture" in n])
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render),                 patch.object(lean, "must_preflight", lambda *a, **k: None), patch.object(lean, "mux", lambda *a, **k: None),                 patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "scanned", lambda film, to: to),                 patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")),                 patch.object(lean, "run", splice), patch.object(lean, "join_report", lambda *a, **k: ""):
            lean.cmd_export(Args(film=str(d)))
            lean.cmd_export(Args(film=str(d)))
            assert pictures() == 1, "an unchanged film's picture is reused"
            (d / "scene.tsx").unlink()
            lean.cmd_export(Args(film=str(d)))
            assert pictures() == 2, "a deleted source makes the picture stale"
            lean.cmd_render(Args(film=str(d), from_="0", to="0.5"))
            lean.cmd_export(Args(film=str(d)))
            assert pictures() == 3, "after a splice the next export draws the whole picture again"
            lean.cmd_export(Args(film=str(d)))
            assert pictures() == 3, "and after that it is current again"

def test_export_copies_a_films_own_sound_on_and_scans_what_it_made():
    # a worked film masters its own sound (media/sound.wav, -15 LUFS) and its score lists no sounds: built from the
    # score, the export would have carried silence
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        (d / "media").mkdir()
        (d / "media" / "sound.wav").write_bytes(b"w")
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
        score["sound_file"] = "media/sound.wav"
        (d / "score.json").write_text(json.dumps(score), encoding="utf-8")
        muxed, scans = [], []

        def no_build(*a):
            raise AssertionError("the film's own sound is not built again from the score")
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "mux", lambda pic, wav, dest, **k: muxed.append(Path(wav))), patch.object(lean, "hand_in", lambda dest: (dest, [])), \
                patch.object(lean, "build_sound", no_build), patch.object(lean, "scanned", lambda film, to: scans.append((Path(film), Path(to)))):
            dest = lean._export(Args(film=str(d)))
        assert muxed == [d / "media" / "sound.wav"], muxed
        assert scans == [(dest, Path(tmp) / "out" / "film" / "scan.txt")], scans
    # and a scan that cannot run never fails the export: one line, and the export stands
    with tempfile.TemporaryDirectory() as tmp:
        assert lean.scanned(Path(tmp) / "nothing.mp4", Path(tmp) / "scan.txt") is None


def test_a_film_that_names_a_shutter_is_exported_with_its_blur():
    # two reviews' finding: Linden was accepted with a camera's blur, and `vd export` of its copy made a sharper film
    # than the one accepted, which the steps then handed to readers as the accepted one
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
        (d / "score.json").write_text(json.dumps({**score, "shutter": {"composition": "film-sub", "sub": 4, "open": 3}}), encoding="utf-8")
        blurred, preflights = [], []

        def averaged(pictures, out, sub, opened, fps):
            blurred.append((Path(pictures).name, sub, opened, fps))
            Path(out).write_bytes(b"blurred")
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), \
                patch.object(lean, "must_preflight", lambda entry, comp, f0, frames, fps: preflights.append((comp, f0, frames, fps))), \
                patch.object(lean, "mux", lambda *a, **k: None), patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "scanned", lambda film, to: to), \
                patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")), patch.object(lean, "averaged", averaged):
            assert lean.cmd_export(Args(film=str(d))) == 0
            total = int(round(score["duration"] * score["fps"]))
            assert preflights == [("film-sub", 0, lean.spread(score, total=total * 4), score["fps"] * 4)], (
                f"shutter export preflights the sub-frame composition at sub * total and sub * fps: {preflights}")
            out = Path(tmp) / "out" / "film"
            pics = list(out.glob("*.picture.mp4"))
            assert len(rendered) == 1 and "film-sub" in rendered[0][1], f"the engine drew the many-pictures composition, once: {rendered}"
            assert len(blurred) == 1 and blurred[0][1:] == (4, 3, 30), f"3 of every 4 averaged, at the film's own rate: {blurred}"
            assert len(pics) == 1 and pics[0].read_bytes() == b"blurred" and not list(out.glob("*.part.mp4")), "the kept picture is the blurred one, and nothing is left beside it"
            (d / "score.json").write_text(json.dumps({**score, "shutter": {"composition": "film-sub-missing", "sub": 4, "open": 3}}), encoding="utf-8")
            preflights.clear()
            assert lean.cmd_export(Args(film=str(d), again=True)) == 0
            assert preflights and preflights[0][0] == "film-sub-missing", preflights
            try:
                lean.cmd_render(Args(film=str(d), from_="0", to="0.5"))
                raise AssertionError("a stretch drawn alone would be sharp inside a blurred picture")
            except SystemExit as e:
                assert "shutter" in str(e) and "vd export" in str(e), e
        (d / "score.json").write_text(json.dumps({**score, "shutter": {"composition": "film-sub", "sub": 4, "open": 5}}), encoding="utf-8")
        try:
            lean.shutter_of(json.loads((d / "score.json").read_text(encoding="utf-8")), "film")
            raise AssertionError("a shutter open for more pictures than there are is refused")
        except SystemExit as e:
            assert "K from 1 to N" in str(e), e
        assert lean.shutter_of({"shutter": {"composition": "film-sub", "sub": 4, "open": 3}}, "other") is None, "only the score's own composition is blurred"


def test_two_film_folders_of_one_name_never_share_a_picture():
    # a review's finding: ~/.vd/out/NAME goes by the folder's name alone, and an export takes a kept picture for
    # current when it is newer than the sources. A second folder called NAME, with older files, got the first one's picture
    import contextlib
    import io
    import os
    import time
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        first, _, _ = fake_film(tmp)
        (Path(tmp) / "elsewhere").mkdir()
        second, _, _ = fake_film(Path(tmp) / "elsewhere")
        drew = []

        def render(dd, entry, out, *flags, env=None):
            drew.append(Path(dd).parent.name)
            Path(out).write_bytes(b"x")
            return True, 0.1, "OK"
        said = io.StringIO()
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "mux", lambda *a, **k: None), patch.object(lean, "hand_in", lambda dest: (dest, [])), patch.object(lean, "scanned", lambda film, to: to), \
                patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")), contextlib.redirect_stderr(said):
            lean.cmd_export(Args(film=str(first)))
            lean.cmd_export(Args(film=str(first)))                 # its own picture is current: not drawn again, nothing said
            assert drew == [Path(tmp).name] and "another film folder" not in said.getvalue(), (drew, said.getvalue())
            hour_ago = time.time() - 3600
            for f in second.rglob("*"):
                os.utime(f, (hour_ago, hour_ago))                  # older than the first film's picture
            lean.cmd_export(Args(film=str(second)))
        assert drew == [Path(tmp).name, "elsewhere"], f"the second folder's own picture is drawn: {drew}"
        assert "another film folder called film" in said.getvalue() and str(first.resolve()) in said.getvalue(), said.getvalue()
        assert (Path(tmp) / "out" / "film" / lean.OWNER).read_text(encoding="utf-8").strip() == str(second.resolve())



def test_a_folder_taking_over_a_name_does_not_inherit_the_other_films_latest_cut_or_scan():
    # broke: a second folder called `shared` took over ~/.vd/out/shared and its first failed export said "shared.mp4 is
    # still cut 1": the other film's cut, its scan.txt and its evolve key were read as this folder's
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "one" / "shared", Path(tmp) / "two" / "shared"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"):
            o = lean.outdir(a)
            (o / "cuts").mkdir()
            for name, data in (("cuts/shared-cut1.mp4", b"cut1"), ("shared.mp4", b"cut1"), ("shared-share.mp4", b"s"),
                               ("shared-sheet_000.jpg", b"j"), ("shared-sheet.jpg", b"one sheet"), ("scan.txt", b"SCAN of one"), ("sound.txt", b"sound of one"),
                               ("bridge/cues.json", b"{}"), ("evolve-1-KEY.txt", b"key"), ("pack-1-KEY.txt", b"pack key")):
                (o / name).parent.mkdir(parents=True, exist_ok=True)
                (o / name).write_bytes(data)
            assert lean.outdir(b) == o
            left = sorted(p.relative_to(o).as_posix() for p in o.rglob("*") if p.is_file() and p.name not in (lean.OWNER, "exporting.lock"))
            # the scan and sound notes are readings and go; the rest of the other film's work is moved aside, not deleted
            aside = ["bridge/cues.json", "cuts/shared-cut1.mp4", "evolve-1-KEY.txt", "pack-1-KEY.txt", "shared-share.mp4", "shared-sheet.jpg", "shared-sheet_000.jpg", "shared.mp4"]
            assert left == [f"earlier-folder/1/{x}" for x in aside], left
            # a third folder taking the name over keeps both earlier keys (broke: the second replaced the first's)
            (o / "evolve-1-KEY.txt").write_bytes(b"key two")
            (o / "pack-1-KEY.txt").write_bytes(b"pack two")
            c = Path(tmp) / "three" / "shared"
            c.mkdir(parents=True)
            lean.outdir(c)
            assert (o / "earlier-folder" / "1" / "evolve-1-KEY.txt").read_bytes() == b"key"
            assert (o / "earlier-folder" / "2" / "evolve-1-KEY.txt").read_bytes() == b"key two"
            assert (o / "earlier-folder" / "1" / "pack-1-KEY.txt").read_bytes() == b"pack key"
            assert (o / "earlier-folder" / "2" / "pack-1-KEY.txt").read_bytes() == b"pack two"

def test_the_scans_count_line_says_when_the_sound_is_missing_or_off_and_an_unscanned_export_is_not_a_clean_exit():
    # a review's finding: a film with no sound, or far off the level, ended "0 to fix and 0 to check"; and an export
    # whose scan could not run still exited 0
    import contextlib
    import io
    import subprocess
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        silent, quiet = Path(tmp) / "silent.mp4", Path(tmp) / "quiet.mp4"
        picture = ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *picture, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", *picture, "-f", "lavfi", "-i", "sine=frequency=440:duration=2,volume=-40dB", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(quiet)], check=True)
        for film, words in ((silent, "the file has no sound"), (quiet, "the level is off")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert lean.scanned(film, Path(tmp) / "scan.txt") is not None
            count = next(l for l in out.getvalue().splitlines() if l.startswith("scan: "))
            assert words in count, count
        d, rendered, render = fake_film(tmp)
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "mux", lambda pic, wav, dest, **k: Path(dest).write_bytes(b"not a film")), patch.object(lean, "hand_in", lambda dest: (dest, [])), \
                patch.object(lean, "build_sound", lambda d, s: Path(lean.outdir(d) / "sound.wav").write_bytes(b"w")), contextlib.redirect_stdout(io.StringIO()) as said:
            assert lean.cmd_export(Args(film=str(d))) == 3, "made, kept, and not scanned: its own exit code"
        assert "NOT scanned" in said.getvalue() and (Path(tmp) / "out" / "film" / "film.mp4").exists(), said.getvalue()[-400:]


def tone_wav(path, hz, seconds, level=0.3, start=0.0, total=None):
    t = np.arange(int(seconds * lean.SR)) / lean.SR
    x = np.zeros((int((total or seconds) * lean.SR), 2), np.float32)
    a = int(start * lean.SR)
    x[a:a + len(t)] = (level * np.sin(2 * np.pi * hz * t))[:, None]
    lean.write_wav(path, x)
    return path


def band_db(x, hz, a, b):
    seg = x[int(a * lean.SR):int(b * lean.SR)].mean(1)
    f = np.fft.rfftfreq(len(seg), 1 / lean.SR)
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    return 20 * np.log10(X[(f > hz - 20) & (f < hz + 20)].max() + 1e-9)


def test_a_voice_on_a_worked_film_is_mixed_over_its_own_sound():
    # T3: vd new --like sets sound_file, and vd sound and export then carried that mix as it was: a voice named in
    # score.json, as the pages tell a maker to add one, was dropped without a word
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        (d / "media").mkdir()
        # the film's own mix: a steady tone (not 1 kHz: a tone whose period is exactly 192 bytes of wav reads to ffmpeg as M2TS)
        tone_wav(d / "media" / "sound.wav", 1003, 4.0, 0.2)
        tone_wav(d / "media" / "take.wav", 301, 1.0, 0.4, start=1.5, total=4.0)        # the voice: 301 Hz from 1.5 to 2.5 s
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
        score.update(duration=4.0, sound_file="media/sound.wav", voice="media/take.wav", words=[{"w": "hello", "start": 1.5, "end": 2.5}])
        (d / "score.json").write_text(json.dumps(score), encoding="utf-8")
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"):
            report = lean.build_sound(d, score)
            x = lean.read_audio(Path(tmp) / "out" / "film" / "sound.wav")
        assert band_db(x, 301, 1.7, 2.3) - band_db(x, 301, 0.2, 1.0) > 40, "the voice is in the mix where it is said"
        ducked = band_db(x, 1003, 0.2, 1.0) - band_db(x, 1003, 1.8, 2.2)
        # 8 dB under the words before levelling; loudnorm may hold a short loud stretch down further (13 dB here)
        assert ducked > 6 and band_db(x, 1003, 0.2, 1.0) > band_db(x, 301, 0.2, 1.0) + 40, f"the film's own mix is under it, ducked while the words are said: {ducked:.1f} dB"
        assert "voice media/take.wav over this film's own mix media/sound.wav, the mix ducked 8 dB under the words" in report, report
        assert report.strip().splitlines()[-1].startswith("sound passes"), report
        # vd sound and vd export take that route; without a voice the own mix is carried as it is
        built, muxed = [], []
        build = lambda dd, ss: built.append(1) or lean.write_wav(Path(lean.outdir(dd)) / "sound.wav", np.zeros((10, 2), np.float32))
        with patch.object(lean, "OUTROOT", Path(tmp) / "out2"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None), \
                patch.object(lean, "build_sound", build), patch.object(lean, "check_sound", lambda *a, **k: "checked"), patch.object(lean, "scanned", lambda *a: None), \
                patch.object(lean, "mux", lambda pic, wav, dest, **k: muxed.append(Path(wav).relative_to(tmp).as_posix())), patch.object(lean, "hand_in", lambda dest: (dest, [])):
            lean.cmd_sound(Args(film=str(d)))
            lean.cmd_export(Args(film=str(d)))
            assert built == [1] and muxed == ["out2/film/sound.wav"], f"built by vd sound, current for the export: {(built, muxed)}"
            del score["voice"]
            (d / "score.json").write_text(json.dumps(score), encoding="utf-8")
            lean.cmd_export(Args(film=str(d)))
            assert built == [1] and muxed[-1] == "film/media/sound.wav", (built, muxed)


def test_an_encode_that_lifts_the_peak_is_trimmed_within_the_level():
    # C1: Plus One's sound, -3.1 dBTP as a wav, came out of the export's AAC encode at -0.6; 0.5 dB lower it still did
    from unittest.mock import patch
    gains = []
    for measured, want in (([(-15.0, -0.6), (-15.5, -0.6), (-15.6, -2.2)], [-0.25, -0.5]), ([(-15.0, -1.6)], [])):
        seq = iter(measured)
        gains.clear()
        with patch.object(lean, "loudness", lambda f: next(seq)), patch.object(lean, "mux", lambda pic, wav, dest, **k: gains.append(k.get("gain_db", 0.0))):
            said = lean.held_under_peak("pic.mp4", "s.wav", Path("part.mp4"))
        assert gains == want, (gains, want)
        assert (said is None) == (not want) and (not want or "0.5 dB lower in this file (-15.6 LUFS, -2.2 dBTP)" in said), said
    # nothing within the level helps: the file is encoded as it was, and the line says so (the scan then names the fault)
    seq = iter([(-15.0, -0.6)] + [(-15.5, -0.9)] * 4)
    with patch.object(lean, "loudness", lambda f: next(seq)), patch.object(lean, "mux", lambda pic, wav, dest, **k: gains.append(k.get("gain_db", 0.0))):
        gains.clear()
        said = lean.held_under_peak("pic.mp4", "s.wav", Path("part.mp4"))
    assert gains == [-0.25, -0.5, -0.75, -1.0, 0.0] and "more headroom" in said, (gains, said)


def test_export_meters_the_encoded_mix_once_without_decoding_picture():
    import contextlib
    import io
    import subprocess
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        (d / "media").mkdir()
        tone_wav(d / "media" / "sound.wav", 440, 1.0, 0.15)
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
        score.update(duration=1.0, fps=30, sound_file="media/sound.wav")
        (d / "score.json").write_text(json.dumps(score), encoding="utf-8")

        def draw_pic(dd, entry, out, *flags, env=None):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:r=30:d=1",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
            return True, 0.1, "OK 0.1s"

        real_run, real_loudness = lean.run, lean.loudness
        cmds, calls = [], []

        def spy_run(args, **kw):
            if any("ebur128" in str(x) for x in args):
                cmds.append([str(x) for x in args])
            return real_run(args, **kw)

        def spy_loudness(path):
            calls.append(Path(path).name)
            return real_loudness(path)

        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", draw_pic), \
                patch.object(lean, "must_preflight", lambda *a, **k: None), patch.object(lean, "hand_in", lambda dest: (dest, [])), \
                patch.object(lean, "run", spy_run), patch.object(lean, "loudness", spy_loudness), contextlib.redirect_stdout(io.StringIO()):
            lean._export(Args(film=str(d)))
        assert cmds and all("-vn" in c for c in cmds), f"loudness skips video decoding with -vn: {cmds}"
        assert len(calls) == 1, f"an untrimmed export meters its encoded mix once, not again in scan: {calls}"
        assert "LUFS integrated" in (Path(tmp) / "out" / "film" / "scan.txt").read_text(encoding="utf-8")


def test_a_stale_worked_film_sound_stops_the_export_with_the_command():
    # P3: sound.py newer than its mix printed a note and exported the old sound under a picture moved to a new beat
    import os
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, rendered, render = fake_film(tmp)
        (d / "media").mkdir()
        (d / "kit").mkdir()
        made = [d / "media" / "sound.wav", d / "kit" / "times.gen.ts"]
        for f in made:
            f.write_bytes(b"x")
        (d / "sound.py").write_text("# makes the sound", encoding="utf-8")
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
        score["sound_file"] = "media/sound.wav"
        (d / "score.json").write_text(json.dumps(score), encoding="utf-8")
        t = os.stat(d / "sound.py").st_mtime
        for older, why in ((made, "media/sound.wav and kit/times.gen.ts were made"), (made[1:], "kit/times.gen.ts was made")):
            for f in made:
                os.utime(f, (t - 60, t - 60) if f in older else (t + 60, t + 60))
            with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "raea_render", render), patch.object(lean, "must_preflight", lambda *a, **k: None):
                try:
                    lean.cmd_export(Args(film=str(d)))
                    raise AssertionError("a stale own mix stops the export")
                except SystemExit as e:
                    said = str(e)
            assert f"sound.py changed after {why}" in said and f"cd {d}" in said and said.rstrip().endswith("sound.py"), said
            assert not rendered, "it stops before the picture takes its place in the queue"
        for f in made:
            os.utime(f, (t + 60, t + 60))
        assert lean.own_sound(d, score) == d / "media" / "sound.wav", "a fresh mix is carried"


def test_named_events_and_meant_silences_are_checked_and_said_in_the_verdict():
    # P1: Plus One's events live in kit/times.gen.ts and score.json lists no sounds, so vd sound checked no sync and said
    # nothing of it. P2: the pages ask for silence on the name, and any such half second failed as a hole
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        x = np.zeros((int(4.0 * lean.SR), 2), np.float32)
        lean.place(x, lean.made("drone", 110, 4.0), 0.0, -12)
        x[int(2.0 * lean.SR):int(2.6 * lean.SR)] = 0                          # half a second of nothing, from 2.0 s
        for at in (0.5, 1.5, 3.3):
            lean.place(x, lean.made("tick", 1800), at, 0)
        wav = Path(tmp) / "mix.wav"
        lean.write_wav(wav, x)
        s = {"fps": 30, "duration": 4.0, "sounds": []}
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "loudness", lambda w: (-15.0, -3.0)):   # the level is not what is tested here
            plain = lean.check_sound(d, s, wav).splitlines()[-1]
            (d / "kit").mkdir()
            (d / "kit" / "times.gen.ts").write_text('// generated\nexport const CLOCK = {"FPS": 30};\n'
                                                     'export const CUES = [["ONE", 0.5], ["TWO", 1.5], ["LATE", 3.0]];\n'
                                                     'export const RESTS = [["the name", 2.0, 2.6]];\n', encoding="utf-8")
            assert lean.gen_data(d)["CUES"][1] == ["TWO", 1.5] and lean.gen_data(d)["CLOCK"] == {"FPS": 30}
            named = lean.check_sound(d, s, wav)
        assert plain.startswith("sound fails: silent hole at 2.0-2.6 s") and plain.endswith("sync not checked: no named events (score.json's sounds, or CUES in kit/times.gen.ts)"), plain
        last = named.splitlines()[-1]
        assert last.startswith("sound passes:") and "1 silence meant (the name)" in last, last
        assert "sync checked on 3 named events, 1 to check by ear: LATE (" in last, last
        assert "silences meant (named in score.json's rests or kit/times.gen.ts): the name 2-2.6 s" in named and "silent holes: none" in named, named
        # the same rest named in score.json
        holes, heard = lean.meant_holes([(2.0, 2.6), (3.5, 3.9)], lean.rests_of(Path(tmp) / "nowhere", {"rests": [{"name": "breath", "from": 1.95, "to": 2.6}]}))
        assert holes == [(3.5, 3.9)] and heard == [("breath", 1.95, 2.6)], (holes, heard)


def test_plus_ones_picture_reads_the_one_clock():
    # C3: the picture kept its own FPS, frames a beat and length, and repeated beats sound.py names (8.5, 16, 18.6, 19.5)
    film = lean.FILMS / "plusone"
    core, main_film = (film / "kit" / "core.tsx").read_text(encoding="utf-8"), (film / "film.tsx").read_text(encoding="utf-8")
    acts = (film / "acts1.tsx").read_text(encoding="utf-8") + (film / "acts2.tsx").read_text(encoding="utf-8")
    assert "FPS = CLOCK.FPS" in core and "FB = CLOCK.FB" in core and "FPS = 60" not in core and "FB = 32" not in core, core[:800]
    assert "FRAMES = CLOCK.BEATS * CLOCK.FB" in main_film and "S.fps" not in main_film and "S.duration" not in main_film
    import re
    cam = main_film[main_film.index("const CAM"):main_film.index("const CREEP")]
    numbered = re.findall(r"\[(?!0[,.])\d+(?:\.\d+)?,", cam)
    assert not numbered, f"every framing after the first is on a named beat: {numbered}"
    beat = r"(?<![-+] )\b\d+(?:\.\d+)? \* FB\b"   # a beat written as a number, not an offset from a named one (PICKF + 3 * FB)
    assert not re.findall(beat, acts), re.findall(beat, acts)
    sound = (film / "sound.py").read_text(encoding="utf-8")
    assert "export const {k} = {json.dumps(v)}" in sound and '("CLOCK", CLOCK)' in sound and '("CUES", CUES)' in sound


def test_the_queue_s_waiting_reaches_the_person_while_they_wait():
    # P4: raea_run says "queue: waiting 30 s; held by ..." at once, and vd look and vd export captured it and printed it
    # only after the wait. A stand-in tool says it waits, then waits until that line has reached the person (the test's
    # stderr writes a file when it sees it); a tool whose words are held back gives up after 20 s and fails
    import io
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        seen = Path(tmp) / "seen"
        tool = Path(tmp) / "tool.py"
        tool.write_text("import sys, time, pathlib\n"
                        "print('queue: waiting 30 s; held by pid 1 (render): another film', file=sys.stderr, flush=True)\n"
                        f"seen = pathlib.Path({str(seen)!r})\n"
                        "t0 = time.time()\n"
                        "while not seen.exists():\n"
                        "    if time.time() - t0 > 20: print('FAILED nobody saw the queue', flush=True); sys.exit(3)\n"
                        "    time.sleep(0.05)\n"
                        "print('OK 1.0s drawn', flush=True)\n", encoding="utf-8")

        class Watch(io.StringIO):
            def write(self, text):
                if "queue: waiting" in text:
                    seen.write_text("yes", encoding="utf-8")
                return super().write(text)
        from contextlib import redirect_stderr
        from unittest.mock import patch
        watch = Watch()
        with redirect_stderr(watch), patch.object(lean, "PY", sys.executable), patch.object(lean, "TOOLS", Path(tmp)):
            p = lean.streamed([sys.executable, tool])
            (Path(tmp) / "raea_run.py").write_text(tool.read_text(encoding="utf-8"), encoding="utf-8")
            seen.unlink()
            ok, secs, line = lean.raea_render(Path(tmp), Path(tmp) / "main.tsx", Path(tmp) / "out.mp4")
        assert p.returncode == 0 and p.stdout.strip() == "OK 1.0s drawn" and "queue: waiting" in p.stderr, (p.returncode, p.stdout, p.stderr)
        assert ok and line == "OK 1.0s drawn" and secs < 20, (ok, secs, line)
        assert watch.getvalue().count("queue: waiting 30 s") == 2, watch.getvalue()


def test_a_look_tile_s_stamp_covers_none_of_the_picture():
    # two readers could not check a film's act lines: every tile's time sat on the picture's top-left corner
    import look
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        pngs = []
        for k, c in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200))):
            pngs.append(Path(tmp) / f"frame-{k:05d}.png")
            Image.new("RGB", (1920, 1080), c).save(pngs[-1])
        out = Path(tmp) / "look.jpg"
        w, h = look.sheet(pngs, ["0.50 s  f30", "1.00 s  f60", "2.00 s  f120"], out)
        with Image.open(out) as im:
            im = im.convert("RGB")
            strip = h // 2 - 540
            assert w == 1920 and strip >= 16, (w, h)
            for k, c in enumerate(((200, 40, 40), (40, 200, 40))):
                got = im.getpixel((k * 960 + 2, strip + 2))
                assert all(abs(a - b) < 12 for a, b in zip(got, c)), f"tile {k + 1}'s corner is its picture: {got}"
                assert sum(im.getpixel((k * 960 + 900, 2))) < 30, "and its time is in the band above it"
            # the first person shown three moments in a grid of four asked which moment had not drawn: the odd tile
            # sits in the middle of its row, with no tile-shaped hole beside it
            row2 = h // 2 + strip
            mid, left, right = im.getpixel((960, row2 + 200)), im.getpixel((240, row2 + 200)), im.getpixel((1680, row2 + 200))
            assert all(abs(a - b) < 12 for a, b in zip(mid, (40, 40, 200))), f"the third tile is centred: {mid}"
            assert sum(left) < 60 and sum(right) < 60 and left == right, f"and the same margin lies each side of it: {left}, {right}"
    import sheet
    tile = sheet.stamp(Image.new("RGB", (320, 180), (200, 40, 40)), "f12  0.40s")
    assert tile.size == (320, 180 + sheet.STRIP) and tile.getpixel((1, sheet.STRIP + 1)) == (200, 40, 40), "move sheets: the same"


def test_look_says_each_kind_once_with_its_worst_cases_and_a_cut_first():
    # a camera moving over a page: hundreds of "outside the frame" lines, one per word per tile, and the one word cut by
    # the frame's edge while on screen lost among them
    import look
    W, H = 1920, 1080
    frames, fps = [0, 60, 120, 180], 60.0
    per = {f: [] for f in frames}
    for f in frames:
        for k in range(40):                                   # 40 words of the page, wholly outside, 100 + 50k px from the frame
            box = (W + 100 + 50 * k, 200, 300, 60)
            per[f].append(look.Note("outside", -look.distance_out(box, W, H), ("page.tsx:1", f"word {k}"), f"outside the frame: text “word {k}”"))
    cut = (W - 150, 500, 600, 80)                              # three quarters of it past the right edge, on tile 3
    per[120].append(look.Note("cut", look.outside_share(cut, W, H), ("card.tsx:9", "Mira's 30th"), "clipped: text “Mira's 30th”"))
    per[180].append(look.Note("nothing", 3, ("card.tsx:12", "img"), "drew no pixels: image 'img' at card.tsx:12"))
    assert abs(look.outside_share(cut, W, H) - 0.75) < 1e-9 and look.distance_out((W + 100, 0, 10, 10), W, H) == 100
    # Plus One's "19": right-aligned in a box 1311 px wide running 870 px past the left edge, whole on its tile
    nineteen = {"text": "19", "box": [-870, 91, 1311, 278], "size": 230, "lines": 1, "align": "right"}
    x, y, w, h = look.ink_box(nineteen)
    assert x > 0 and abs(x + w - 441) < 1e-6, "its letters are at the box's right end, inside the frame"
    assert look.ink_box(dict(nineteen, align="left"))[0] == -870, "left-aligned, they are at its left end, outside"
    assert look.ink_box({"text": "two lines", "box": [-50, 0, 400, 100], "size": 40, "lines": 2})[0] == -50, "wrapped text fills its box"
    # the four places a text can have against the edge. Plus One's side cards, mostly off the frame, were each called
    # FAULT on a first look with a newer raea: "Add a look", box -329,334 434x38, "about 100% of its letters outside"
    kind = lambda **t: getattr(look.edge_note({"lines": 1, "align": "left", "loc": "card.tsx:1", **t}, W, H), "kind", None)
    assert kind(text="Add a look", box=[-329, 334, 434, 38], size=32) == "outside", "its box reaches in, its letters do not: nothing is cut"
    assert "reaches in" in look.edge_note({"text": "Add a look", "box": [-329, 334, 434, 38], "size": 32, "lines": 1, "align": "left"}, W, H)
    assert kind(text="Omar", box=[W - 60, 988, 291, 44], size=40) == "cut", "letters across the edge are the fault"
    assert kind(**nineteen) == "box", "a wide box across the edge with its letters inside is not"
    assert kind(text="far", box=[W + 300, 10, 80, 30], size=24) == "outside" and kind(text="in", box=[100, 100, 80, 30], size=24) is None
    lines = look.summary(per, frames, fps)
    assert len(lines) <= 3 * 4, f"a few lines, not {sum(map(len, per.values()))}: {lines}"
    assert lines[0].startswith("!! FAULT, text cut by the frame's edge") and "tile 3" in lines[0] and "2.00 s" in lines[1] and "Mira" in lines[1], lines
    assert lines[2].startswith("drew no pixels"), "what draws nowhere comes before the page's words"
    head = next(i for i, l in enumerate(lines) if l.startswith("text wholly outside"))
    assert "40 on tiles 1, 2, 3, 4; the worst 3:" in lines[head], lines[head]
    shown = lines[head + 1:head + 4]
    assert len(shown) == 3 and "word 0" in shown[0] and "word 1" in shown[1] and "word 2" in shown[2], f"nearest the frame first: {shown}"
    assert "(and on 3 more tiles)" in shown[0], "a word seen on four tiles is one case"
    assert look.one_each(["render warn: frame-00001.png: 5% clip", "render warn: frame-00004.png: 5% clip", "other"]) == \
        ["render warn: frame-*.png: 5% clip  (on 2 stills)", "other"]
    # Bb3: two moments that round to the same frame name both tiles in summary()
    dup_note = look.Note("cut", 0.5, ("a.tsx:1", "Hello"), "clipped: text Hello")
    dup_lines = look.summary({60: [dup_note]}, [60, 60], 60.0)
    assert "tiles 1, 2:" in dup_lines[0] and "(and on 1 more tile)" in dup_lines[1], dup_lines
    import subprocess
    out = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "vd.py"), "look", "--help"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "--all" in out and "look-report.txt" in " ".join(out.split()), out
    # Ab2+Ab4: film-look is chosen before must_preflight, trailing commas in --at are ignored, and bad --at words exit cleanly
    from types import SimpleNamespace
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "look-film"
        d.mkdir()
        (d / "main.tsx").write_text('const FILM_ID = "f"; export default <Composition id={`${FILM_ID}-look`} />;\n', encoding="utf-8")
        (d / "score.json").write_text(json.dumps({"fps": 30, "duration": 10.0, "beats": [{"from": 0.0, "to": 10.0}]}), encoding="utf-8")
        pre, ran = [], []
        fake_stream = lambda cmd, **kw: ran.append(list(map(str, cmd))) or SimpleNamespace(returncode=0, stdout="LOOK ok\n", stderr="")
        import raea_run
        busy = [False]
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "room", lambda *a, **k: None), \
                patch.object(lean, "must_preflight", lambda e, c, f0, fs, r: pre.append((c, f0, fs, r))), \
                patch.object(lean, "streamed", fake_stream), patch.object(raea_run, "queue_free", lambda: not busy[0]):
            # A1b: a page film's look with the queue free runs no preflight (look.py's own render refuses as quickly)
            assert lean.main(["look", "--at", "2,9,", "--film", str(d)]) == 0
            assert pre == [] and len(ran) == 1, f"a flat film with a free queue is drawn without the checks: {pre}"
            busy[0] = True
            assert lean.main(["look", "--at", "2,9,", "--film", str(d)]) == 0
            assert pre == [("film-look", 60, [60, 270], 30)], f"preflight sees film-look and parsed frames: {pre}"
            busy[0] = False
            (d / "scene.tsx").write_text('import { Sphere } from "raea/3d";\n', encoding="utf-8")
            assert lean.main(["look", "--at", "2,9,", "--film", str(d)]) == 0
            assert len(pre) == 2, f"a film with 3D is checked first even when the queue is free: {pre}"
            (d / "scene.tsx").unlink()
            ran[:] = ran[1:]
            assert "--composition" in ran[0] and ran[0][ran[0].index("--composition") + 1] == "film-look", ran[0]
            assert ran[0][ran[0].index("--at") + 1] == "60,270", ran[0]
            for bad_at in ("2,bad", ","):
                try:
                    lean.main(["look", "--at", bad_at, "--film", str(d)])
                    raise AssertionError(f"bad --at {bad_at!r} should exit cleanly")
                except SystemExit as e:
                    assert "--at" in str(e), (bad_at, e)


def test_pin_leaves_out_words_heard_in_music():
    # a music film pinned 1.36 words a second: the transcriber heard a YouTube sign-off in it
    from unittest.mock import patch
    signoff = "Thank you so much for watching this video, and I'll see you in the next one. Thank you for watching this video, and I'll see you in the next one."
    heard = {"A_time": {"length_s": 47.7, "words": 30, "words_per_s": 1.36, "changes_in_sentence_gap": 2, "shot_len_median": 2.5},
             "D_motion": {"still_share": {"0.35": 0.1}}, "words": [{"w": w, "t0": i, "t1": i + 0.5} for i, w in enumerate(signoff.split())]}
    spoken = dict(heard, A_time=dict(heard["A_time"], length_s=3.5), words=[{"w": w, "t0": i * 0.3, "t1": i * 0.3 + 0.25} for i, w in enumerate("count the seconds and you know how far away it struck".split())])
    for m, words_kept in ((heard, False), (spoken, True)):
        with tempfile.TemporaryDirectory() as tmp:
            d, _, _ = fake_film(tmp)
            asked = []
            with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "measures_of", lambda ref, no_voice=False: asked.append(no_voice) or (m, Path(tmp) / "m.json")), \
                    patch.object(lean, "pin_material", lambda *a, **k: None):
                import io
                from contextlib import redirect_stdout
                buf = io.StringIO()
                with redirect_stdout(buf):
                    lean.cmd_pin(Args(film=str(d), ref="ref.mp4", k=5, no_voice=False))
            s = json.loads((d / "score.json").read_text(encoding="utf-8"))
            assert ("A_time.words_per_s" in s["targets"]) == words_kept and ("A_time.words_per_s" in s["targets_all"]) == words_kept, s["targets"]
            assert "A_time.shot_len_median" in s["targets"], "the rest is pinned as before"
            said = [l for l in buf.getvalue().splitlines() if l.startswith("no words-per-second target")]
            assert len(said) == (0 if words_kept else 1) and (words_kept or "false hearing" in said[0] and "--no-voice" in said[0]), buf.getvalue()
    with tempfile.TemporaryDirectory() as tmp:
        d, _, _ = fake_film(tmp)
        asked = []
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"), patch.object(lean, "measures_of", lambda ref, no_voice=False: asked.append(no_voice) or ({"A_time": {"shots": 3}}, Path(tmp) / "m.json")), \
                patch.object(lean, "pin_material", lambda *a, **k: None):
            assert lean.main(["pin", "ref.mp4", "--no-voice", "--film", str(d)]) == 0
        assert asked == [True], "--no-voice goes to the measure, which then skips the transcriber"


def test_one_level_target_and_a_verdict_that_says_pass_or_what_fails():
    # vd sound said "aim -14" while the scan and the pages said -15, and nothing said whether it passed
    assert (lean.LUFS_AIM, lean.LUFS_WITHIN, lean.PEAK_UNDER) == (-15.0, 1.0, -1.0)
    assert lean.sound_verdict(-15.4, -2.6, []) == "sound passes: -15.4 LUFS (within 1 of -15), true peak -2.6 dBTP (under -1), no silent hole; " \
        "sync not checked: no named events (score.json's sounds, or CUES in kit/times.gen.ts)"
    assert lean.sound_verdict(-14.0, -1.5, []).startswith("sound passes"), "1 LU away is within"
    bad = lean.sound_verdict(-16.3, -0.8, [(3.2, 4.0)])
    assert bad.startswith("sound fails: ") and "1.3 LU under -15" in bad and "-0.8 dBTP, not under -1" in bad and "silent hole at 3.2-4.0 s" in bad, bad
    assert lean.sound_verdict(-15.0, -1.0, []).startswith("sound fails"), "the peak must be under -1, not at it"
    src = "\n".join(l for l in (TOOLS / "lean.py").read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))   # its code, not the note on why
    assert "I=-14" not in src and "aim -14" not in src and "-14 LUFS" not in src, "one target everywhere"
    import scan
    assert scan.lean.level_faults is lean.level_faults if hasattr(scan, "lean") else "lean.level_faults" in (TOOLS / "scan.py").read_text(encoding="utf-8")
    # a made mix, checked: the verdict is the report's last line, and it passes
    with tempfile.TemporaryDirectory() as tmp:
        from unittest.mock import patch
        d, _, _ = fake_film(tmp)
        s = {"fps": 30, "duration": 4.0, "beats": [], "sounds": [{"make": "ping", "at": t, "pitch": 660} for t in (0.2, 1.1, 2.0, 2.9)],
             "bed": {"make": "drone", "pitch": 110, "gain": -18}}
        with patch.object(lean, "OUTROOT", Path(tmp) / "out"):
            report = lean.build_sound(d, s)
        last = report.strip().splitlines()[-1]
        assert last.startswith("sound passes: "), report
        assert "aim -15" in report.splitlines()[0], report.splitlines()[0]


def test_pin_keys_are_full_size_frames_at_rest_spread_over_the_film():
    # a maker could not read an interface on 400 px story tiles; the first frame of a busy stretch is the wrong moment
    import subprocess
    import pack
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        film, fps = Path(tmp) / "ref.mp4", 30
        # 12 s, 1280 x 720: still for the middle second of each 2 s sixth (frames 15..44 of each 60 hold one picture),
        # a picture that moves the rest of the time
        n = 12 * fps
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "1280x720", "-r", str(fps), "-i", "-",
                              "-c:v", "libx264", "-crf", "16", "-g", "1000", "-pix_fmt", "yuv420p", str(film)], stdin=subprocess.PIPE)
        ramp = np.tile(np.arange(1280, dtype=np.float32), (720, 1))
        for f in range(n):
            k, j = divmod(f, 60)
            c = 60 * k + (15 if 15 <= j < 45 else j)
            p.stdin.write(((ramp * 0.15 + 9 * c) % 256).astype(np.uint8).tobytes())
        p.stdin.close()
        assert p.wait() == 0
        times = pack.rest_times(film)
        assert len(times) == 6 and all(abs(t - (2 * k + 1.0)) <= 0.1 for k, t in enumerate(times)), f"the middle of each sixth's still second: {times}"
        made = pack.rest_keys(film, Path(tmp) / "pin")
        assert [f.name for f in made] == [f"key-{i}.jpg" for i in range(1, 7)], made
        with Image.open(made[2]) as im:
            size, comment = im.size, im.info.get("comment", b"").decode()
        assert size == (1280, 720) and comment == f"{times[2]:.2f} s", (size, comment)
        assert lean.key_time(made[2]) == f"{times[2]:.2f} s"
        wide = Path(tmp) / "wide.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=2560x1080:r=10:d=2", "-pix_fmt", "yuv420p", str(wide)], check=True)
        with Image.open(pack.rest_keys(wide, Path(tmp) / "w")[0]) as im:
            assert im.size == (1920, 810), "at most 1920 wide, the film's own shape"


HOLD = """import os
import sys
sys.path.insert(0, sys.argv[1])
import lean
with lean.one_export(sys.argv[2], "export"):
    print("held", os.getpid(), flush=True)
    sys.stdin.read()
"""


def holder_of(out):
    """Another process that holds a film's output folder as an export does, until its stdin closes or it is killed:
    (the process, the number it knows itself by). In a virtual environment on Windows the Python that runs is a child
    of the one started, so the number is asked of the process itself."""
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", HOLD, str(TOOLS), str(out)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    said = p.stdout.readline().split()
    assert said[:1] == ["held"], f"the other process took the folder: {said}"
    return p, int(said[1])


def test_two_exports_of_one_film_at_once_are_refused_and_nothing_is_left_to_go_stale():
    # a review's risk: two exports of one film took the same cut number and the same part files, and the one that
    # failed removed the other's. Its re-check's findings: a note naming the process could be taken over by two
    # commands at once, an ended process not yet collected counted as alive, and so did a reused process number. The
    # system's own lock has none of the three: it goes when its process does
    import os
    import shutil
    import time
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out" / "film"
        with lean.one_export(out, "export"):
            said = (out / lean.BUSY).read_text(encoding="utf-8")
            assert "vd export" in said and str(os.getpid()) in said, said
            try:
                with lean.one_export(out, "render"):
                    raise AssertionError("a second command ran beside the first")
            except SystemExit as e:
                assert "already running" in str(e) and "vd export" in str(e), e
        assert not (out / lean.BUSY).exists(), "the note goes when the export ends"
        try:
            with lean.one_export(out, "export"):
                raise KeyError("the export fails")
        except KeyError:
            pass
        with lean.one_export(out, "export"):
            pass                                            # free again after a failure
        other, pid = holder_of(out)
        try:
            try:
                with lean.one_export(out, "export"):
                    raise AssertionError("a second export ran beside another process's")
            except SystemExit as e:
                assert "already running" in str(e) and f"process {pid}" in str(e) and "Nothing was made" in str(e), e
            d, _, _ = fake_film(tmp)
            with patch.object(lean, "OUTROOT", Path(tmp) / "out"):
                assert lean.outdir(d) == out
                # the whole commands refuse, before a cut number is taken or anything is drawn
                for cmd in (["export", "--film", str(d)], ["render", "--film", str(d), "--from", "0", "--to", "1"]):
                    try:
                        lean.main(cmd)
                        raise AssertionError(f"vd {cmd[0]} ran beside a live export")
                    except SystemExit as e:
                        assert "already running" in str(e), e
                assert not (out / "cuts").exists(), "nothing was begun"
                # and a second folder of the same name clears nothing from under the export: its command was refused a
                # moment later, after it had removed the picture and sound the export was about to join
                (out / "film.picture.mp4").write_bytes(b"the picture")
                (out / "sound.wav").write_bytes(b"the sound")
                twin = Path(tmp) / "elsewhere" / "film"
                shutil.copytree(d, twin)
                try:
                    lean.outdir(twin)
                    raise AssertionError("another folder took the output folder over while an export held it")
                except SystemExit as e:
                    assert "right now" in str(e) and "Nothing was changed" in str(e) and f"process {pid}" in str(e), e
                assert (out / "film.picture.mp4").read_bytes() == b"the picture" and (out / "sound.wav").read_bytes() == b"the sound"
                assert (out / lean.OWNER).read_text(encoding="utf-8").strip() == str(d.resolve()), "and it is still the first folder's"
        finally:
            other.stdin.close()
            other.wait(timeout=30)
        # a process that ends without tidying up (killed) leaves its note and no lock
        import psutil
        killed, pid = holder_of(out)
        for q in {killed.pid, pid}:
            try:
                psutil.Process(q).kill()
            except psutil.Error:
                pass
        killed.wait(timeout=30)
        assert (out / lean.BUSY).exists(), "the killed process's note is still there"
        for _ in range(50):
            try:
                with lean.one_export(out, "export"):
                    break
            except SystemExit:
                time.sleep(0.1)                             # the system is still closing the dead process's files
        else:
            raise AssertionError("a dead process's note kept the next export out")


def test_the_blur_takes_its_turn_in_the_machines_queue():
    # the re-check's finding: the averaging is a whole-film encode, and it began the moment the engine let the queue
    # go, beside whatever render had been waiting
    import types
    from unittest.mock import patch
    import raea_run
    events = []

    class Turn:
        def close(self):
            events.append("let go")

    def taken(**kw):
        events.append(("taken", kw.get("kind")))
        return Turn()

    def blur(args, **kw):
        events.append("blur")
        if ok:
            Path(args[5]).write_bytes(b"averaged")
        return types.SimpleNamespace(returncode=0 if ok else 1, stdout="", stderr="no room")
    with tempfile.TemporaryDirectory() as tmp, patch.object(raea_run, "one_at_a_time", taken), patch.object(lean, "run", blur):
        ok = True
        lean.averaged(Path(tmp) / "pictures.mp4", Path(tmp) / "picture.mp4", 4, 3, 60)
        assert events == [("taken", "heavy"), "blur", "let go"], events
        ok, events[:] = False, []
        try:
            lean.averaged(Path(tmp) / "pictures.mp4", Path(tmp) / "none.mp4", 4, 3, 60)
            raise AssertionError("a blur that failed is said")
        except SystemExit as e:
            assert "the blur failed" in str(e) and "no room" in str(e), e
        assert events == [("taken", "heavy"), "blur", "let go"], f"the queue is let go when the blur fails too: {events}"


def test_worked_film_sound_cache_restores_every_output_and_invalidates_on_any_input():
    # C4: repeated `vd new --like` under one VD_OUT reuses sound.py's outputs (including onoma's kit/waves.gen.ts),
    # sets fresh mtimes so own_sound never stops on a cached file, and invalidates when sound.py, score.json,
    # media/sounds/* or the ffmpeg version changes
    import io
    import os
    import time
    from contextlib import redirect_stdout
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        real_run = lean.run
        sound_runs = []

        def spy_run(args, **kw):
            if [str(x) for x in args[-2:]] == ["utf8", "sound.py"]:
                sound_runs.append(Path(kw["cwd"]).name)
            return real_run(args, **kw)

        with patch.object(lean, "OUTROOT", out), patch.object(lean, "run", spy_run), redirect_stdout(io.StringIO()):
            lean.main(["new", str(Path(tmp) / "onoma_cold"), "--like", "onoma"])
            lean.main(["new", str(Path(tmp) / "onoma_warm"), "--like", "onoma"])
        assert sound_runs == ["onoma_cold"], f"the second copy under one OUTROOT reuses cached sound.py outputs: {sound_runs}"
        cold, warm = Path(tmp) / "onoma_cold", Path(tmp) / "onoma_warm"
        for rel in ("media/sound.wav", "kit/times.gen.ts", "kit/waves.gen.ts", "score.json"):
            assert (warm / rel).read_bytes() == (cold / rel).read_bytes(), f"{rel} differs between cold and cached copy"
        assert lean.own_sound(warm, lean.score_of(warm)) == warm / "media" / "sound.wav"
        with patch.object(lean, "OUTROOT", out):
            code, clean_said = _clean("--orphans")
            assert code == 0 and ".worked-sound" not in clean_said, clean_said
            assert _refused(".worked-sound", "--yes")

        films = Path(tmp) / "films"
        mini = films / "mini"
        (mini / "kit").mkdir(parents=True)
        (mini / "media" / "sounds" / "inst").mkdir(parents=True)
        (mini / "film.tsx").write_text("export const Film = () => null;\n", encoding="utf-8")
        (mini / "score.json").write_text(json.dumps({"fps": 30, "width": 64, "height": 36, "duration": 1.0, "bpm": 120, "beats": [], "sounds": []}), encoding="utf-8")
        (mini / "media" / "sounds" / "inst" / "c4.bin").write_bytes(b"sample-v1")
        (mini / "kit" / "times.gen.ts").write_text("// old\n", encoding="utf-8")
        (mini / "kit" / "waves.gen.ts").write_text("// old\n", encoding="utf-8")
        (mini / "sound.py").write_text(
            "from pathlib import Path\n"
            "tag = Path('media/sounds/inst/c4.bin').read_bytes().decode()\n"
            "(Path('media') / 'sound.wav').write_bytes(b'RIFF' + tag.encode())\n"
            "(Path('kit') / 'times.gen.ts').write_text(f'export const TAG = {tag!r};\\n', encoding='utf-8')\n"
            "(Path('kit') / 'waves.gen.ts').write_text(f'export const WAVES = {tag!r};\\n', encoding='utf-8')\n"
            "print('mini sound ready')\n",
            encoding="utf-8",
        )
        old_t = time.time() - 120
        for g in (mini / "kit" / "times.gen.ts", mini / "kit" / "waves.gen.ts"):
            os.utime(g, (old_t, old_t))
        os.utime(mini / "sound.py", (old_t + 60, old_t + 60))
        sound_runs.clear()
        ff_ver = ["ffmpeg version 7.1-fake"]
        n = 0

        def copy_mini():
            nonlocal n
            n += 1
            dest = Path(tmp) / f"m_{n}"
            with patch.object(lean, "OUTROOT", out), patch.object(lean, "FILMS", films), patch.object(lean, "run", spy_run), \
                    patch.object(lean, "ffmpeg_version", lambda: ff_ver[0]), redirect_stdout(io.StringIO()):
                lean.main(["new", str(dest), "--like", "mini"])
            assert lean.own_sound(dest, lean.score_of(dest)) == dest / "media" / "sound.wav"
            assert (dest / "kit" / "times.gen.ts").stat().st_mtime >= (dest / "sound.py").stat().st_mtime
            assert (dest / "kit" / "waves.gen.ts").stat().st_mtime >= (dest / "sound.py").stat().st_mtime
            return dest

        d1 = copy_mini()
        d2 = copy_mini()
        assert len(sound_runs) == 1 and "sample-v1" in (d2 / "kit" / "waves.gen.ts").read_text(encoding="utf-8")
        (mini / "media" / "sounds" / "inst" / "c4.bin").write_bytes(b"sample-v2")
        d3 = copy_mini()
        assert len(sound_runs) == 2 and "sample-v2" in (d3 / "kit" / "waves.gen.ts").read_text(encoding="utf-8")
        copy_mini()
        assert len(sound_runs) == 2
        (mini / "score.json").write_text(json.dumps({"fps": 30, "width": 64, "height": 36, "duration": 1.0, "bpm": 100, "beats": [], "sounds": []}), encoding="utf-8")
        copy_mini()
        assert len(sound_runs) == 3
        (mini / "sound.py").write_text((mini / "sound.py").read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        copy_mini()
        assert len(sound_runs) == 4
        ff_ver[0] = "ffmpeg version 8.0-fake"
        copy_mini()
        assert len(sound_runs) == 5
        copy_mini()
        assert len(sound_runs) == 5
        with patch.object(np, "__version__", "99.0-fake"):
            copy_mini()
            assert len(sound_runs) == 6
            copy_mini()
            assert len(sound_runs) == 6
        with patch.object(lean.sys, "version_info", (3, 99, 0)):
            copy_mini()
            assert len(sound_runs) == 7
            copy_mini()
            assert len(sound_runs) == 7


if __name__ == "__main__":
    import utf8  # noqa: F401
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
