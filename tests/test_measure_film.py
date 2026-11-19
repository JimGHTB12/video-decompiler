#!/usr/bin/env python3
"""tools/measure_film.py on a film with no voice (a test pattern over a steady tone): it used to save measures.json and
then crash writing REPORT.md, formatting a gap level that a film with no words doesn't have. Both files must be written.
And a film whose words could not be transcribed (no transcriber, or no model for it on this machine) is "not
transcribed", its word measures unknown, never a film with no voice: a spoken reference was measured as silent.

  python tests/test_measure_film.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"


def test_a_film_with_no_voice_gets_its_report():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        film, out = Path(tmp) / "novoice.mp4", Path(tmp) / "m"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3", "-f", "lavfi",
                        "-i", "sine=frequency=330:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(film)], check=True)
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure_film.py"), str(film), str(out), "--no-voice"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        assert p.returncode == 0, (p.stdout + p.stderr)[-1500:]
        assert json.loads((out / "measures.json").read_text(encoding="utf-8"))["probe"]["duration"] > 2.5
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        m = json.loads((out / "measures.json").read_text(encoding="utf-8"))
        assert m["A_time"]["changes_during_voice"] == 0 and m["A_time"]["words"] == 0, f"told no voice: no words, no change during speech: {m['A_time']}"
        assert m["voice"] == "no voice (--no-voice)", m["voice"]
        assert "## A. Time" in report and "gaps none" in report.replace("gaps none dBFS", "gaps none"), report[:800]
        # C2: measure and see ran in this process; measure's own beat sheets are left out, and its measure.json is the
        # one measure.py writes but for those sheets; --skip-tools then reuses both without running them again
        vd = json.loads((out / "vd" / "measure.json").read_text(encoding="utf-8"))
        assert vd["sheets"] == [] and not list((out / "vd").glob("beats-*.jpg")), vd["sheets"]
        cli = Path(tmp) / "cli"
        subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure.py"), str(film), "--out", str(cli)], check=True, capture_output=True)
        whole = json.loads((cli / "measure.json").read_text(encoding="utf-8"))
        assert whole.pop("sheets") and {**vd, "sheets": None} == {**whole, "sheets": None}
        stamps = {p: p.stat().st_mtime_ns for p in (out / "vd" / "measure.json", out / "see" / "motion.json")}
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure_film.py"), str(film), str(out), "--no-voice", "--skip-tools"], capture_output=True, text=True, timeout=600)
        assert p.returncode == 0 and all(f.stat().st_mtime_ns == t for f, t in stamps.items()), (p.stderr[-500:], stamps)
        # the same film where no transcriber can run (its model is not in this Hugging Face cache): unknown, not none
        empty = Path(tmp) / "hub"
        empty.mkdir()
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "measure_film.py"), str(film), str(Path(tmp) / "u")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, env={**os.environ, "HF_HUB_CACHE": str(empty)})
        assert p.returncode == 0, (p.stdout + p.stderr)[-1500:]
        m = json.loads((Path(tmp) / "u" / "measures.json").read_text(encoding="utf-8"))
        # which of the two reasons depends on this Python: the transcriber is optional (requirements.txt leaves it out),
        # so a machine set up as the README says has none, and one that has it finds no model in the empty cache
        try:
            import faster_whisper  # noqa: F401
            why = str(empty)
        except ImportError:
            why = "faster_whisper is not installed"
        assert m["voice"].startswith("not transcribed: ") and why in m["voice"], m["voice"]
        assert all(m["A_time"][k] is None for k in ("words", "changes_during_voice", "changes_in_sentence_gap", "sentence_gaps")), m["A_time"]
        assert m["E_sound"]["gap_seconds"] is None and "not transcribed" in p.stderr, (m["E_sound"], p.stderr[-500:])
        assert not (Path(tmp) / "u" / "words.json").exists(), "no words are cached for a film nobody transcribed"
        assert "words not transcribed" in (Path(tmp) / "u" / "REPORT.md").read_text(encoding="utf-8")


def test_measure_gives_no_voice_to_every_film_and_measures_again_once_it_can_hear():
    sys.path.insert(0, str(TOOLS))
    import lean
    from unittest.mock import patch
    asked = []
    m = {"A_time": {"shots": 3, "words": None}, "voice": "not transcribed: faster_whisper is not installed in this Python"}

    class A:
        film, target, against, bare, no_voice = None, "ours.mp4", "ref.mp4", "bare.mp4", True
    with tempfile.TemporaryDirectory() as tmp, patch.object(lean, "OUTROOT", Path(tmp) / "out"), \
            patch.object(lean, "measures_of", lambda f, no_voice=False: asked.append((f, no_voice)) or (m, Path(tmp) / "m.json")):
        a = A()
        a.target = str(Path(tmp) / "ours.mp4")
        lean.cmd_measure(a)
        gap = Path(a.target).with_suffix(".gap.md").read_text(encoding="utf-8")
    assert asked == [(a.target, True), ("ref.mp4", True), ("bare.mp4", True)], f"--no-voice reaches the reference and the bare pass: {asked}"
    assert gap.count("words not transcribed (faster_whisper is not installed") == 3 and "not read as no voice" in gap, gap[:600]
    assert "A_time.words" not in lean.leaves(m), "an unknown word count is no number in a gap table"
    # a cached measure made with no transcriber is measured again only once one is here
    with tempfile.TemporaryDirectory() as tmp:
        film = Path(tmp) / "f.mp4"
        film.write_bytes(b"film")
        import hashlib
        cached = Path(tmp) / "cache" / hashlib.sha1(b"film").hexdigest()[:16]
        cached.mkdir(parents=True)
        ran = []

        class Done:
            returncode, stdout = 0, ""

        import measure as measure_py
        import see
        now = {"measure": measure_py.VERSION, "see": see.VERSION}

        def measure(args, **k):
            ran.append(1)
            (cached / "measures.json").write_text(json.dumps({"voice": "transcribed", "versions": now}), encoding="utf-8")
            return Done()
        for here, again in (("faster_whisper is not installed in this Python", False), (None, True)):
            (cached / "measures.json").write_text(json.dumps({**m, "versions": now}), encoding="utf-8")
            ran.clear()
            with patch.object(lean, "transcriber", lambda: here), patch.object(lean, "run", measure):
                got, _ = lean.measures_of(film, cache_root=Path(tmp) / "cache")
            assert bool(ran) == again and (got["voice"] == "transcribed") == again, (here, ran, got)
        # broke: a cache made by an earlier measure.py (whose tempo read 240 for 120 BPM) was compared with new measures
        for old in ({**now, "measure": now["measure"] - 1}, None):
            (cached / "measures.json").write_text(json.dumps({**m, "versions": old}), encoding="utf-8")
            ran.clear()
            with patch.object(lean, "transcriber", lambda: "faster_whisper is not installed in this Python"), patch.object(lean, "run", measure):
                got, _ = lean.measures_of(film, cache_root=Path(tmp) / "cache")
            assert ran and got["versions"] == now, f"a measure made by other code ({old}) is made again: {ran} {got}"


def test_false_hearings_and_sparse_words_are_no_voice():
    sys.path.insert(0, str(TOOLS))
    import measure_film
    heard = [{"w": "Thank", "t0": 14.0, "t1": 14.2}, {"w": "you", "t0": 14.2, "t1": 14.4}, {"w": "for", "t0": 14.4, "t1": 14.5}, {"w": "watching!", "t0": 14.5, "t1": 15.0}]
    assert measure_film.no_voice(heard, 15.6), "piano heard as a subtitle's sign-off is no voice"
    sparse = [{"w": "storm", "t0": 3.0, "t1": 3.4}, {"w": "light", "t0": 3.4, "t1": 3.8}]
    assert measure_film.no_voice(sparse, 15.6), "two words in fifteen seconds with no sentence gap is no voice"
    spoken = [{"w": w, "t0": i * 0.3, "t1": i * 0.3 + 0.25} for i, w in enumerate("count the seconds and you know how far away it struck".split())]
    assert measure_film.no_voice(spoken, 3.5) is None, "a real line is a voice"
    # a music film heard as a whole YouTube sign-off, twice: 30 words, 1.36 a second, let through by the short list
    signoff = "Thank you so much for watching this video, and I'll see you in the next one. Thank you for watching this video, and I'll see you in the next one."
    heard = [{"w": w, "t0": 3 + i * 0.7, "t1": 3 + i * 0.7 + 0.5} for i, w in enumerate(signoff.split())]
    assert "sign-offs" in (measure_film.no_voice(heard, 47.7) or ""), "a sign-off said whole is no voice"
    near = [{"w": w, "t0": i * 0.3, "t1": i * 0.3 + 0.25} for i, w in enumerate("Thank you for coming. I'll see you in the next meeting about the budget.".split())]
    assert measure_film.no_voice(near, 5.0) is None, "a real line that shares a sign-off's words is a voice"


def test_the_frame_measures_and_sync_chances_are_the_old_numbers():
    # C3: whole-number flat blocks and distances, family tables, and every sync trial at once must give the numbers the
    # float and loop versions gave, here on blocks built on each spread threshold and pixels on the distance line
    import numpy as np
    sys.path.insert(0, str(TOOLS))
    import cv2
    import measure_film as mf
    rng = np.random.default_rng(5)
    B = mf.FLAT_BLOCK

    def old_flat(rgb):
        h, w = rgb.shape[0] // B * B, rgb.shape[1] // B * B
        x = rgb[:h, :w].astype(np.float32).reshape(h // B, B, w // B, B, 3)
        sd = x.std(axis=(1, 3)).max(axis=-1)
        return {t: float((sd < t).mean()) for t in (1.5, mf.FLAT_STD, 6.0)}
    # blocks whose spread is each threshold exactly (half the block a, half a + 2t), just under and just over
    tiles = []
    for t in (1.5, mf.FLAT_STD, 6.0):
        for step in (2 * t, 2 * t - 1, 2 * t + 1):
            for a in (0, 100, 250 - int(step)):
                blk = np.full((B, B, 3), a, np.uint8)
                blk[:, B // 2:] = a + int(step) if float(step).is_integer() else a
                tiles.append(blk)
    tiles += [rng.integers(0, 256, (B, B, 3)).astype(np.uint8) for _ in range(20)]
    tiles += [(100 + rng.integers(-k, k + 1, (B, B, 3))).astype(np.uint8) for k in (1, 2, 3, 6, 9, 12) for _ in range(5)]
    while len(tiles) % 10:
        tiles.append(np.zeros((B, B, 3), np.uint8))
    frame = np.concatenate([np.concatenate(tiles[r:r + 10], axis=1) for r in range(0, len(tiles), 10)], axis=0)
    assert mf.flat_share(frame) == old_flat(frame), (mf.flat_share(frame), old_flat(frame))
    # the distance line: pixels at FG_DIST from the ground and one either side
    bgv = np.array([16, 48, 80])
    px = np.zeros((40, 64, 3), np.uint8) + bgv.astype(np.uint8)
    for k, dv in enumerate((mf.FG_DIST - 1, mf.FG_DIST, mf.FG_DIST + 1)):
        px[k * 10:(k + 1) * 10, 32:, 0] = bgv[0] + dv
    old_fg = (np.linalg.norm(px.astype(np.float32) - bgv.astype(np.float32), axis=-1) > mf.FG_DIST)
    d = px.astype(np.int32) - bgv
    assert np.array_equal(old_fg, (d * d).sum(axis=-1) > mf.FG_DIST * mf.FG_DIST)
    # families from tables: every hue and value
    hsv = np.stack(np.meshgrid(np.arange(180), np.arange(256), indexing="ij"), -1).reshape(-1, 2)
    h = hsv[:, 0].astype(np.uint8)
    v = hsv[:, 1].astype(np.uint8)
    assert np.array_equal(mf.HUE_FAMILY[h], (h.astype(int) * 2 // 30) % 12) and np.array_equal(mf.GREY_FAMILY[v], 12 + np.digitize(v, [70, 190]))
    # sync trials: each share the loop's, with times on the tolerance and on onsets
    import measure
    onsets = [0.5, 1.0, 1.0, 2.25, 7.0]
    events = [0.5 + 0.12, 1.0 - 0.12, 2.25, 3.0, 6.88, 9.99]
    for tol in (0.12, 1 / 30, 0.0):
        o = np.array(onsets)
        near = lambda ts: float(np.mean([np.min(np.abs(o - t)) <= tol for t in ts]))
        r1, r2 = np.random.default_rng(0), np.random.default_rng(0)
        assert float(measure.near_shares(onsets, events, tol)) == near(events)
        assert measure.chance_shares(events, onsets, 10.0, tol, r1, 500) == float(np.mean([near((np.array(events) + r2.uniform(0, 10.0)) % 10.0) for _ in range(500)]))


def test_a_file_with_no_sound_stream_is_not_queued_for_the_transcriber():
    # C6: a file with no sound stream holds no speech; the transcriber took the render queue and loaded a 400 MB model
    # to hear nothing, and where it was missing the film read "not transcribed"
    from unittest.mock import patch
    sys.path.insert(0, str(TOOLS))
    import measure_film as mf
    import raea_run
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(raea_run, "one_at_a_time", lambda *a, **k: (_ for _ in ()).throw(AssertionError("took the queue"))), \
            patch.object(mf, "transcriber", lambda: "faster-whisper is not installed"):
        ws, how = mf.words_of(Path(tmp) / "silent.mp4", Path(tmp), has_audio=False)
        assert ws == [] and how == mf.TRANSCRIBED and (Path(tmp) / "words.json").read_text(encoding="utf-8") == "[]", (ws, how)
    assert "cv2" not in subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{TOOLS}'); import measure_film; print(sorted(sys.modules))"],
                                       capture_output=True, text=True).stdout, "importing measure_film for no_voice loads no OpenCV"


if __name__ == "__main__":
    sys.path.insert(0, str(TOOLS))
    import utf8  # noqa: F401
    test_false_hearings_and_sparse_words_are_no_voice()
    print("ok test_false_hearings_and_sparse_words_are_no_voice")
    test_a_film_with_no_voice_gets_its_report()
    print("ok test_a_film_with_no_voice_gets_its_report")
    test_measure_gives_no_voice_to_every_film_and_measures_again_once_it_can_hear()
    print("ok test_measure_gives_no_voice_to_every_film_and_measures_again_once_it_can_hear")
    test_the_frame_measures_and_sync_chances_are_the_old_numbers()
    print("ok test_the_frame_measures_and_sync_chances_are_the_old_numbers")
    test_a_file_with_no_sound_stream_is_not_queued_for_the_transcriber()
    print("ok test_a_file_with_no_sound_stream_is_not_queued_for_the_transcriber")
