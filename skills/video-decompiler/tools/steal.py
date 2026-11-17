#!/usr/bin/env python3
"""`vd steal` (not proven on a film): a reference's moves fitted to springs and curves, and its held colours,
into dna.json, kit/dna.gen.ts and a REFERENCE.md to finish by TAKE-APART.md.

  python steal.py REF.mp4 [--for REPO_DIR] [--out FILM_DIR]

What it does: measures the reference (vd pin's measure), fits each move's speed profile to physics.ts's spring
(frequency, damping) and a cubic curve, and takes the held colours. Which worked film it is like is chosen with
--like, never guessed. A move with no usable profile, a poor fit or a fit on the grid's edge is marked unfitted
(`fitted: false`), never a perfect fit. It pins no targets: vd measure reads vd pin's numbers.
Known answer: tests/test_new_check_faults.py plants springs on moves of 0.2 to 1.2 s and recovers them within 0.15 Hz
and 0.06 damping, and calls an inOutCubic glide unfitted.
"""
import argparse
import functools
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))


FREQS = np.round(np.arange(0.5, 8.0001, 0.05), 2)     # Hz: physics.ts springs in the worked films run 1.5 to 5
DAMPS = np.round(np.linspace(0.20, 1.15, 20), 2)
FIT_MSE = 0.02    # above this the move is not a spring of this family (an inOutCubic glide fits damp 0.2 at 0.198)


@functools.lru_cache(maxsize=64)
def spring_velocity_curves(dur):
    """Normalised speed profiles (measure.POINTS long) of physics.ts's spring(t, {freq, damp}) over a move lasting `dur`
    seconds, for every (freq, damp) on the grid. The grid is in real hertz at the move's own length: one made in
    move-relative units and divided by the length afterwards could not reach 2.2 Hz on a 0.2 s move (it read 5.0)."""
    import measure
    t = np.linspace(0.0, float(dur), measure.POINTS + 1)
    grid, curves = [], []
    for freq in FREQS:
        w = 2.0 * math.pi * float(freq)
        for damp in DAMPS:
            damp = float(damp)
            if damp < 1.0:
                wd = w * math.sqrt(1.0 - damp * damp)
                y = 1.0 - np.exp(-damp * w * t) * (np.cos(wd * t) + (damp * w / wd) * np.sin(wd * t))
            elif damp == 1.0:
                y = 1.0 - np.exp(-w * t) * (1.0 + w * t)
            else:
                r = math.sqrt(damp * damp - 1.0)
                a, b = -w * (damp - r), -w * (damp + r)
                c2 = a / (b - a)
                c1 = -1.0 - c2
                y = 1.0 + c1 * np.exp(a * t) + c2 * np.exp(b * t)
            v = np.abs(np.diff(y))
            curves.append(v / max(float(v.max()), 1e-9))
            grid.append((float(freq), damp))
    return tuple(grid), np.asarray(curves, dtype=np.float32)


def fit_spring_profile(profile, dur=0.5):
    """Fit a move's normalised speed profile to physics.ts's spring(t, {freq, damp}) over its `dur` seconds.
    Returns {'freq', 'damp', 'mse', 'fitted'}. `fitted` is False, with physics.ts's default spring, when there is no
    usable profile; and False beside the nearest spring when the fit is poor (mse over FIT_MSE) or lands on the edge of
    the grid, since then no spring of this family was found, only the closest it could reach."""
    import measure
    p = np.asarray(profile, dtype=np.float32)
    if len(p) != measure.POINTS or float(p.max(initial=0.0)) <= 0 or not dur or float(dur) <= 0:
        return {"freq": 2.2, "damp": 0.45, "mse": None, "fitted": False}
    grid, curves = spring_velocity_curves(round(float(dur), 3))
    p = p / float(p.max())
    errs = ((curves - p[None, :]) ** 2).mean(axis=1)
    idx = int(np.argmin(errs))
    freq, damp = grid[idx]
    mse = float(errs[idx])
    edge = freq in (float(FREQS[0]), float(FREQS[-1])) or damp in (float(DAMPS[0]), float(DAMPS[-1]))
    return {"freq": round(freq, 2), "damp": round(damp, 2), "mse": round(mse, 4), "fitted": bool(mse <= FIT_MSE and not edge)}


