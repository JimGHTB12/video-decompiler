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


if __name__ == "__main__":
    sys.path.insert(0, str(TOOLS))
    import utf8  # noqa: F401
    test_false_hearings_and_sparse_words_are_no_voice()
    print("ok test_false_hearings_and_sparse_words_are_no_voice")
    test_a_film_with_no_voice_gets_its_report()
    print("ok test_a_film_with_no_voice_gets_its_report")
    test_measure_gives_no_voice_to_every_film_and_measures_again_once_it_can_hear()
    print("ok test_measure_gives_no_voice_to_every_film_and_measures_again_once_it_can_hear")
