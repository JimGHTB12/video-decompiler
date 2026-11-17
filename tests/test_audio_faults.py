#!/usr/bin/env python3
"""tools/tempo_map.py and tools/voice_clean.py (`vd audio`) on small sounds made here with known answers.

Tempo: click tracks at 120 and at 100 beats a minute, with no tempo given, are read to within one beat a minute and
their first beat to within 15 ms; a track with only two clicks has no grid, and `vd audio --tempo-map` refuses it and
leaves the film's clock as it was, instead of writing a made-up tempo into it. Clicks speeding up from 112 to 124 beats a
minute are reported stretch by stretch, rising, and refused for sliding more than 40 ms off one steady grid; a tempo
given outside 60 to 200 is told its half or double, not a crash. Voice: a voice-like sound passes every
step; the same sound with a guard of 0 dB has a step refused and named; silence is refused, not levelled; a file that
is not sound, and an output that is the input, stop with a message. Needs ffmpeg.

  python tests/test_audio_faults.py
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import lean  # noqa: E402
import tempo_map  # noqa: E402
import voice_clean  # noqa: E402

SR = 48000


def write_wav(path, mono):
    pcm = (np.clip(np.asarray(mono, dtype=np.float64), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


def clicks(path, bpm, seconds=12.0, first=0.25, count=None):
    """A short decaying kick on every beat from `first` seconds, at `bpm`; `count` stops after that many."""
    x = np.zeros(int(seconds * SR))
    period = 60.0 / bpm
    th = np.arange(int(0.08 * SR)) / SR
    kick = 0.5 * np.sin(2 * np.pi * 95.0 * th * (1 + 0.8 * np.exp(-th * 40))) * np.exp(-th * 28)
    n = 0
    t = first
    while t + 0.08 < seconds and (count is None or n < count):
        i = int(round(t * SR))
        x[i:i + len(kick)] += kick
        t += period
        n += 1
    write_wav(path, x)


def voice_like(path, seconds=6.0):
    """Harmonics on a moving pitch, shaped into syllables, over quiet room noise: speech-band energy with no words."""
    t = np.arange(int(seconds * SR)) / SR
    phase = 2 * np.pi * np.cumsum(130 + 15 * np.sin(2 * np.pi * 1.3 * t)) / SR
    tone = sum(np.sin(h * phase) / h for h in range(1, 20))
    syllables = np.clip(np.sin(2 * np.pi * 2.5 * t) * 1.4, 0, 1) ** 0.7
    rng = np.random.default_rng(4)
    write_wav(path, 0.05 * tone * syllables + 0.003 * rng.standard_normal(len(t)))


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
        try:
            return fn(*args, **kwargs), out.getvalue()
        except SystemExit as e:
            return e, out.getvalue()


def test_tempo_is_read_without_being_told():
    with tempfile.TemporaryDirectory() as tmp:
        for bpm in (120.0, 100.0):
            f = Path(tmp) / f"clicks{int(bpm)}.wav"
            clicks(f, bpm)
            res, code = tempo_map.analyse_file(f)
            assert code == 0, (bpm, res["flags"])
            assert abs(res["bpm"] - bpm) < 1.0, f"{bpm} BPM clicks read as {res['bpm']}"
            assert abs(res["offset_s"] - 0.25) < 0.015, f"first beat at 0.25 s read as {res['offset_s']}"


def test_no_grid_is_refused_and_the_film_keeps_its_clock():
    with tempfile.TemporaryDirectory() as tmp:
        two = Path(tmp) / "two.wav"
        clicks(two, 120.0, count=2)
        res, code = tempo_map.analyse_file(two)
        assert code == 1 and res["bpm"] is None, res
        film = Path(tmp) / "f"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        gen = film / "kit" / "times.gen.ts"
        before = gen.read_bytes() if gen.is_file() else None
        score_before = (film / "score.json").read_bytes()
        r, _ = quiet(lean.main, ["audio", str(two), "--tempo-map", "--film", str(film)])
        assert isinstance(r, SystemExit) and "grid" in str(r.code), f"a track with no beat grid was mapped: {r!r}"
        assert (gen.read_bytes() if gen.is_file() else None) == before, "times.gen.ts changed although no grid was found"
        assert (film / "score.json").read_bytes() == score_before, "score.json changed although no grid was found"
        assert not (film / "media" / "two.wav").exists(), "the refused track was copied into the film"


def test_voice_cleanup_guards():
    with tempfile.TemporaryDirectory() as tmp:
        v = Path(tmp) / "voice.wav"
        voice_like(v)
        rep = voice_clean.clean_voice(v, Path(tmp) / "clean.wav")
        assert rep["refused"] is None and [r["step"] for r in rep["steps"]] == [n for n, _ in voice_clean.STAGES] + ["final_level"], rep
        # the guard: allowed no loss at all, some step costs a little speech-band power, and is refused by name
        rep = voice_clean.clean_voice(v, Path(tmp) / "strict.wav", max_speech_loss_db=0.0)
        assert rep["exit_code"] == 1 and "exceeded speech-band loss limit" in rep["refused"], rep["refused"]
        assert rep["refused"].split()[0] in [n for n, _ in voice_clean.STAGES] + ["final_level"]
        assert (Path(tmp) / "strict.wav").is_file(), "the steps before the refused one are kept as the output"
        # silence: nothing to level, so it is refused rather than raised by 6 dB of noise
        s = Path(tmp) / "silence.wav"
        write_wav(s, np.zeros(SR * 3))
        rep = voice_clean.clean_voice(s, Path(tmp) / "s-clean.wav")
        assert rep["exit_code"] == 1 and "silence" in rep["refused"], rep["refused"]
        # a refused cleanup never replaces a voice the film already uses
        film = Path(tmp) / "voiced"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        good = film / "media" / "voice-clean.wav"
        quiet(lean.main, ["audio", str(v), "--clean-voice", "--film", str(film)])
        assert good.is_file() and lean.score_of(film).get("voice") == "media/voice-clean.wav"
        kept = good.read_bytes()
        loud = Path(tmp) / "voice.wav"   # the same name, now silence: its cleanup is refused
        write_wav(loud, np.zeros(SR * 3))
        quiet(lean.main, ["audio", str(loud), "--clean-voice", "--film", str(film)])
        assert good.read_bytes() == kept, "a refused cleanup replaced the voice in use"
        assert (film / "media" / "voice-clean-partial.wav").is_file()
        assert lean.score_of(film).get("voice") == "media/voice-clean.wav"
        # an output named with -o inside the film is the voice score.json names, at that path
        take = Path(tmp) / "take.wav"   # voice.wav is silence by now
        voice_like(take)
        quiet(lean.main, ["audio", str(take), "--clean-voice", "--film", str(film), "-o", str(film / "take-clean.wav")])
        assert lean.score_of(film).get("voice") == "take-clean.wav" and (film / "take-clean.wav").is_file(), lean.score_of(film).get("voice")
        # -o naming the take itself is refused, and the take is left as it was
        before = take.read_bytes()
        r, _ = quiet(lean.main, ["audio", str(take), "--clean-voice", "--film", str(film), "-o", str(take)])
        assert isinstance(r, SystemExit) and "take itself" in str(r.code) and take.read_bytes() == before, r
        # names the command makes for itself never land on the take: a take called NAME.new.wav cleaned to NAME.wav is kept,
        # and a silent take called NAME-partial.wav, refused, leaves its refusal under another name
        odd = Path(tmp) / "odd.new.wav"
        voice_like(odd)
        odd_bytes = odd.read_bytes()
        quiet(lean.main, ["audio", str(odd), "--clean-voice", "--film", str(film), "-o", str(Path(tmp) / "odd.wav")])
        assert odd.is_file() and odd.read_bytes() == odd_bytes, "the take was deleted or changed"
        hush = Path(tmp) / "hush-partial.wav"
        write_wav(hush, np.zeros(SR * 3))
        hush_bytes = hush.read_bytes()
        quiet(lean.main, ["audio", str(hush), "--clean-voice", "--film", str(film), "-o", str(Path(tmp) / "hush.wav")])
        assert hush.read_bytes() == hush_bytes and (Path(tmp) / "hush-partial-2.wav").is_file(), "a refusal overwrote the take"
        # broke: the voice in its object form, {"file": ..., "at": ..., "gain": ...}, was not protected, and a refused
        # cleanup of silent.wav wrote over the voice in use, media/silent-clean-partial.wav, saying it was unchanged
        active = film / "media" / "silent-clean-partial.wav"
        active.write_bytes(kept)
        sc = lean.score_of(film)
        sc["voice"] = {"file": "media/silent-clean-partial.wav", "at": 0.0, "gain": 0}
        (film / "score.json").write_text(json.dumps(sc), encoding="utf-8")
        silent = Path(tmp) / "silent.wav"
        write_wav(silent, np.zeros(SR * 3))
        quiet(lean.main, ["audio", str(silent), "--clean-voice", "--film", str(film)])
        assert active.read_bytes() == kept, "a refused cleanup replaced the voice in use, named in its object form"
        assert (film / "media" / "silent-clean-partial-2.wav").is_file()
        # a cleanup that is kept changes only the voice's file, not where it starts or its level (both were dropped)
        quiet(lean.main, ["audio", str(take), "--clean-voice", "--film", str(film)])
        v2 = lean.score_of(film)["voice"]
        assert isinstance(v2, dict) and v2["at"] == 0.0 and v2["gain"] == 0 and v2["file"] == "media/take-clean.wav", v2
        # cleaning a voice or mapping a track writes into a film folder, so neither makes one where it is run
        bare = Path(tmp) / "not-a-film"
        bare.mkdir()
        for flag in ("--clean-voice", "--tempo-map"):
            r, _ = quiet(lean.main, ["audio", str(take), flag, "--film", str(bare)])
            assert isinstance(r, SystemExit) and not (bare / "score.json").exists(), (flag, r)
        # not sound, and an output that would overwrite its input
        junk = Path(tmp) / "notes.wav"
        junk.write_text("this is not a wav file\n", encoding="utf-8")
        film = Path(tmp) / "f"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        r, _ = quiet(lean.main, ["audio", str(junk), "--clean-voice", "--film", str(film)])
        assert isinstance(r, SystemExit) and "notes.wav" in str(r.code), f"a file that is not sound should stop with its name: {r!r}"
        try:
            voice_clean.clean_voice(v, v)
            raise AssertionError("cleaning a file onto itself was allowed")
        except ValueError as e:
            assert "distinct" in str(e)


FILMS = ROOT / "skills" / "video-decompiler" / "library" / "films"
FB_LINE = "a track mapped by vd audio --tempo-map sets the beat"


def run_sound_py(film):
    subprocess.run([sys.executable, "sound.py"], cwd=film, check=True, capture_output=True)


def onsets(wav_path, floor=0.2):
    """Times of the kicks in a built mix: where the level first rises past `floor` of its peak after a quiet stretch."""
    import wave as wave_mod
    with wave_mod.open(str(wav_path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels()).mean(axis=1) / 32768
        rate = w.getframerate()
    env = np.convolve(np.abs(x), np.ones(48) / 48, mode="same")
    on, last = [], -1.0
    for i in np.flatnonzero(env > floor * env.max()):
        t = i / rate
        if t - last > 0.15:
            on.append(t)
        last = t
    return on


def test_the_worked_films_sound_the_same_with_no_track_mapped():
    # the line each sound.py gained reads score.json's music; with none, the clock and the mix are what they were
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("linden", "onoma", "plusone", "stet"):
            film = Path(tmp) / name
            shutil.copytree(FILMS / name, film, ignore=shutil.ignore_patterns("media"))
            if (FILMS / name / "media" / "sounds").is_dir():
                shutil.copytree(FILMS / name / "media" / "sounds", film / "media" / "sounds")
            (film / "media").mkdir(exist_ok=True)
            run_sound_py(film)
            assert (film / "kit" / "times.gen.ts").read_bytes() == (FILMS / name / "kit" / "times.gen.ts").read_bytes(), f"{name}: the clock changed"
            now = (film / "media" / "sound.wav").read_bytes()
            src = (film / "sound.py").read_text(encoding="utf-8")
            (film / "sound.py").write_text("\n".join(l for l in src.splitlines() if FB_LINE not in l) + "\n", encoding="utf-8")
            run_sound_py(film)
            assert (film / "media" / "sound.wav").read_bytes() == now, f"{name}: the mix changed"


def test_a_mapped_track_becomes_the_films_beat():
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "linden"
        quiet(lean.main, ["new", str(film), "--like", "linden"])
        # a 128 BPM track: the nearest beat a 60 fps film holds is 28 frames (128.57 BPM), so it is stretched by 0.45%
        track = Path(tmp) / "clicks128.wav"
        clicks(track, 128.0, seconds=30.0, first=0.40)
        r, _ = quiet(lean.main, ["audio", str(track), "--tempo-map", "--replace-own-mix", "--film", str(film)])
        m = lean.score_of(film)["music"]
        assert r == 0 and m["fb"] == 28 and abs(m["stretch"] - (3600 / 28) / 128) < 1e-4 and (film / m["file"]).is_file(), (r, m)
        # its beat is not the film's until the film's sound.py has run: the mix stops rather than lay it on the old beat
        r, out = quiet(lean.main, ["sound", "--film", str(film)])
        assert isinstance(r, SystemExit) and "sound.py" in str(r.code), r
        run_sound_py(film)
        clock = lean.gen_data(film)["CLOCK"]
        assert clock["FB"] == 28, clock
        assert "music" in lean.score_of(film), "sound.py kept the mapped track in score.json"
        quiet(lean.main, ["sound", "--film", str(film)])
        beat = 28 / 60
        dur = lean.score_of(film)["duration"]
        got = [t for t in onsets(lean.outdir(film) / "sound.wav") if t < dur - 0.2]
        assert len(got) >= dur / beat - 2, (len(got), dur / beat)
        worst = max(abs(t - round(t / beat) * beat) for t in got)
        assert worst < 0.025, f"a kick lands {worst * 1000:.0f} ms off the film's beat"
        # a track already on a beat the film can hold is not stretched
        hundred = Path(tmp) / "clicks100.wav"
        clicks(hundred, 100.0, seconds=30.0)
        quiet(lean.main, ["audio", str(hundred), "--tempo-map", "--film", str(film)])
        m = lean.score_of(film)["music"]
        assert m["fb"] == 36 and abs(m["stretch"] - 1.0) < 1e-3, m
        # the accepted films' own music, made on an exact grid, is mapped, not refused (a drift rule refused Onoma's and
        # Linden's, so there is none): each film's 720p copy's sound, into a copy of that film, gives back its own beat
        # Onoma's and Linden's own music have a weak grid (as weak as white noise), so they need their tempo given
        for name, fb, given in (("onoma", 30, "120"), ("linden", 36, "100"), ("plusone", 32, None), ("stet", 24, None)):
            own = Path(tmp) / f"{name}-own.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "docs" / "media" / f"{name}.mp4"), "-vn", "-ac", "2", "-ar", "48000", str(own)], check=True)
            copy = Path(tmp) / f"{name}-copy"
            quiet(lean.main, ["new", str(copy), "--like", name])
            if given:
                r, _ = quiet(lean.main, ["audio", str(own), "--tempo-map", "--film", str(copy)])
                assert isinstance(r, SystemExit) and "--bpm" in str(r.code) and "music" not in lean.score_of(copy), (name, r)
            r, _ = quiet(lean.main, ["audio", str(own), "--tempo-map", "--film", str(copy), *(["--bpm", given] if given else [])])
            assert r == 0 and lean.score_of(copy)["music"]["fb"] == fb, (name, r, lean.score_of(copy).get("music"))
        # a track with no beat is refused, not mapped (white noise once mapped at 177.6 BPM, a drone at 198)
        rng = np.random.default_rng(1)
        for name, x in (("noise", 0.2 * rng.standard_normal(20 * SR)), ("drone", 0.3 * np.sin(2 * np.pi * 220 * np.arange(20 * SR) / SR))):
            f = Path(tmp) / f"{name}.wav"
            write_wav(f, x)
            r, _ = quiet(lean.main, ["audio", str(f), "--tempo-map", "--film", str(film)])
            assert isinstance(r, SystemExit) and lean.score_of(film)["music"] == m, (name, r)

def accelerating(path, bpm0, bpm1, seconds=28.0, first=0.25):
    """A kick on every beat of a tempo that rises evenly from bpm0 to bpm1, like a band speeding up, and a softer one
    between beats (a 1906 ragtime record read 112 BPM at its start and 124 at its end)."""
    x = np.zeros(int(seconds * SR))
    th = np.arange(int(0.08 * SR)) / SR
    kick = 0.5 * np.sin(2 * np.pi * 95.0 * th * (1 + 0.8 * np.exp(-th * 40))) * np.exp(-th * 28)
    t = first
    while t + 0.6 < seconds:
        period = 60.0 / (bpm0 + (bpm1 - bpm0) * t / seconds)
        for at, level in ((t, 1.0), (t + period / 2, 0.4)):
            i = int(round(at * SR))
            x[i:i + len(kick)] += level * kick
        t += period
    write_wav(path, x)


def test_a_track_that_speeds_up_is_reported_and_refused_and_a_tempo_out_of_range_is_told():
    # broke: a band record that speeds up about 10% was fitted to one tempo and mapped, its drift unseen (each half was
    # fitted within 1.5% of the whole), and --bpm 232 (a valid eighth-note tempo) crashed the fit with an IndexError
    with tempfile.TemporaryDirectory() as tmp:
        steady, faster = Path(tmp) / "steady.wav", Path(tmp) / "faster.wav"
        clicks(steady, 120.0, seconds=28.0)
        accelerating(faster, 112.0, 124.0)
        res, _ = tempo_map.analyse_file(steady)
        assert res["drift_ms"] is not None and res["drift_ms"] < 5 and all(abs(s["bpm"] - 120) < 1 for s in res["stretches"]), (res["drift_ms"], res["stretches"])
        res, _ = tempo_map.analyse_file(faster, bpm=118)
        st = res["stretches"]
        assert len(st) >= 3 and st[-1]["bpm"] - st[0]["bpm"] >= 5, ("each stretch's tempo is reported, and it rises", st)
        assert res["drift_ms"] > tempo_map.DRIFT_MAX_MS, res["drift_ms"]
        film = Path(tmp) / "f"
        quiet(lean.main, ["new", str(film), "--like", "linden"])
        before = (film / "score.json").read_bytes()
        r, _ = quiet(lean.main, ["audio", str(faster), "--tempo-map", "--bpm", "118", "--film", str(film)])
        said = str(getattr(r, "code", r))
        assert isinstance(r, SystemExit) and "steady" in said and f"{res['drift_ms']:.0f} ms" in said and "BPM" in said, said
        assert (film / "score.json").read_bytes() == before, "a refused track changed score.json"
        # a tempo outside what the fit reads is told, with the one to give, not a crash
        try:
            tempo_map.analyse_file(steady, bpm=232)
            raise AssertionError("--bpm 232 was taken")
        except ValueError as e:
            assert "116" in str(e) and "200" in str(e), e
        r, _ = quiet(tempo_map.main, [str(steady), "--bpm", "232"])
        assert isinstance(r, SystemExit) and "116" in str(r.code), r
        r, _ = quiet(lean.main, ["audio", str(steady), "--tempo-map", "--bpm", "232", "--film", str(film)])
        assert isinstance(r, SystemExit) and "116" in str(r.code) and (film / "score.json").read_bytes() == before, r


def test_a_drop_lands_on_the_beat_named():
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "linden"
        quiet(lean.main, ["new", str(film), "--like", "linden"])
        # 100 BPM (36 frames a beat, no stretch); quiet kicks for 4 bars, then loud from 0.25 + 16 beats = 9.85 s
        track = Path(tmp) / "drop.wav"
        x = np.zeros(int(30 * SR))
        th = np.arange(int(0.08 * SR)) / SR
        kick = np.sin(2 * np.pi * 95.0 * th) * np.exp(-th * 28)
        for k in range(48):
            t = 0.25 + k * 0.6
            i = int(t * SR)
            x[i:i + len(kick)] += kick * (0.6 if k >= 16 else 0.12) * (1.5 if k % 4 == 0 else 1.0)   # each bar's first beat accented
        write_wav(track, x)
        r, _ = quiet(lean.main, ["audio", str(track), "--tempo-map", "--drop-at-beat", "24", "--film", str(film)])
        m = lean.score_of(film)["music"]
        assert r == 0 and m["fb"] == 36, (r, m)
        # the drop at 9.85 s of the track lands on beat 24 = 14.4 s of the film: the track starts 4.55 s in
        assert abs(m["at"] - 4.55) < 0.03 and m["from"] == 0.0, m
        # the track's first beat (0.25 s into the file) falls at 4.80 s of the film, not at the file's start (it had said 4.55)
        assert abs(m["first_beat_s"] - 4.80) < 0.03, m



def test_one_output_name_and_a_sheet_outside_a_film():
    # broke: --clean-voice --sheet -o custom.png wrote the cleaned voice to custom.png, named it as the voice, then drew
    # the sheet over it; -o some.jpg was dropped for listen-sheet.png; and outside a film folder the sheet made an output
    # folder named after the folder it was run in
    import os
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "f"
        quiet(lean.main, ["new", str(film), "--kind", "launch"])
        take = Path(tmp) / "take.wav"
        voice_like(take)
        r, _ = quiet(lean.main, ["audio", str(take), "--clean-voice", "--sheet", "--film", str(film), "-o", str(Path(tmp) / "custom.png")])
        assert isinstance(r, SystemExit) and "-o" in str(r.code) and not (Path(tmp) / "custom.png").exists(), r
        assert lean.score_of(film).get("voice") in (None, ""), lean.score_of(film).get("voice")
        # with --clean-voice the sheet draws the cleaned voice, not the take (it had drawn the raw take)
        import listen
        from unittest.mock import patch
        drawn = []
        with patch.object(listen, "measure", lambda p, *a, **k: drawn.append(Path(p)) or {"measurements": {"integrated_lufs": 0, "true_peak_dbtp": 0, "side_to_mid_db": 0, "correlation": 0}}),                 patch.object(listen, "sheet", lambda p, out, **k: {"png": str(out)}):
            quiet(lean.main, ["audio", str(take), "--clean-voice", "--sheet", "--film", str(film)])
        assert drawn and drawn[0].name == "take-clean.wav", drawn
        r, _ = quiet(lean.main, ["audio", str(take), "--sheet", "--film", str(film), "-o", str(Path(tmp) / "s.jpg")])
        assert isinstance(r, SystemExit) and ".png" in str(r.code), r
        bare = Path(tmp) / "loose"
        bare.mkdir()
        old_cwd, old_out = os.getcwd(), lean.OUTROOT
        os.chdir(bare)
        lean.OUTROOT = Path(tmp) / "out"
        try:
            r, _ = quiet(lean.main, ["audio", str(take), "--sheet"])
        finally:
            os.chdir(old_cwd)
            lean.OUTROOT = old_out
        assert r == 0 and (Path(tmp) / "take-sheet.png").is_file(), r
        assert not (Path(tmp) / "out" / "loose").exists(), "an output folder was made for a folder that is no film"



def test_mapping_a_track_keeps_what_the_film_uses():
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "linden"
        quiet(lean.main, ["new", str(film), "--like", "linden"])
        # broke: a voice called beat-fitted.wav was written over by the fitted copy of beat.wav
        voice = film / "media" / "beat-fitted.wav"
        voice_like(voice)
        before = voice.read_bytes()
        sc = lean.score_of(film)
        sc["voice"] = "media/beat-fitted.wav"
        (film / "score.json").write_text(json.dumps(sc), encoding="utf-8")
        beat = Path(tmp) / "beat.wav"
        clicks(beat, 100.0, seconds=30.0)
        r, _ = quiet(lean.main, ["audio", str(beat), "--tempo-map", "--film", str(film)])
        m = lean.score_of(film)["music"]
        assert r == 0 and voice.read_bytes() == before and m["file"] != "media/beat-fitted.wav", (r, m)
        # broke: --drop-at-beat on a track with no drop placed it anyway and recorded the request
        r, _ = quiet(lean.main, ["audio", str(beat), "--tempo-map", "--drop-at-beat", "24", "--film", str(film)])
        assert isinstance(r, SystemExit) and "drop" in str(r.code) and lean.score_of(film)["music"] == m, r



def test_an_ambiguous_tempo_takes_the_octave_nearest_the_film():
    # broke: Linden's own 100 BPM read as 200 and was mapped at 18 frames a beat, halving the film without a word
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "linden"
        quiet(lean.main, ["new", str(film), "--like", "linden"])          # 36 frames a beat, 100 BPM
        track = Path(tmp) / "t.wav"
        clicks(track, 100.0, seconds=30.0)
        read = {"bpm": 200.0, "offset_s": 0.25, "drops": [], "grid_strength": 0.6, "flags": ["alternative tempo within 10%: ambiguous"],
                "residual_ms": {"median": 1.0, "p90": 2.0}, "duration_s": 30.0}
        with patch.object(tempo_map, "analyse_file", lambda *a, **k: (read, 1)):
            r, out = quiet(lean.main, ["audio", str(track), "--tempo-map", "--film", str(film)])
        m = lean.score_of(film)["music"]
        assert r == 0 and m["fb"] == 36 and m["octave"] and "100.00" in m["octave"], (r, m)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("audio fault checks passed")
