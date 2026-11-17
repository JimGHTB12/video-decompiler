#!/usr/bin/env python3
"""tools/pack.py with small planted films of known colour and known motion. The pack is a line-up of up to four films
under letters (lineup/A..D) and ours alone (alone/). Each film in the line-up gets its story at two frames a second (6 x 4
tiles a sheet) and its K every-frame stretches; the letters are dealt anew for each pack number and the same when that
number is made again, and ours never keeps its letter from the pack before. alone/ has ten stretches by default and five
full-size keys. The key file sits outside the pack; the --against films' material is made once and reused; --ref-first and
--ref-last trim them, either alone too; no film's name is in any file inside a pack, nor anywhere in the pack's own path
(it is made under a neutral root with a random name; the key is under the film's own folder). A burst of motion in a known second is among the
stretches picked, in a pack and in vd pin.

  python tests/test_pack.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))
import pack  # noqa: E402
import sheet  # noqa: E402
from PIL import Image  # noqa: E402
from test_scan import film as moving_film  # noqa: E402  the scan's own planted films


def film(path, colour, seconds):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r=24:d={seconds}", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def mean_colour(sheet):
    with Image.open(sheet) as im:
        im = im.convert("RGB").crop((40, 40, 380, 200))   # inside the first tile, clear of its time label
        return tuple(sum(c) / len(c) for c in zip(*im.getdata()))


def colour_of(sheet):
    r, g, b = mean_colour(sheet)
    return "white" if min(r, g, b) > 200 else "red" if r > 150 and g < 80 and b < 80 else "green" if g > 100 and r < 80 and b < 80 else \
        "blue" if b > 150 and r < 80 else f"{r:.0f},{g:.0f},{b:.0f}"


def burst(path, fps=30, seconds=8, at=5.0):
    """Slow drift, and one second of fast motion from `at`."""
    a, b = int(at * fps), int((at + 1) * fps)
    clock = lambda f: 0.15 * f if f < a else 0.15 * a + 4 * (f - a) if f < b else 0.15 * a + 4 * (b - a) + 0.15 * (f - b)
    return moving_film(path, fps, seconds, clock=clock)


def key_lines(key):
    return {l.split(" = ")[0]: l for l in key.read_text(encoding="utf-8").splitlines() if " = " in l}


def test_a_lineup_of_four_films_under_dealt_letters():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ours = film(tmp / "ours.mp4", "red", 13)
        refs = [film(tmp / "ref.mp4", "blue", 30), film(tmp / "good.mp4", "green", 7), film(tmp / "earlier.mp4", "white", 3)]
        out, cache, reads = tmp / "out", tmp / "cache", tmp / "reads"
        p, key, letters = pack.make(ours, refs, out, cache_root=cache, reads_root=reads)
        assert p.parent == reads and key == out / "pack-1-KEY.txt" and sorted(x.name for x in p.iterdir()) == ["alone", "lineup"], list(p.iterdir())
        assert sorted(letters) == ["A", "B", "C", "D"] and sorted(x.name for x in (p / "lineup").iterdir()) == ["A", "B", "C", "D"]
        sheets = {"ours.mp4": 2, "ref.mp4": 3, "good.mp4": 1, "earlier.mp4": 1}   # 13 s, 30 s, 7 s, 3 s at 2 a second, 24 tiles a sheet
        colours = {"ours.mp4": "red", "ref.mp4": "blue", "good.mp4": "green", "earlier.mp4": "white"}
        for letter, f in letters.items():
            story = sorted((p / "lineup" / letter).glob("story-*.jpg"))
            assert len(story) == sheets[f.name], f"{letter} ({f.name}): {len(story)} story sheets, not {sheets[f.name]}"
            assert colour_of(story[0]) == colours[f.name], f"{letter} holds {f.name}: {colour_of(story[0])}"
            with Image.open(story[0]) as im:
                assert im.size == (2400, 4 * (225 + pack.STRIP)), "every film the same way: 6 x 4 tiles of 400 x 225, each under its time"
                corner = im.convert("RGB").getpixel((3, pack.STRIP + 3))
                assert sum(im.convert("RGB").getpixel((60, 20))) < 60 and max(corner) > 100, f"the time is in a band above the tile, not on its corner: {corner}"
        assert all(f.suffix == ".jpg" for f in (p / "lineup").rglob("*.*")), "the line-up holds sheets and nothing else"
        assert not list((p / "lineup").rglob("move-*.jpg")), "a film that never changes has no stretch of motion to show"
        said = key_lines(key)
        assert key.parent == out and p not in key.parents and str(p) in key.read_text(encoding="utf-8"), "the key is outside the pack, and says where it is"
        for letter, f in letters.items():
            assert f.name in said[f"lineup/{letter}"] and (("ours" in said[f"lineup/{letter}"]) == (f.name == "ours.mp4")), said
        assert "stretches from" in said["alone/"] and "keys at" in said["alone/"], said
        # alone: ours, its story and five keys (no stretches in a film that never changes)
        al = sorted(x.name for x in (p / "alone").iterdir())
        assert [n for n in al if n.startswith("story-")] == ["story-01.jpg", "story-02.jpg"] and len([n for n in al if n.startswith("key-")]) == 5, al
        assert colour_of(p / "alone" / "story-01.jpg") == "red"
        made = sorted(cache.glob("*/reader-all-all-k5/story-*.jpg"))
        assert len(made) == 3 + 1 + 1, "the three --against films' sheets are kept beside their measures"
        stamp = made[0].stat().st_mtime
        # pack 2: the letters are dealt again, and ours does not keep its letter; the cache is reused
        p2, key2, letters2 = pack.make(ours, refs, out, cache_root=cache, reads_root=reads)
        mine = lambda ls: next(l for l, f in ls.items() if f.name == "ours.mp4")
        assert key2 == out / "pack-2-KEY.txt" and p2 != p and p2.parent == reads and mine(letters2) != mine(letters), (letters, letters2)
        assert made[0].stat().st_mtime == stamp, "a second pack reuses them, made by the same code"
        # pack 2 made again deals the same letters
        shutil.rmtree(p2)
        key2.unlink()
        p2b, key2b, again = pack.make(ours, refs, out, cache_root=cache, reads_root=reads)
        assert key2b == key2 and {l: f.name for l, f in again.items()} == {l: f.name for l, f in letters2.items()}, (letters2, again)
        assert pack.deal(7, 4) == pack.deal(7, 4) and all(pack.deal(n, c)[0] != pack.deal(n + 1, c)[0] for c in (2, 3, 4) for n in range(1, 20))
        # two films: two letters
        p3, _, two = pack.make(ours, refs[:1], out, cache_root=cache, reads_root=reads)
        assert sorted(two) == ["A", "B"] and sorted(x.name for x in (p3 / "lineup").iterdir()) == ["A", "B"]
        # trimmed: the first 2 s and last 2 s of each --against film: 8 tiles, one sheet
        p4, key4, trimmed = pack.make(ours, refs[:1], out, ref_first=2, ref_last=2, key_times=[1.0, 2.0], cache_root=cache, reads_root=reads)
        ref_letter = next(l for l, f in trimmed.items() if f.name == "ref.mp4")
        assert len(list((p4 / "lineup" / ref_letter).glob("story-*.jpg"))) == 1 and len(list((p4 / "alone").glob("key-*.png"))) == 2
        assert "only its first 2 s and last 2 s" in key_lines(key4)[f"lineup/{ref_letter}"]
        # either end alone: the first 2 s (4 tiles), or the last 3 s (6 tiles); each made, and said in the key
        for first, last, said in ((2, None, "only its first 2 s)"), (None, 3, "only its last 3 s)")):
            p5, key5, one = pack.make(ours, refs[:1], out, ref_first=first, ref_last=last, key_times=[1.0], cache_root=cache, reads_root=reads)
            ref_letter = next(l for l, f in one.items() if f.name == "ref.mp4")
            assert len(list((p5 / "lineup" / ref_letter).glob("story-*.jpg"))) == 1, list((p5 / "lineup" / ref_letter).iterdir())
            assert said in key_lines(key5)[f"lineup/{ref_letter}"], key_lines(key5)
        try:
            pack.make(ours, refs + refs[:1], out, cache_root=cache, reads_root=reads)
            raise AssertionError("five films are refused")
        except SystemExit as e:
            assert "up to 3" in str(e), e


def test_each_story_tile_shows_the_frame_at_its_label():
    # broke: ffmpeg's fps filter keeps the last frame of each half second centred on a tick, so the tile labelled 31.00 s
    # showed the frame at 31.167 (and 0.00 showed 0.208): a cut read off a story tile was read in the wrong shot
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "count.mp4"
        frames = np.stack([np.full((36, 64), 3 * i, np.uint8) for i in range(72)])        # 3 s at 24 fps, frame i at grey 3i
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "64x36", "-r", "24", "-i", "-",
                        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(clip)], input=frames.tobytes(), check=True)
        for start in (0.0, 0.5):
            for t, im in pack.tiles(clip, start=start):
                shown = round(float(np.asarray(im.convert("L")).mean()) / 3)
                assert shown == int(t * 24 + 1e-6), f"the tile labelled {t:.2f} s shows the frame at {shown / 24:.3f} s"


def test_ours_alone_has_ten_stretches_and_no_lineup_without_against():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ours = burst(tmp / "ours.mp4", fps=30, seconds=15, at=9.0)
        p, key, letters = pack.make(ours, [], tmp / "out", cache_root=tmp / "cache", reads_root=tmp / "reads")
        assert letters == {} and sorted(x.name for x in p.iterdir()) == ["alone"], "with no --against, only alone/"
        moves = sorted((p / "alone").glob("move-*.jpg"), key=lambda f: int(f.stem.split("-")[1]))
        assert [f.name for f in moves] == [f"move-{i}.jpg" for i in range(1, 11)], f"ten stretches by default: {moves}"
        starts = [float(t) for t in key_lines(key)["alone/"].split("stretches from ")[1].split(" s")[0].split(", ")]
        assert len(starts) == 10 and starts == sorted(starts) and any(abs(t - 9.0) <= 2 / 30 for t in starts), starts
        assert all(y - x >= 1.0 - 1e-9 for x, y in zip(starts, starts[1:])), f"not overlapping: {starts}"
        for f in moves:
            with Image.open(f) as im:
                im.verify()


def test_the_busiest_second_is_given_frame_by_frame_and_no_name_is_in_the_pack():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ours = burst(tmp / "plusoneourcut.mp4", fps=30, at=5.0)
        refs = [burst(tmp / "studioreference.mp4", fps=60, seconds=6, at=2.0), burst(tmp / "knowngoodfilm.mp4", fps=30, seconds=5, at=1.0)]
        # the key goes where vd pack puts it, under the film's own output folder, which is named after it
        p, key, letters = pack.make(ours, refs, tmp / "out" / "plusoneourcut", cache_root=tmp / "cache", k=3, k_alone=4, reads_root=tmp / "reads")
        for letter, f in letters.items():
            moves = sorted((p / "lineup" / letter).glob("move-*.jpg"))
            assert [m.name for m in moves] == ["move-1.jpg", "move-2.jpg", "move-3.jpg"], (f.name, moves)
            for m in moves + sorted((p / "lineup" / letter).glob("story-*.jpg")):
                with Image.open(m) as im:
                    im.verify()                                         # a picture a reader can open
        mine = next(l for l, f in letters.items() if f.name == "plusoneourcut.mp4")
        said = key_lines(key)[f"lineup/{mine}"]
        starts = [float(t) for t in said.split("stretches from ")[1].split(" s")[0].split(", ")]
        assert any(abs(t - 5.0) <= 2 / 30 for t in starts) and starts == sorted(starts), f"the burst at 5 s is among ours, in time order: {starts}"
        k = starts.index(min(starts, key=lambda t: abs(t - 5.0))) + 1
        with Image.open(p / "lineup" / mine / f"move-{k}.jpg") as im:
            assert im.size == (8 * 320, 4 * (180 + sheet.STRIP)), "its 30 frames, every one, 8 to a row, each under its time and frame"
        theirs = next(l for l, f in letters.items() if f.name == "studioreference.mp4")
        with Image.open(p / "lineup" / theirs / "move-1.jpg") as im:
            assert im.size == (8 * 320, 8 * (180 + sheet.STRIP)), "a film at 60 a second: 60 frames, 8 x 8"
        ref_said = key_lines(key)[f"lineup/{theirs}"]
        assert any(abs(float(t) - 2.0) <= 2 / 60 for t in ref_said.split("stretches from ")[1].split(" s")[0].split(", ")), ref_said
        assert len(list((p / "alone").glob("move-*.jpg"))) == 4, "--k-alone sets alone/'s count"
        # no film's name anywhere in a path a reader is given (the whole path, its parents too), nor in a file's bytes
        names = ("plusoneourcut", "studioreference", "knowngoodfilm")
        inside = list(p.rglob("*"))
        assert not [f for f in [p, *inside] if any(n in str(f).lower() for n in names)], [p, *inside]
        assert not any(n.encode() in f.read_bytes().lower() for f in inside if f.is_file() for n in names), "nor in any file's bytes"
        assert all(n in key.read_text(encoding="utf-8") for n in names), "the key file, outside, names them all"


def test_a_makers_packs_deal_ours_a_new_letter_each_time():
    # a maker packed cut 1 against a reference, exported cut 2, and packed it against the reference and cut 1: ours was A
    # both times. The rule held only between packs of the same count (3 films, then 4: A and A), and a pack started outside
    # the film's folder was keyed by the file's own name, so a cut's pack began again at pack 1
    import json
    import lean
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        refs = [film(tmp / "ref.mp4", "blue", 3), film(tmp / "good.mp4", "green", 2)]
        for start in (1, 2):                                 # 2 films then 3, and 3 films then 4
            for inside in (True, False):
                name = f"f{start}{'in' if inside else 'out'}"
                d = tmp / name
                d.mkdir()
                (d / "score.json").write_text(json.dumps({"fps": 24, "width": 320, "height": 180, "duration": 2.0}), encoding="utf-8")
                out = tmp / "out" / name
                (out / "cuts").mkdir(parents=True)
                ours = []
                with patch.object(lean, "OUTROOT", tmp / "out"), patch.object(pack, "READS", tmp / "reads"), patch.object(Path, "cwd", lambda: d if inside else tmp):
                    for n in (1, 2, 3):
                        cut = film(out / "cuts" / f"{name}-cut{n}.mp4", ("red", "white", "yellow")[n - 1], 2)    # vd export: cut n, and NAME.mp4 the latest
                        shutil.copy2(cut, out / f"{name}.mp4")
                        against = refs[:start] + ([str(out / "cuts" / f"{name}-cut{n - 1}.mp4")] if n > 1 else [])
                        target = out / f"{name}.mp4" if n != 2 else cut    # the latest by either of its names
                        assert lean.main(["pack", str(target), *[x for r in against for x in ("--against", str(r))]]) == 0
                        key = out / f"pack-{n}-KEY.txt"
                        assert key.is_file(), f"{name}: every pack's key is in the film's own folder: {sorted(out.iterdir())}"
                        ours.append(next(l for l in key_lines(key) if key_lines(key)[l].split(" = ")[1].startswith("ours"))[len("lineup/"):])
                assert ours[0] != ours[1] and ours[1] != ours[2], f"{name}: ours was dealt {ours}"


def test_two_trims_of_one_reference_keep_two_timing_notes():
    # a review's finding: the note of a cached trim was named with with_suffix, which cut "reader-1.5-all-k5" at its
    # point, so --ref-first 1.5 and --ref-first 1.7 shared "reader-1.times" and one was told the other's times
    with tempfile.TemporaryDirectory() as tmp:
        notes = set()
        for first in (1.5, 1.7):
            folder = Path(tmp) / f"reader-{first}-all-k5"
            folder.mkdir()
            (folder.with_name(folder.name + ".times")).write_text(f"{first:.4f}", encoding="utf-8")
            assert pack.stretch_times(folder, "no-film-needed.mp4", 5) == [first], "each trim reads its own note"
            notes.add(folder.name + ".times")
        assert len(notes) == 2 and len(list(Path(tmp).glob("*.times"))) == 2


def test_pin_gives_the_pinned_film_to_take_apart():
    # H: vd pin measured the reference, and the maker had to build a sheet of it with ffmpeg to see it
    import lean
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ref = burst(tmp / "ref.mp4", fps=60, seconds=7, at=3.0)
        got = lean.pin_material(ref, tmp / "out", cache_root=tmp / "cache", k=2)
        assert got == tmp / "out" / "pin", got
        story, moving = sorted(got.glob("story-*.jpg")), sorted(got.glob("move-*.jpg"))
        with Image.open(story[0]) as im:
            assert len(story) == 1 and im.size == (2400, 4 * (225 + pack.STRIP)), "7 s at 2 a second: 14 tiles, laid out as vd pack lays out ours"
        assert [f.name for f in moving] == ["move-1.jpg", "move-2.jpg"], moving
        src = next(f for f in (tmp / "cache").glob("*/reader-all-all-k2") if f.is_dir())
        import scan
        assert any(abs(t - 3.0) <= 2 / 60 for t in scan.windows(ref, 60, 2)), "the picked stretch holds the burst"
        assert sorted(f.name for f in src.iterdir()) == sorted(f.name for f in story + moving), "made by vd pack's own code, cached"
        assert [f.name for f in sorted(got.glob("key-*.jpg"))] == [f"key-{i}.jpg" for i in range(1, 7)], "and six frames at rest, full size"
        assert lean.pin_material(tmp / "measures.json", tmp / "out") is None


if __name__ == "__main__":
    import utf8  # noqa: F401
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