def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) != 6:
        return (20, 20, 20)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_luma(rgb):
    r, g, b = (c / 255.0 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgb_sat(rgb):
    mx, mn = max(rgb) / 255.0, min(rgb) / 255.0
    return 0.0 if mx <= 1e-6 else (mx - mn) / mx


def extract_palette_and_ink(m):
    """Aggregate hold palettes and ink-band histograms from measure.py's output."""
    holds = m.get("holds") or []
    weights = {}
    bands = []
    occupancies = []
    details = []
    for h in holds:
        dur = max(0.05, float(h.get("t1", 0.0)) - float(h.get("t0", 0.0)))
        occupancies.append(float(h.get("occupancy", 0.1)))
        details.append(float(h.get("detail", 0.01)))
        if h.get("bands"):
            bands.extend(float(b) for b in h["bands"])
        for hex_col, share in h.get("palette") or []:
            weights[hex_col] = weights.get(hex_col, 0.0) + dur * float(share)
    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    colors = [c for c, _ in ranked] if ranked else ["#121316", "#f4efe6", "#2a5bd7", "#e04f33"]
    # the ground is the frame's border colour held longest (measure.py's background), not the largest colour cluster:
    # a film of dark paintings on paper had its paintings' navy taken for its ground
    grounds = {}
    for h in holds:
        if h.get("ground"):
            k = tuple(v // 16 for v in hex_to_rgb(h["ground"]))
            grounds.setdefault(k, [0.0, h["ground"]])[0] += max(0.05, float(h.get("t1", 0.0)) - float(h.get("t0", 0.0)))
    ground = max(grounds.values())[1] if grounds else colors[0]
    colors = [ground] + [c for c in colors if c != ground]
    g_luma = rgb_luma(hex_to_rgb(ground))
    # Ink is the colour with highest luminance contrast against ground
    ink = max(colors, key=lambda c: abs(rgb_luma(hex_to_rgb(c)) - g_luma)) if len(colors) > 1 else ("#141413" if g_luma > 0.5 else "#f5f2eb")
    if abs(rgb_luma(hex_to_rgb(ink)) - g_luma) < 0.35:
        ink = "#141413" if g_luma > 0.5 else "#f5f2eb"
    # the accent: the most coloured (chroma, max - min) of the colours clearly apart from ground and ink. Saturation on
    # its own made a near-black teal the accent, and a colour one step from the ground counted as distinct from it
    far = lambda a, b: sum((x - y) ** 2 for x, y in zip(hex_to_rgb(a), hex_to_rgb(b))) ** 0.5 >= 48
    chroma = lambda c: max(hex_to_rgb(c)) - min(hex_to_rgb(c))
    apart = [c for c in colors if far(c, ground) and far(c, ink)]
    accent = max(apart, key=chroma) if apart and chroma(max(apart, key=chroma)) >= 40 else "#e04f33"
    surface = next((c for c in colors if c not in (ground, ink, accent)), "#24262b" if g_luma <= 0.5 else "#e8e2d5")
    band_arr = np.asarray(bands, dtype=np.float32) if bands else np.array([0.08, 0.05, 0.036], dtype=np.float32)
    return {
        "ground": ground,
        "ink": ink,
        "accent": accent,
        "surface": surface,
        "is_dark": bool(g_luma < 0.45),
        "swatches": [{"hex": c, "weight": round(w, 3)} for c, w in ranked[:8]],
        "ink_bands": {
            "hero_share": round(float(np.percentile(band_arr, 90)), 3),
            "statement_share": round(float(np.percentile(band_arr, 60)), 3),
            "body_share": round(float(np.percentile(band_arr, 30)), 3),
            "occupancy_median": round(float(np.median(occupancies)) if occupancies else 0.18, 3),
            "detail_median": round(float(np.median(details)) if details else 0.015, 4),
        },
    }


def compile_beat_table(m, near_fb=None):
    """Snap measured visual events, cuts, holds and audio onsets onto one deterministic beat clock. Onsets cannot tell a
    tempo from its half or double (measure.py names both as `octave`); with `near_fb`, the frames a beat of the film
    being made, the one of the three nearest it is taken (Linden's 100 BPM was read as 200 and set 18 frames a beat)."""
    fps = 60
    dur = float(m.get("duration") or 30.0)
    snd = m.get("sound") or {}
    t = snd.get("tempo") or {}
    bpm = float(t.get("bpm") or 112.5)
    if near_fb and t.get("octave"):
        bpm = min([bpm, *map(float, t["octave"])], key=lambda b: abs(3600.0 / b - near_fb))
    # Choose an integer frames-per-beat FB near 60 * 60 / bpm
    fb = max(18, min(60, int(round(3600.0 / bpm))))
    beat_s = fb / fps
    beats_total = max(8, int( math.ceil(dur / beat_s)))
    events_s = [float(t) for t in (m.get("events") or [0.0])]
    onsets_s = [float(t) for t in (snd.get("onsets") or [])]

    def snap_sec(t):
        if onsets_s:
            nearest = min(onsets_s, key=lambda o: abs(o - t))
            if abs(nearest - t) <= 0.065:
                t = nearest
        return round(t / beat_s, 3)

    event_beats = sorted({snap_sec(t) for t in events_s if 0.0 <= t <= dur})
    if not event_beats:
        event_beats = [round(i * beats_total / 6.0, 2) for i in range(6)]
    cuts_beats = [snap_sec(t) for t in (m.get("cuts") or [])]
    cues = [[f"BEAT_{i + 1}", round(b * beat_s, 4)] for i, b in enumerate(event_beats[:24])]
    clock = {
        "FPS": fps,
        "FB": fb,
        "BEATS": beats_total,
        "DURATION": round(beats_total * beat_s, 6),
        "BPM": round(60.0 / beat_s, 4),
    }
    times = {
        "OPEN": event_beats[0] if event_beats else 0.0,
        "TURN": event_beats[len(event_beats) // 3] if len(event_beats) >= 3 else round(beats_total * 0.33, 2),
        "PROOF": event_beats[(2 * len(event_beats)) // 3] if len(event_beats) >= 3 else round(beats_total * 0.66, 2),
        "END": event_beats[-1] if len(event_beats) else round(beats_total * 0.85, 2),
        "EVENTS": event_beats,
        "CUTS": cuts_beats,
    }
    return clock, times, cues


def inspect_repo(repo_dir: Path):
    """Read a target repository's real metadata (name, tagline, CLI/scripts, languages, git stats) without running code."""
    repo_dir = Path(repo_dir).resolve()
    if not repo_dir.exists():
        raise SystemExit(f"--for {repo_dir}: no such folder")
    name = repo_dir.name
    tagline = f"{name}: built from source."
    commands = []
    # Check package.json, pyproject.toml, Cargo.toml, README.md
    pkg = repo_dir / "package.json"
    if pkg.is_file():
        try:
            pj = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            name = pj.get("name") or name
            if pj.get("description"):
                tagline = str(pj["description"]).strip()
            for k, v in list((pj.get("scripts") or {}).items())[:4]:
                commands.append(f"npm run {k}  # {v}")
        except ValueError:
            pass
    readme = next((repo_dir / f for f in ("README.md", "readme.md", "SKILL.md") if (repo_dir / f).is_file()), None)
    if readme:
        lines = [l.strip() for l in readme.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        for l in lines:
            if l.startswith("# ") and len(l) > 2:
                name = l[2:].strip()[:48]
                break
        for l in lines:
            if not l.startswith(("#", "<", "!", "|", "-", "`", "[")) and len(l) >= 16:
                tagline = re.sub(r"\*\*|\*|`|\[([^\]]+)\]\([^)]+\)", r"\1", l).strip()[:110]
                break
    py_files = [p for p in repo_dir.rglob("*.py") if ".git" not in p.parts and "node_modules" not in p.parts and "__pycache__" not in p.parts]
    ts_files = [p for p in list(repo_dir.rglob("*.ts")) + list(repo_dir.rglob("*.tsx")) if ".git" not in p.parts and "node_modules" not in p.parts]
    commits = 0
    try:
        p = subprocess.run(["git", "-C", str(repo_dir), "rev-list", "--count", "HEAD"], capture_output=True, text=True, timeout=5)
        if p.returncode == 0 and p.stdout.strip().isdigit():
            commits = int(p.stdout.strip())
    except Exception:
        pass
    return {
        "name": name,
        "path": repo_dir.as_posix(),
        "tagline": tagline,
        "python_files": len(py_files),
        "ts_files": len(ts_files),
        "total_code_files": len(py_files) + len(ts_files),
        "commits": commits,
        "commands": commands or [f"cd {repo_dir.name}"],
    }


def write_reference_md(dest: Path, ref_path: Path, dna: dict):
    """Write REFERENCE.md, a start on the TAKE-APART.md dossier, from what steal measured and fitted."""
    s = dna["summary"]
    pal = dna["palette"]
    springs = dna["springs"]
    archetype, why_arch = dna["archetype"], dna["archetype_reason"]
    sp_default = dna["default_spring"]
    bez_default = dna["default_bezier"]
    lines = [
        f"# {ref_path.stem} (decompiled by `vd steal`)",
        f"> The claim: {dna['duration']:.1f} s at {dna['fps']:g} fps ({s.get('events_per_10s', 0)} events/10s), moving {float(s.get('move_share') or 0):.0%} of the time.",
        f"Post: local file `{ref_path.name}` · {dna['duration']:.1f} s · {dna['width']}x{dna['height']} at {dna['fps']:g} fps · tempo {dna['clock']['BPM']} BPM",
        f"Kind: {('`' + archetype + '` (' + why_arch + ')') if archetype else 'to be written from the film itself (TAKE-APART.md); ' + why_arch}",
        f"Evidence: measured every frame by `measure.py` and `space.py`; {len(springs)} move speed profiles fitted to closed-form springs and cubic-beziers.",
        "",
        "## Spine",
        "```text",
    ]
    for seg in (dna.get("segments") or [])[:16]:
        lines.append(f"{seg['t0']:6.2f}s .. {seg['t1']:6.2f}s  [{seg['kind'].upper():4s}]")
    lines += [
        "```",
        "",
        "## The world",
        f"- **Ground:** `{pal['ground']}` ({'dark' if pal['is_dark'] else 'light'} ground) · **Ink:** `{pal['ink']}` · **Accent:** `{pal['accent']}` · **Surface:** `{pal['surface']}`.",
        f"- **Ink bands (share of frame height):** hero {pal['ink_bands']['hero_share']}, statement {pal['ink_bands']['statement_share']}, body {pal['ink_bands']['body_share']}; median occupancy {pal['ink_bands']['occupancy_median']}.",
        f"- **Space:** scene motion {s.get('scene_move')}, sheet motion {s.get('sheet_move')}, lit middle with dark corners {s.get('dark_corners')}.",
        "",
        "## The formal idea",
        f" Events lock to a {dna['clock']['BPM']} BPM grid ({dna['clock']['FB']} frames/beat at 60 fps); moves follow `spring(s, {{ freq: {sp_default['freq']}, damp: {sp_default['damp']} }})` / `bezier({', '.join(map(str, bez_default))})`.",
        "",
        "## Moves (optical-flow spring + bezier fit)",
        "| t0 (s) | dur (s) | spring freq (Hz) | spring damp | cubic-bezier | reliable |",
        "|---|---|---|---|---|---|",
    ]
    for mv in springs[:12]:
        lines.append(f"| {mv['t0']:.2f} | {mv['dur']:.2f} | {mv['spring']['freq']} | {mv['spring']['damp']} | `{mv['ease']}` | {mv['reliable']} |")
    if not springs:
        lines.append(f"| 0.00 | 0.35 | {sp_default['freq']} | {sp_default['damp']} | `{bez_default}` | default |")
    lines += [
        "",
        "## Measured",
        f"- `events_per_10s`: {s.get('events_per_10s')}",
        f"- `median_hold_s`: {s.get('median_hold_s')}",
        f"- `median_move_s`: {s.get('median_move_s')}",
        f"- `sync_rate`: {s.get('sync_rate')} (chance {s.get('sync_chance')})",
        "",
        "## What we take and what stays theirs",
        "Take the beat grid (`kit/times.gen.ts`), the fitted spring and bezier curves (`kit/dna.gen.ts`), the ink-band hierarchy, and the ground/ink contrast relationship. Leave all original words, marks and footage behind.",
    ]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_dna_cartridge(ref_video: Path, out_dir: Path = None, repo_dir: Path = None, k: int = 5, like: str = None):
    """Fit `ref_video`'s moves and colours into dna.json, kit/dna.gen.ts and REFERENCE.md in `out_dir` (made with
    `vd new --like` when new)."""
    import lean
    import measure
    ref_video = Path(ref_video).resolve()
    if not ref_video.is_file():
        raise SystemExit(f"no such reference video: {ref_video}")

    # 1. Measure the reference video (cached in ~/.vd/measures)
    m_dir = Path.home() / ".vd" / "measures" / ("steal-" + lean.hashlib.sha1(ref_video.read_bytes()).hexdigest()[:12])
    m = json.loads((m_dir / "measure.json").read_text(encoding="utf-8")) if (m_dir / "measure.json").is_file() else {}
    if m.get("version") != measure.VERSION:  # made by another measure.py, or never: its numbers are measured again
        measure.measure(ref_video, m_dir)
        m = json.loads((m_dir / "measure.json").read_text(encoding="utf-8"))

    # 2. Fit optical-flow velocity profiles to physics.ts springs + cubic-beziers
    springs = []
    for mv in m.get("moves") or []:
        sp = fit_spring_profile(mv.get("profile") or [], dur=float(mv.get("dur") or 0.4))
        springs.append({
            "t0": mv["t0"],
            "dur": mv["dur"],
            "peak": mv.get("peak"),
            "ease": mv.get("ease") or [0.2, 0.8, 0.2, 1.0],
            "spring": sp,
            "reliable": bool(mv.get("ease_reliable", True)) and sp["fitted"],
        })
    reliable_springs = [x["spring"] for x in springs if x["reliable"]] or [x["spring"] for x in springs if x["spring"]["fitted"]]
    default_spring = {
        "freq": round(float(np.median([x["freq"] for x in reliable_springs])), 2) if reliable_springs else 2.4,
        "damp": round(float(np.median([x["damp"] for x in reliable_springs])), 2) if reliable_springs else 0.48,
    }
    reliable_beziers = [x["ease"] for x in springs if x["reliable"]] or [[0.2, 0.8, 0.2, 1.0]]
    default_bezier = [round(float(np.median([b[i] for b in reliable_beziers])), 2) for i in range(4)]

    # 3. Extract palette, ink bands, archetype, and beat clock
    palette = extract_palette_and_ink(m)
    # Which worked film this is like is chosen, not measured: on the four accepted films the measures that once picked it
    # named all four `onoma`, and Onoma and Plus One are near twins on every one of them (6.2 and 6.5 events in 10 s,
    # largest type band 0.259 and 0.257). A kind is what a film shows; these numbers are how it moves.
    archetype = like
    arch_reason = "chosen with --like" if like else "not chosen: steal does not guess a kind from the measures"
    near = None
    here = Path(out_dir) if out_dir is not None else lean.film_dir(None, required=False)
    if here is not None and (Path(here) / "kit" / "times.gen.ts").is_file():
        near = (lean.gen_data(Path(here)).get("CLOCK") or {}).get("FB")
    elif like:
        near = (lean.gen_data(TOOLS.parent / "library" / "films" / like).get("CLOCK") or {}).get("FB")
    clock, times, cues = compile_beat_table(m, near_fb=near)
    repo_info = inspect_repo(repo_dir) if repo_dir else None

    # 4. Create or bind target film folder
    if out_dir is None:
        existing = lean.film_dir(None, required=False)
        if existing is not None:
            out_dir = existing
        else:
            stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", (repo_info["name"] if repo_info else ref_video.stem).lower()).strip("-") or "stolen"
            out_dir = Path.cwd() / stem
    out_dir = Path(out_dir).resolve()
    if not (out_dir / "score.json").is_file():
        if not like:
            raise SystemExit(f"vd steal: {out_dir} is not a film folder yet, and steal makes one only as a copy of the worked "
                             "film you name with --like (plusone, stet, onoma or linden; SKILL.md, step 1, says which "
                             "fits): its measures cannot tell the kinds apart. Or run it inside your film folder.")
        class NewArgs:
            name = str(out_dir)
            like = archetype
            kind = None
            bare = False
        lean.cmd_new(NewArgs())

    # 5. Write dna.json, kit/dna.gen.ts, REFERENCE.md, and pin targets in score.json
    dna = {
        "source_video": ref_video.name,
        "width": m.get("w", 1920),
        "height": m.get("h", 1080),
        "fps": m.get("fps", 60.0),
        "duration": m.get("duration", 10.0),
        "archetype": archetype,
        "archetype_reason": arch_reason,
        "clock": clock,
        "times": times,
        "cues": cues,
        "default_spring": default_spring,
        "default_bezier": default_bezier,
        "springs": springs,
        "palette": palette,
        "summary": m.get("summary") or {},
        "segments": m.get("segments") or [],
        "repo": repo_info,
    }
    (out_dir / "dna.json").write_text(json.dumps(dna, indent=1) + "\n", encoding="utf-8")
    (out_dir / "kit").mkdir(parents=True, exist_ok=True)
    ts_lines = [
        "// generated by `vd steal`: moves fitted to springs and curves, and held colours, from " + ref_video.name,
        f"export const DNA_ARCHETYPE = {json.dumps(archetype)} as const;",
        f"export const DNA_CLOCK = {json.dumps(clock)} as const;",
        f"export const DNA_SPRING = {json.dumps(default_spring)} as const;",
        f"export const DNA_BEZIER = {json.dumps(default_bezier)} as [number, number, number, number];",
        f"export const DNA_PALETTE = {json.dumps(palette)} as const;",
        f"export const DNA_MOVES = {json.dumps(springs)} as const;",
        f"export const DNA_TIMES = {json.dumps(times)} as const;",
        f"export const DNA_REPO = {json.dumps(repo_info)} as const;",
    ]
    (out_dir / "kit" / "dna.gen.ts").write_text("\n".join(ts_lines) + "\n", encoding="utf-8", newline="\n")
    write_reference_md(out_dir / "REFERENCE.md", ref_video, dna)

    score = lean.score_of(out_dir)
    score["dna"] = "dna.json"  # `pinned` and `targets` are vd pin's: vd measure reads them in pin's shape, not this one
    (out_dir / "score.json").write_text(json.dumps(score, indent=1) + "\n", encoding="utf-8")
    lean.pin_material(ref_video, lean.outdir(out_dir), k=k)
    return out_dir, dna


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ref", help="reference video file (MP4/MOV/MKV/WEBM)")
    ap.add_argument("--for", dest="repo", help="also record this repository's counts in dna.json (nothing reads them yet)")
    ap.add_argument("--out", help="destination film folder (default: current film folder, or ./<name>)")
    ap.add_argument("--k", type=int, default=5, help="number of 1s busiest motion sheets to extract into pin/")
    ap.add_argument("--like", choices=("plusone", "stet", "onoma", "linden"), help="the worked film to copy when steal makes a new film folder (plusone, stet, onoma, linden): chosen, never guessed")
    a = ap.parse_args(argv)
    out_dir, dna = compile_dna_cartridge(
        Path(a.ref),
        out_dir=Path(a.out) if a.out else None,
        repo_dir=Path(a.repo) if a.repo else None,
        k=a.k,
        like=a.like,
    )
    sp = dna["default_spring"]
    pal = dna["palette"]
    print(f"fitted {Path(a.ref).name} -> {out_dir}")
    print(f"  kind: {dna['archetype'] or '-'} ({dna['archetype_reason']})")
    print(f"  clock: {dna['clock']['BPM']} BPM ({dna['clock']['FB']} frames/beat at {dna['clock']['FPS']} fps), {len(dna['times']['EVENTS'])} snapped events")
    print(f"  spring fit: freq {sp['freq']} Hz, damp {sp['damp']}; bezier {dna['default_bezier']} ({sum(1 for x in dna['springs'] if x['spring']['fitted'])} of {len(dna['springs'])} moves fitted)")
    print(f"  palette: ground {pal['ground']}, ink {pal['ink']}, accent {pal['accent']}, hero band {pal['ink_bands']['hero_share']}")
    if dna.get("repo"):
        r = dna["repo"]
        print(f"  repo cast: {r['name']} ({r['total_code_files']} code files, {r['commits']} commits) — \"{r['tagline']}\"")
    print(f"  wrote: {out_dir / 'dna.json'}, {out_dir / 'kit' / 'dna.gen.ts'}, {out_dir / 'REFERENCE.md'}")
    print(out_dir)


if __name__ == "__main__":
    import utf8  # noqa: F401
    main()
