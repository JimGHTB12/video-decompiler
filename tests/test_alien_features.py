#!/usr/bin/env python3
"""The newer commands, none proven on a film, each run once on a clean input or a small planted one (their planted-fault
tests are in test_new_check_faults.py, test_audio_faults.py and test_bridge_capture_faults.py):
  vd borrow (fitted moves and colours), vd capture and vd launch (a repository's counts as a plane), vd foley (a track made
  by rule from the film's code), vd look's two pixel checks, vd evolve (four sketches as a blind line-up), vd playable (a
  browser imitation of the film), vd scan's flash check, vd audio, vd bridge, and vd.py routing every command.
"""
import json
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "video-decompiler"
TOOLS = SKILL / "tools"
sys.path.insert(0, str(TOOLS))

import evolve  # noqa: E402
import foley  # noqa: E402
import lean  # noqa: E402
import look  # noqa: E402
import playable  # noqa: E402
import puppet  # noqa: E402
import borrow  # noqa: E402


def test_look_raycasts_weber_contrast_and_saccade_jumps():
    W, H = 1920, 1080
    # 1. Figure-ground collision: white serif text crossing a bright, high-edge-crowding photographic patch
    busy_rgb = np.full((H, W, 3), 235, dtype=np.uint8)
    # Create a busy checkerboard/texture in and around the text box [x=1200, y=760, w=500, h=80] so Sobel edge crowding is high and Weber contrast is low
    yy, xx = np.mgrid[740:860, 1180:1720]
    busy_rgb[740:860, 1180:1720] = np.where(((xx // 2 + yy // 2) % 2)[..., None] == 0, 244, 218).astype(np.uint8)
    t_bad = {
        "text": "Museum Archive 1924",
        "box": [1200, 760, 500, 80],
        "size": 56.0,
        "color": [1.0, 1.0, 1.0, 1.0],
        "opacity": 1.0,
    }
    # without raea's layer mask the letters can't be told from the ground, so nothing is said (test_new_check_faults)
    assert look.contrast_note(t_bad, busy_rgb, W, H) is None
    # with it (a picture layer frontmost everywhere but under the letters, here none drawn), the busy ground is caught
    fault = look.contrast_note(t_bad, busy_rgb, W, H, image_mask_2d=np.ones((270, 480), dtype=bool))
    assert fault is not None and fault.kind == "contrast", f"expected figure-ground contrast fault, got {fault}"
    assert "Weber" in str(fault), str(fault)

    # Clean dark ground under the same white text passes without fault
    clean_rgb = np.full((H, W, 3), 18, dtype=np.uint8)
    clean_rgb[775:825, 1220:1680] = 248
    assert look.contrast_note(t_bad, clean_rgb, W, H) is None

    # 1b. Regression for Test 5: dark charcoal serif text ('rgb(29, 26, 22)') partially crossing a dark textured photo
    # with RAEALAYR image_mask_2d, and multiple text nodes sharing the same helper `loc` ("kit/core.tsx:51:3")
    pizza_rgb = np.full((H, W, 3), 244, dtype=np.uint8)
    py_grid, px_grid = np.mgrid[560:680, 440:680]
    pizza_rgb[560:680, 440:680] = np.where(((px_grid // 3 + py_grid // 3) % 2)[..., None] == 0, 18, 52).astype(np.uint8)
    img_mask = np.zeros((270, 480), dtype=bool)
    img_mask[140:170, 110:170] = True
    t_dark1 = {"text": "Chicken", "box": [460, 579, 684, 84], "size": 116.0, "color": "rgb(29, 26, 22)", "opacity": 1.0, "loc": "kit/core.tsx:51:3", "index": "tn0", "lines": 1}
    t_dark2 = {"text": "& spinach pizza", "box": [460, 662, 684, 84], "size": 116.0, "color": "rgb(29, 26, 22)", "opacity": 1.0, "loc": "kit/core.tsx:51:3", "index": "tn1", "lines": 1}
    c_dark = look.contrast_note(t_dark1, pizza_rgb, W, H, image_mask_2d=img_mask)
    assert c_dark is not None and c_dark.kind == "contrast" and "1." in str(c_dark), c_dark
    assert t_dark1["loc"] == t_dark2["loc"], "shared helper loc regression setup"
    # Regression for Test 6 cold-run finding: text wholly occluded behind an opaque foreground panel/image (0 frontmost text pixels) is NOT flagged as contrast fault
    occluded_txt_mask = np.zeros((270, 480), dtype=bool)
    assert look.contrast_note(t_dark1, pizza_rgb, W, H, image_mask_2d=img_mask, text_mask_2d=occluded_txt_mask) is None
    # Regression for Test 6 blind-reader finding: text visible over a photograph covered by a translucent scrim `<div>` (img_mask=0, text_mask>0) IS caught!
    zero_img_mask = np.zeros((270, 480), dtype=bool)
    vis_txt_mask = np.zeros((270, 480), dtype=bool)
    vis_txt_mask[148:152, 120:145] = True
    scrim_fault = look.contrast_note(t_dark1, pizza_rgb, W, H, image_mask_2d=zero_img_mask, text_mask_2d=vis_txt_mask, all_text_mask_2d=vis_txt_mask)
    assert scrim_fault is not None and scrim_fault.kind == "contrast", scrim_fault

    # 2. Walter Murch eye-trace continuity across cuts: fixation at (1400, 800) on frame 10 -> text claim at (200, 150) on frame 11
    fd0 = {
        "frame": 10,
        "text": [{"text": "Focus right", "box": [1300, 760, 200, 80], "size": 56.0, "opacity": 1.0}],
        "elements": [],
    }
    fd1 = {
        "frame": 11,
        "text": [{"text": "Claim top-left", "box": [100, 110, 200, 80], "size": 56.0, "opacity": 1.0}],
        "elements": [],
    }
    # only across a cut: two frames that barely differ are one shot (busy -> clean is a cut)
    assert look.saccade_note(10, 11, fd0, fd1, clean_rgb, clean_rgb, W, H) is None, "the same picture twice is no cut"
    sac = look.saccade_note(10, 11, fd0, fd1, busy_rgb, clean_rgb, W, H)
    assert sac is not None and sac.kind == "saccade", f"expected saccade fault across cut, got {sac}"
    assert "45 degrees" in str(sac) and "(1400, 800)" in str(sac) and "(200, 150)" in str(sac), str(sac)

    # Adding a join.ts handover (`"join": True`) or keeping the fixation nearby suppresses the saccade fault
    fd1_joined = {**fd1, "join": True}
    assert look.saccade_note(10, 11, fd0, fd1_joined, busy_rgb, clean_rgb, W, H) is None
    fd1_near = {
        "frame": 11,
        "text": [{"text": "Claim nearby", "box": [1250, 740, 200, 80], "size": 56.0, "opacity": 1.0}],
        "elements": [],
    }
    assert look.saccade_note(10, 11, fd0, fd1_near, busy_rgb, clean_rgb, W, H) is None
    # a corner label that stays put is no hand-over for a headline jumping across the frame (it silenced the jump)
    label = {"text": "STEP 2", "box": [60, 40, 160, 40], "size": 30.0, "opacity": 1.0}
    fd0_l = {**fd0, "text": [*fd0["text"], label]}
    fd1_l = {**fd1, "text": [*fd1["text"], label]}
    assert look.saccade_note(10, 11, fd0_l, fd1_l, busy_rgb, clean_rgb, W, H) is not None

    # Verify look.report integrates both pixel-level checks when frame PNGs are present
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        p10, p11 = out_dir / "frame-00010.png", out_dir / "frame-00011.png"
        Image.fromarray(busy_rgb).save(p10)
        Image.fromarray(clean_rgb).save(p11)
        manifest = {
            "width": W,
            "height": H,
            "frames": [
                {"frame": 10, "text": [t_bad, *fd0["text"]], "elements": []},
                fd1,
            ],
        }
        (out_dir / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
        per, general = look.report(out_dir, [10, 11], 60, pngs_by_frame={10: p10, 11: p11})
        kinds = {n.kind for notes in per.values() for n in notes}
        # no layer masks in this manifest: the cut is checked, the contrast is not guessed at
    assert "saccade" in kinds and "contrast" not in kinds, (kinds, per, general)


def test_foley_reads_aliased_camera_keys_writes_outside_the_film_and_refuses_a_mix_with_no_sound():
    # broke: Onoma's camera keys written P.thunder (const P = TM.PARTS) were read as nothing, so its second half had no
    # camera sound; the trace was written into kit/ (a .json in the film, TRAPS.md); and --mix with no media/sound.wav
    # did nothing and said nothing
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "onoma-copy"
        lean.main(["new", str(d), "--like", "onoma"])
        tel = foley.extract_telemetry_from_film(d)
        late = [c.get("omega", 0) for c in tel["camera"] if c.get("f", c.get("frame", 0)) > 900]
        assert max(late) > 10, "the camera moves of the film's second half are read"
        old = lean.OUTROOT
        lean.OUTROOT = Path(tmp) / "out"
        try:
            wav, tel_path, _ = foley.run_foley(d)
            assert wav.is_file() and tel_path.parent == lean.outdir(d) and not (d / "kit" / "telemetry.gen.json").exists(), tel_path
            starter = Path(tmp) / "starter"
            lean.main(["new", str(starter), "--kind", "launch"])
            try:
                foley.run_foley(starter, mix_into_sound=True)
                raise AssertionError("--mix with no media/sound.wav to mix into made a track and said nothing")
            except SystemExit as e:
                assert "sound.wav" in str(e), e
        finally:
            lean.OUTROOT = old


def test_foley_mix_reports_the_level_it_wrote():
    # broke: over a silent media/sound.wav, --mix said "blended into media/sound.wav (-15 LUFS)" and wrote -24.7 LUFS: the
    # re-level is held to 6 dB and under -2.2 dBTP, and the note was a fixed string
    import contextlib
    import io
    import re
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "quiet-stet"
        lean.main(["new", str(d), "--like", "stet"])
        lean.write_wav(d / "media" / "sound.wav", np.zeros((int(lean.score_of(d)["duration"] * 48000), 2), np.float32))
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            assert lean.main(["foley", "--mix", "--film", str(d)]) == 0
        lufs, tp = lean.loudness(d / "media" / "sound.wav")
        m = re.search(r"media/sound\.wav[^;]*?(-?\d+(?:\.\d+)?) LUFS", said.getvalue())
        assert m and abs(float(m.group(1)) - float(lufs)) <= 0.2, ("it says the level it wrote", lufs, said.getvalue())
        assert float(lufs) < -16 and "-15 LUFS)" not in said.getvalue(), (lufs, said.getvalue())


def test_foley_synthesizes_physical_sound_from_telemetry():
    # Spectral centroid helper
    def centroid_hz(sig):
        mono = sig.mean(axis=1) if sig.ndim == 2 else sig
        freqs = np.fft.rfftfreq(len(mono), 1.0 / foley.SR)
        mag = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
        return float(np.sum(freqs * mag) / (np.sum(mag) + 1e-12))

    # 1. Heavy mass produces a deeper modal thud than a small badge mass
    heavy = foley.thud_from_mass(mass=0.55, velocity=2.0, seed=7)
    light = foley.thud_from_mass(mass=0.01, velocity=2.0, seed=7)
    assert centroid_hz(heavy) < centroid_hz(light) * 0.75, (centroid_hz(heavy), centroid_hz(light))

    # 2. Kerning-lock click panned via synthesize() pans left vs right accurately
    left_click = foley.synthesize(
        {"fps": 60, "frames": 60, "camera": [], "impacts": [{"t": 0.1, "kind": "lock", "mass": 0.005, "velocity": 1.2, "pan": -0.8}]},
        duration_s=1.0,
    )
    right_click = foley.synthesize(
        {"fps": 60, "frames": 60, "camera": [], "impacts": [{"t": 0.1, "kind": "lock", "mass": 0.005, "velocity": 1.2, "pan": 0.8}]},
        duration_s=1.0,
    )
    assert np.sum(left_click[:, 0] ** 2) > np.sum(left_click[:, 1] ** 2) * 2.5
    assert np.sum(right_click[:, 1] ** 2) > np.sum(right_click[:, 0] ** 2) * 2.5

    # 3. End-to-end `vd foley` on a copy of a worked film
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "foley-film"
        lean.main(["new", str(d), "--like", "plusone"])
        code = lean.main(["foley", "--film", str(d)])
        assert code == 0
        tel_path = lean.outdir(d) / "telemetry.gen.json"   # an output, beside the film's others, not in kit/
        wav_path = d / "media" / "foley.wav"
        assert tel_path.is_file() and wav_path.is_file()
        tel = json.loads(tel_path.read_text(encoding="utf-8"))
        assert len(tel["impacts"]) >= 4 and len(tel["camera"]) > 100
        with wave.open(str(wav_path), "rb") as w:
            assert w.getnchannels() == 2 and w.getframerate() == 48000
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767.0
        assert float(np.max(np.abs(pcm))) > 0.05, "foley wav has non-trivial physical audio energy"
        # Verify `--mix` blends the foley track into media/sound.wav while preserving -15 LUFS target
        assert lean.main(["foley", "--mix", "--film", str(d)]) == 0
        lufs, tp = lean.loudness(d / "media" / "sound.wav")
        assert lufs is not None and abs(float(lufs) - (-15.0)) <= 1.2 and float(tp) < -1.0, (lufs, tp)


def test_borrow_compiles_motion_dna_cartridge():
    ref_mp4 = ROOT / "docs" / "media" / "stet.mp4"
    assert ref_mp4.is_file(), f"missing sample video {ref_mp4}"
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / "sample-repo"
        repo_dir.mkdir()
        (repo_dir / "README.md").write_text("# SampleEngine\nDeterministic sub-millisecond stream compiler.\n", encoding="utf-8")
        (repo_dir / "engine.py").write_text("def compile_stream(x):\n    return x * 2\n", encoding="utf-8")
        out_film = Path(tmp) / "borrowed-film"
        try:
            lean.main(["borrow", str(ref_mp4), "-o", str(out_film), "--k", "2"])
            raise AssertionError("borrow made a new film folder without being told which worked film to copy")
        except SystemExit as e:
            assert "--like" in str(e) and not out_film.exists(), e
        code = lean.main(["borrow", str(ref_mp4), "--for", str(repo_dir), "-o", str(out_film), "--k", "2", "--like", "stet"])
        assert code == 0
        dna_json = out_film / "dna.json"
        dna_ts = out_film / "kit" / "dna.gen.ts"
        ref_md = out_film / "REFERENCE.md"
        score_json = out_film / "score.json"
        assert dna_json.is_file() and dna_ts.is_file() and ref_md.is_file() and score_json.is_file()
        dna = json.loads(dna_json.read_text(encoding="utf-8"))
        assert dna["default_spring"]["freq"] > 0 and dna["default_spring"]["damp"] > 0
        assert len(dna["default_bezier"]) == 4
        assert len(dna["palette"]["swatches"]) >= 3
        assert "hero_share" in dna["palette"]["ink_bands"]
        assert dna["repo"]["name"] == "SampleEngine"
        assert dna["archetype"] == "stet", "the kind is the one chosen with --like, never one guessed from the measures"
        # a cached measure made by another measure.py is measured again, not trusted
        import hashlib
        import measure
        m_dir = Path.home() / ".vd" / "measures" / ("borrow-" + hashlib.sha1(ref_mp4.read_bytes()).hexdigest()[:12])
        (m_dir / "measure.json").write_text(json.dumps({"version": 0}), encoding="utf-8")
        assert lean.main(["borrow", str(ref_mp4), "-o", str(out_film), "--k", "2"]) == 0, "in a film folder no --like is needed"
        assert json.loads((m_dir / "measure.json").read_text(encoding="utf-8"))["version"] == measure.VERSION
        ts_text = dna_ts.read_text(encoding="utf-8")
        assert "export const DNA_SPRING =" in ts_text and "export const DNA_PALETTE =" in ts_text
        pin_dir = lean.outdir(out_film) / "pin"
        assert pin_dir.is_dir() and list(pin_dir.glob("story-*.jpg")), f"expected pin sheets in {pin_dir}"


def test_capture_and_launch_build_live_codebase_puppets():
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / "prism-cli"
        repo_dir.mkdir()
        (repo_dir / "README.md").write_text("# PrismCLI\nZero-copy AST verifier for local builds.\n", encoding="utf-8")
        (repo_dir / "verifier.py").write_text(
            "class Verifier:\n    pass\n\ndef check_ast(node):\n    return True\n\ndef run_all():\n    return 42\n",
            encoding="utf-8",
        )
        film_dir = Path(tmp) / "prism-launch"
        cmd = f'"{sys.executable}" -c "print(\'ok test_ast_verifier (1.2 ms)\'); print(\'2 passed in 0.01s\')"'
        code = lean.main(["launch", str(repo_dir), "-o", str(film_dir), "--like", "stet", "--cmd", cmd])
        assert code == 0
        gen_ts = film_dir / "kit" / "puppet.gen.ts"
        plane_tsx = film_dir / "kit" / "PuppetPlane.tsx"
        assert gen_ts.is_file() and plane_tsx.is_file()
        gen_text = gen_ts.read_text(encoding="utf-8")
        assert "PrismCLI" in gen_text and "ok test_ast_verifier" in gen_text
        assert "export const PUPPET_DATA =" in gen_text and "export const PUPPET_TERMINAL =" in gen_text
        # Verify all relative TypeScript imports in the film folder resolve cleanly
        assert lean.prune_unresolved(film_dir / "kit") == []
        # broke: nothing imported the plane, so the film was Stet unchanged; and the plane named a face it never loaded
        film_src = (film_dir / "film.tsx").read_text(encoding="utf-8")
        assert "PuppetTerminal" in film_src and "./kit/PuppetPlane" in film_src, "the launch film draws the plane"
        assert "<style>{PUPPET_FONTS}</style>" in plane_tsx.read_text(encoding="utf-8"), "the plane mounts its own faces"
        assert "On screen:** the plane" in (film_dir / "REPO-FACTS.md").read_text(encoding="utf-8")


def test_evolve_packs_four_blind_world_candidates_and_selects_winner():
    with tempfile.TemporaryDirectory() as tmp:
        with tempfile.TemporaryDirectory() as fake_out:
            old_outroot = lean.OUTROOT
            lean.OUTROOT = Path(fake_out)
            try:
                target = Path(tmp) / "evo-film"
                tourn_dir, key_path, brief_path, _mapping = evolve.build_tournament(
                    name=str(target), render=False, reads_root=Path(tmp) / "reads"
                )
                assert tourn_dir.is_dir() and key_path.is_file() and brief_path.is_file()
                letters = sorted(p.name for p in tourn_dir.iterdir() if p.is_dir())
                assert letters == ["A", "B", "C", "D"]
                for ltr in letters:
                    blind = (tourn_dir / ltr / "BOARD-BLIND.md").read_text(encoding="utf-8")
                    metrics = json.loads((tourn_dir / ltr / "perceptual-metrics.json").read_text(encoding="utf-8"))
                    assert "passes_wcag_45" not in metrics and metrics["range_ratio"] >= 1.0, "a sheet's tonal range is reported, never as text that passes WCAG"
                    assert "evo-film" not in blind.lower()
                    for arch in ("plusone", "stet", "onoma", "linden"):
                        assert arch not in blind.lower(), f"blind board {ltr} leaked archetype {arch}"
                div_json = json.loads((lean.outdir(target) / "evolve-1-divergence.json").read_text(encoding="utf-8"))
                assert div_json["divergent"] and div_json["bpm_spread"] >= 20.0, div_json
                t1 = lean.outdir(target) / "tournaments" / "t1"
                assert (t1 / "v1-plusone" / "AUTHOR-BRIEF.md").is_file() and not (target / "candidates").exists()
                # broke: a second run reused the candidates and wrote over a board an author had worked on
                (t1 / "v2-stet" / "BOARD.md").write_text("# an author's board", encoding="utf-8")
                evolve.build_tournament(name=str(target), render=False, reads_root=Path(tmp) / "reads")
                assert (t1 / "v2-stet" / "BOARD.md").read_text(encoding="utf-8") == "# an author's board"
                assert (lean.outdir(target) / "tournaments" / "t2" / "v2-stet" / "BOARD.md").is_file()
                # and a key promotes only what its readers saw: tournament 1's stet sketch has changed since
                k1 = (lean.outdir(target) / "evolve-1-KEY.txt").read_text(encoding="utf-8")
                stet_letter = next(l.split("/")[1][0] for l in k1.splitlines() if l.startswith("tournament/") and "= stet " in l)
                try:
                    evolve.select_winner(target, letter=stet_letter, key_file=lean.outdir(target) / "evolve-1-KEY.txt")
                    raise AssertionError("a sketch changed after it was read was promoted")
                except SystemExit as e:
                    assert "not what its readers saw" in str(e), e
                # a tie among the readers goes to the sheet with the wider tonal range, read from the key
                key2 = (lean.outdir(target) / "evolve-2-KEY.txt").read_text(encoding="utf-8")
                ranges = {l.split("/")[1][0]: float(l.split("[tonal range ")[1].split(":1")[0]) for l in key2.splitlines() if l.startswith("tournament/")}
                a_, b_ = sorted(ranges)[:2]
                tie = Path(tmp) / "TIE.md"
                tie.write_text(f"RANKING: {a_} > {b_} > C > D\nRANKING: {b_} > {a_} > C > D\n", encoding="utf-8")
                want = max((a_, b_), key=lambda x: ranges[x])
                mapping = {k: {"metrics": {"range_ratio": v}} for k, v in ranges.items()}
                assert evolve.parse_winner_from_readings(tie, mapping) == want
                # Promote consensus winner from a two-reader blind READINGS.md file
                readings_md = Path(tmp) / "READINGS.md"
                readings_md.write_text(
                    "## Reader 1 (Claude)\nRANKING: B > D > A > C\n\n## Reader 2 (GPT)\nRANKING: B > A > D > C\n",
                    encoding="utf-8",
                )
                # what vd pin or vd borrow put in the film folder before is kept when the winner is copied in
                target.mkdir(exist_ok=True)   # a film folder vd pin or vd borrow has written into
                sj = target / "score.json"
                old = json.loads(sj.read_text(encoding="utf-8")) if sj.is_file() else {}
                sj.write_text(json.dumps({**old, "pinned": {"from": "ref.mp4"}, "dna": "dna.json", "targets_all": {"x": 1}}), encoding="utf-8")
                try:
                    evolve.select_winner(target)
                    raise AssertionError("a winner was promoted with no letter chosen")
                except SystemExit as e:
                    assert "letter" in str(e), e
                (target / "notes.tsx").write_text("// the author's own file", encoding="utf-8")
                code = lean.main(["evolve", str(target), "--readings", str(readings_md)])
                assert code == 0
                # the folder is the chosen film now; what was in it is moved aside, not mixed in and not deleted
                aside = lean.outdir(target) / "before-select-1"
                assert not (target / "notes.tsx").exists() and (aside / "notes.tsx").is_file(), sorted(p.name for p in target.iterdir())
                promoted = json.loads(sj.read_text(encoding="utf-8"))
                assert promoted["pinned"] == {"from": "ref.mp4"} and promoted["dna"] == "dna.json" and promoted["targets_all"] == {"x": 1}, promoted
                assert (target / "score.json").is_file() and (target / "BOARD.md").is_file()
                winner_meta = json.loads((lean.outdir(target) / "EVOLVE-WINNER.json").read_text(encoding="utf-8"))
                assert not (target / "EVOLVE-WINNER.json").exists(), "bookkeeping stays out of the film folder"
                assert winner_meta["letter"] == "B"
            finally:
                lean.OUTROOT = old_outroot


def test_playable_exports_interactive_runtime_twin():
    if playable.find_esbuild() is None and playable.find_bun() is None:
        print("skipped: neither esbuild nor bun is installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "playable-stet"
        lean.main(["new", str(d), "--like", "stet"])
        out_play = Path(tmp) / "playable-out"
        code = lean.main(["playable", "--film", str(d), "-o", str(out_play)])
        assert code == 0
        index_html = out_play / "index.html"
        bundle_js = out_play / "bundle.js"
        assert index_html.is_file() and bundle_js.is_file()
        html = index_html.read_text(encoding="utf-8")
        js = bundle_js.read_text(encoding="utf-8")
        assert "View Decompiled Score" in html and "120fps" not in html and "Scroll wheel" in html
        assert len(js) > 5000 and "vd-stage" in js and "wheel" in js and "vd-inspector" in js
        # broke: SVG filter attributes were hyphenated (base-frequency), so the grain filter drew nothing; and the sound
        # ended while the picture looped on silently
        assert "\"baseFrequency\",\"numOctaves\",\"stdDeviation\"" in js, "SVG keeps its camelCase attribute names"
        assert ("loop>" in html) or ("<audio" not in html), "the sound loops with the picture"
        # a film whose sound comes from vd sound: a rebuilt mix reaches a rebuilt playable (the first build's copy had
        # kept every later mix out). Its score.json names no own mix, as the export would refuse one that is missing
        (d / "media" / "sound.wav").unlink(missing_ok=True)
        s = lean.score_of(d)
        s.pop("sound_file", None)
        (d / "score.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
        out_play2 = Path(tmp) / "playable-out-2"
        built = Path(lean.outdir(d)) / "sound.wav"
        built.parent.mkdir(parents=True, exist_ok=True)
        try:
            for level in (0.1, 0.2):
                lean.write_wav(built, np.full((4800, 2), level, np.float32))
                assert lean.main(["playable", "--film", str(d), "-o", str(out_play2)]) == 0
                assert (out_play2 / "media" / "sound.wav").read_bytes() == built.read_bytes(), "the current mix"
        finally:
            built.unlink(missing_ok=True)


def test_playable_fits_any_window_and_plays_the_films_whole_mix():
    # broke: in a window narrower than 1920 px the stage, a flex item free to shrink, was squeezed to the window's width
    # and then scaled, so the left half of the frame showed; and the page played media/sound.wav, the film's own mix
    # alone, where the export lays the voice and a mapped track over it
    if playable.find_esbuild() is None and playable.find_bun() is None:
        print("skipped: neither esbuild nor bun is installed")
        return
    import re
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "playable-mix"
        lean.main(["new", str(d), "--like", "stet"])
        t = np.arange(48000 * 2) / 48000.0
        lean.write_wav(d / "media" / "voice-test.wav", np.repeat((0.2 * np.sin(2 * np.pi * 220 * t))[:, None], 2, axis=1).astype(np.float32))
        s = lean.score_of(d)
        s["voice"] = {"file": "media/voice-test.wav", "at": 1.0}
        (d / "score.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
        out_play = Path(tmp) / "play"
        assert lean.main(["playable", "--film", str(d), "-o", str(out_play)]) == 0
        html = (out_play / "index.html").read_text(encoding="utf-8")
        stage = re.search(r"#vd-stage \{\{?([^}]*)\}", html).group(1)
        assert "flex: none" in stage, ("the stage keeps its size and is only scaled", stage)
        # scaled to the window by both sides, with no floor that crops a small pane (a 10% floor cropped any pane under
        # 216 px, and a scale forced to 1 was not caught: a review's findings). This reads the page's source in playable.py,
        # which the bundler rewrites; no browser runs.
        src = Path(playable.__file__).read_text(encoding="utf-8")
        fit = re.search(r"const s = Math\.min\(\(wrap\.clientWidth - 24\) / W, \(wrap\.clientHeight - 24\) / H\);", src)
        floor = re.search(r"stage\.style\.transform = `scale\(\$\{Math\.max\(([\d.]+), s\)", src)
        assert fit and floor and float(floor.group(1)) <= 0.01, ("the stage scales to fit the window, floored at no more than 1%", fit, floor)
        played = out_play / re.search(r"<audio id='vd-audio' src='([^']+)'", html).group(1)
        mix = lean.outdir(d) / "sound.wav"
        assert mix.is_file() and played.read_bytes() == mix.read_bytes(), "the page plays the mix the export lays under the picture"
        assert played.read_bytes() != (d / "media" / "sound.wav").read_bytes(), "not the film's own mix without its voice"


def test_playable_builds_every_worked_film_against_its_raea_stand_in():
    """vd playable bundles a film against a stand-in for raea (playable.py's RAEA_SHIM_TS), not raea itself, so the
    stand-in can fall behind what films use. The bundler refuses an import the stand-in does not export: every worked
    film is built through it here, so a name a film uses and the stand-in lacks fails this test, not a person's page."""
    if playable.find_esbuild() is None and playable.find_bun() is None:
        print("skipped: neither esbuild nor bun is installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        for like in ("stet", "onoma", "plusone", "linden"):
            d = Path(tmp) / like
            assert lean.main(["new", str(d), "--like", like]) == 0
            out_play = Path(tmp) / ("play-" + like)
            assert lean.main(["playable", "--film", str(d), "-o", str(out_play)]) == 0, like
            assert (out_play / "bundle.js").stat().st_size > 5000 and (out_play / "index.html").is_file(), like
        # the control: an import the stand-in does not have stops the build (so the four builds above prove the names)
        d = Path(tmp) / "stet"
        entry = lean.entry_of(d)
        # used, as a film uses what it imports (TypeScript drops an import nothing uses, as it may be a type)
        entry.write_text('import { NotInRaea } from "raea";\nconsole.warn(NotInRaea);\n' + entry.read_text(encoding="utf-8"),
                         encoding="utf-8")
        try:
            code = lean.main(["playable", "--film", str(d), "-o", str(Path(tmp) / "play-bad")])
        except SystemExit as e:
            code = e.code
        assert code not in (0, None), "a name the stand-in lacks must stop the build"


def test_flash_scan_catches_wcag_231_flashing_and_wcag_45_contrast():
    import subprocess
    import flash_scan
    import scan
    # 1. Verify WCAG 4.5:1 contrast ratio calculation
    assert abs(float(flash_scan.wcag_contrast_ratio(1.0, 0.0)) - 21.0) < 0.01
    assert abs(float(flash_scan.wcag_contrast_ratio(1.0, 1.0)) - 1.0) < 0.01

    # 2. Synthesize a 2-second 30 fps video with a 5 Hz strobe in the center (> 3 flashes/s -> 10 transitions/s)
    with tempfile.TemporaryDirectory() as tmp:
        strobe_mp4 = Path(tmp) / "strobe.mp4"
        w, h, fps = 320, 180, 30
        frames = []
        for i in range(60):
            img = np.full((h, w, 3), 20, dtype=np.uint8)
            # Flash a large central region at 5 Hz during the first second (frames 0..29: alternates every 3 frames)
            if i < 30 and (i // 3) % 2 == 1:
                img[20:160, 40:280] = 245
            frames.append(img)
        raw = np.stack(frames).tobytes()
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
             "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(strobe_mp4)],
            input=raw, check=True,
        )
        res = flash_scan.screen_video(strobe_mp4)
        assert res["verdict"] == "FLAGGED" and res["busiest_classic"]["transitions_in_1s"] > 6, res
        text, fixes = scan.scan(strobe_mp4)
        assert any(f.startswith("fix before anyone watches: flashing over WCAG 2.3.1") for f in fixes), (fixes, text)




def test_external_audio_tempo_map_voice_clean_and_listen_sheet():
    import listen
    import tempo_map
    import voice_clean
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "audio-film"
        lean.main(["new", str(d), "--kind", "launch"])

        # 1. Synthesize a 10 s 120 BPM click/kick track (period = 0.5 s) with a loudness rise at beat 8 (t = 4.0 s)
        sr = 48000
        dur = 10.0
        t = np.arange(int(dur * sr), dtype=np.float32) / sr
        music = np.zeros((len(t), 2), dtype=np.float32)
        for beat in range(20):
            idx = int(round(beat * 0.5 * sr))
            n_hit = min(int(0.08 * sr), len(t) - idx)
            th = np.arange(n_hit, dtype=np.float32) / sr
            amp = 0.22 if beat < 8 else 0.72
            kick = amp * np.sin(2.0 * np.pi * 95.0 * th * (1.0 + 0.8 * np.exp(-th * 40.0))) * np.exp(-th * 28.0)
            music[idx:idx + n_hit, 0] += kick
            music[idx:idx + n_hit, 1] += kick
        music_wav = Path(tmp) / "external-music.wav"
        foley.write_wav(music_wav, music)

        # 2. Synthesize a Klatt-style formant speech signal (glottal harmonics + F1/F2/F3 vowel formants + /s/ sibilants + room tone) at ~-21.5 LUFS
        rng = np.random.default_rng(9)
        f0 = 132.0 + 18.0 * np.sin(2.0 * np.pi * 1.4 * t)
        phase = 2.0 * np.pi * np.cumsum(f0) / sr
        glottal = np.zeros_like(t)
        for h in range(1, 26):
            glottal += (1.0 / (h ** 1.15)) * np.sin(h * phase)
        # Apply time-varying vowel formants (F1 ~ 520 Hz, F2 ~ 1750 Hz, F3 ~ 2650 Hz) + syllable cadence
        syl_env = np.clip(np.sin(2.0 * np.pi * 2.5 * t) * 1.4, 0.0, 1.0) ** 0.7
        voiced = (
            0.55 * foley.band(glottal, 320.0, 820.0, sr)
            + 0.35 * foley.band(glottal, 1300.0, 2300.0, sr)
            + 0.15 * foley.band(glottal, 2400.0, 3400.0, sr)
        ) * syl_env
        # Add alveolar /s/ sibilant bursts (5.5-8.0 kHz) at syllable edges + -48 dBFS room tone
        sibilant_mask = np.clip(np.cos(2.0 * np.pi * 2.5 * t) - 0.75, 0.0, 1.0) * 4.0
        sibilants = foley.band(rng.standard_normal(len(t)).astype(np.float32), 5500.0, 8200.0, sr) * sibilant_mask * 0.04
        room_tone = rng.standard_normal(len(t)).astype(np.float32) * 0.0035
        voice = ((voiced * 0.042) + sibilants + room_tone).astype(np.float32)
        voice_wav = Path(tmp) / "raw-voice.wav"
        foley.write_wav(voice_wav, np.stack([voice, voice], axis=1))

        # Verify voice_clean accepts all 5 stages without speech-band damage
        rep = voice_clean.clean_voice(voice_wav, Path(tmp) / "direct-clean.wav")
        assert rep["refused"] is None and rep["exit_code"] == 0, rep

        # Run `vd audio` for voice cleanup, mapping a track as the film's beat (score.json's music), and the 5-lane sound sheet
        assert lean.main(["audio", str(voice_wav), "--clean-voice", "--film", str(d)]) == 0
        assert (d / "media" / "raw-voice-clean.wav").is_file()

        assert lean.main(["audio", str(music_wav), "--tempo-map", "--bpm", "120", "--drop-at-beat", "8", "--sheet", "--film", str(d)]) == 0
        s = lean.score_of(d)
        assert abs(s["music"]["bpm"] - 120.0) < 1.5 and s["music"]["fb"] == round(60 * s["fps"] / 120.0) and (d / s["music"]["file"]).is_file(), s["music"]
        assert not (d / "kit" / "times.gen.ts").exists(), "the clock file is a worked film's sound.py's alone; a starter has none"
        assert lean.main(["sound", "--film", str(d)]) in (0, 1), "a starter with no sound.py builds its mix with the track in it"
        sheet_png = lean.outdir(d) / "listen-sheet.png"
        assert sheet_png.is_file()
        with Image.open(sheet_png) as im:
            assert im.size == (1600, 760)




def test_legible_film_bridge_exports_valid_v2_cues_xmeml_and_otio():
    import subprocess
    ref_mp4 = ROOT / "docs" / "media" / "stet.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "bridge-film"
        lean.main(["new", str(d), "--like", "stet"])
        bridge_out = Path(tmp) / "bridge-out"
        code = lean.main(["bridge", "--film", str(d), "--video", str(ref_mp4), "-o", str(bridge_out), "--host-in", "2.5"])
        assert code == 0
        cues_json = bridge_out / "cues.json"
        timing_json = bridge_out / "picture-timing.json"
        xml_path = bridge_out / "timeline.xml"
        otio_path = bridge_out / "timeline.otio"
        assert cues_json.is_file() and timing_json.is_file() and xml_path.is_file() and otio_path.is_file()

        doc = json.loads(cues_json.read_text(encoding="utf-8"))
        assert doc["version"] == "v2" and doc["picture"]["kind"] == "picture" and len(doc["picture"]["sha256"]) == 64
        assert len(doc["sections"]) >= 1 and len(doc["events"]) >= 4

        # Verify against legible-film's own cue_list.py and exchange.py when installed on this machine
        lf_scripts = Path.home() / ".agents" / "skills" / "legible-film" / "scripts"
        if (lf_scripts / "cue_list.py").is_file():
            p = subprocess.run(
                [sys.executable, str(lf_scripts / "cue_list.py"), str(cues_json), "--json"],
                capture_output=True, text=True, encoding="utf-8",
            )
            assert p.returncode == 0, p.stdout + p.stderr
            state = json.loads(p.stdout)
            assert state["state"] == "fresh" and state["version"] == "v2", state
        if (lf_scripts / "exchange.py").is_file():
            p = subprocess.run(
                [sys.executable, str(lf_scripts / "exchange.py"), "read", str(xml_path)],
                capture_output=True, text=True, encoding="utf-8",
            )
            assert p.returncode == 0 and "1 mapped, 0 skipped, 0 not mapped" in p.stdout, p.stdout + p.stderr
        if (lf_scripts / "spot_cues.py").is_file():
            # legible-film's sound spotting reads the same file: it refused every turn event, which had no role
            p = subprocess.run(
                [sys.executable, str(lf_scripts / "spot_cues.py"), str(cues_json), "--out-dir", str(Path(tmp) / "spotted")],
                capture_output=True, text=True, encoding="utf-8",
            )
            assert p.returncode == 0, p.stdout + p.stderr




def test_vd_main_entrypoint_routes_all_commands_cleanly():
    import vd
    # 1. Calling vd.main([]) with no arguments prints help and returns 0 instead of raising AttributeError
    assert vd.main([]) == 0
    # 2. Calling vd.main(["new", ...]) directly as a Python entrypoint delegates to lean.main()
    with tempfile.TemporaryDirectory() as tmp:
        film_dir = Path(tmp) / "entry-check"
        assert vd.main(["new", str(film_dir), "--kind", "app"]) == 0
        assert (film_dir / "score.json").is_file()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("alien feature checks passed")
