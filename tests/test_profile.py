#!/usr/bin/env python3
"""tools/profile_run.py on a small made-up session: a command that names a folder called C-sleep-on-it is not waiting
(the old rule counted a whole film as waiting), another agent's work is its own class, and the split it prints reads the
render-queue minutes from the tools' own output (raea_run's "queue: waiting N s").

  python tests/test_profile.py
"""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"


def at(s):
    return f"2026-11-12T07:{s // 60:02d}:{s % 60:02d}.000Z"


def use(t, mid, cid, name, inp, stop="tool_use"):
    return {"type": "assistant", "timestamp": at(t), "message": {"id": mid, "stop_reason": stop, "content": [{"type": "tool_use", "id": cid, "name": name, "input": inp}]}}


def result(t, cid, text):
    return {"type": "user", "timestamp": at(t), "message": {"content": [{"type": "tool_result", "tool_use_id": cid, "content": text}]}}


def test_a_session():
    queue = "\n".join(f"queue: waiting {n} s; held by pid 7 (render), holding it 1.0 min: raea_run.py other.tsx" for n in (0, 30, 60, 90))
    log = [
        {"type": "user", "timestamp": at(0), "message": {"content": "Make the film."}},
        use(1, "m1", "c1", "Bash", {"command": 'cat "showcase/C-sleep-on-it/SCORE.md"'}),
        result(3, "c1", "the score"),
        use(5, "m2", "c2", "Agent", {"prompt": "write two routes"}),
        result(20, "c2", "two routes"),
        use(22, "m3", "c3", "Bash", {"command": "python tools/raea_run.py film.tsx -o out/film.mp4 --composition film"}),
        result(130, "c3", queue + "\nOK 20.0s APPLIED  300 frames rendered to out/film.mp4"),
        {"type": "assistant", "timestamp": at(135), "message": {"id": "m4", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "s.jsonl").write_text("\n".join(json.dumps(e) for e in log), encoding="utf-8")
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "profile_run.py"), str(tmp / "s.jsonl"), "-o", str(tmp / "p")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert p.returncode == 0, p.stdout + p.stderr
        steps = list(csv.DictReader(open(tmp / "p" / "steps.csv", encoding="utf-8")))
        assert steps[0]["class"] == "read", f"naming C-sleep-on-it is not waiting: {steps[0]['class']}"
        assert steps[1]["class"] == "agents", f"another agent's work is its own class: {steps[1]['class']}"
        split = json.load(open(tmp / "p" / "profile.json", encoding="utf-8"))["split"]
        assert split["render_queue"] == 1.5, f"90 s in the queue, read from raea_run's own lines: {split}"
        assert "split (min):" in p.stdout and "render queue 1.5" in p.stdout, p.stdout
        assert "own minutes are in their own logs and are not counted" in p.stdout, "the profile says what it leaves out"


def profile(log, tmp, *window):
    (tmp / "s.jsonl").write_text("\n".join(json.dumps(e) for e in log), encoding="utf-8")
    p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "profile_run.py"), str(tmp / "s.jsonl"), "-o", str(tmp / "p"), *window],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout + p.stderr
    return json.load(open(tmp / "p" / "profile.json", encoding="utf-8"))["split"]


EXCLUSIVE = ("making", "rework", "looking", "render_queue", "heavy_job", "engine", "reporting", "agents", "pages", "not_classed", "waiting_other", "replies")


def test_the_split_is_exclusive_and_adds_up():
    # a review's finding: one 60-second look reported making 1.0, looking 1.0 and total 1.0: episode minutes were counted, then looks again
    log = [
        {"type": "user", "timestamp": at(0), "message": {"content": "Look at it."}},
        use(0, "m1", "c1", "Read", {"file_path": "out/look.jpg"}),
        {"type": "user", "timestamp": "2026-11-12T07:01:00.000Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "c1", "content": "picture"}]}},
        {"type": "assistant", "timestamp": "2026-11-12T07:01:00.000Z", "message": {"id": "m2", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Looked at the frame."}]}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        sp = profile(log, Path(tmp))
    assert sp["looking"] == 1.0 and sp["making"] == 0.0, sp
    assert abs(sum(sp[k] for k in EXCLUSIVE) - sp["total"]) <= 0.15, f"the classes add up to the total: {sp}"


def test_the_first_full_render_is_the_whole_film_not_a_long_range():
    # a review's finding: any render of 120 frames or more became "the first full render" (a 4-second range did), and a whole film
    # shorter than that was missed, so the making that followed was counted as rework
    log = [
        {"type": "user", "timestamp": at(0), "message": {"content": "Make the film."}},
        use(1, "m1", "c1", "Bash", {"command": "python tools/raea_run.py _range.tsx -o out/range-0-120.mp4 --composition range"}),
        result(10, "c1", "OK 3.0s APPLIED  120 frames rendered to out/range-0-120.mp4"),
        {"type": "assistant", "timestamp": at(12), "message": {"id": "t1", "content": [{"type": "text", "text": "Drawing the next shot's layout."}]}},
        use(12, "m2", "c2", "Write", {"file_path": "film.tsx", "content": "x"}),
        result(30, "c2", "written"),
        use(31, "m3", "c3", "Bash", {"command": "python tools/raea_run.py main.tsx -o out/film.mp4 --composition film"}),
        result(40, "c3", "OK 2.0s APPLIED  90 frames rendered to out/film.mp4"),
        {"type": "assistant", "timestamp": at(42), "message": {"id": "m4", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        sp = profile(log, Path(tmp))
    assert sp["first_full_render_min"] is not None and abs(sp["first_full_render_min"] - 39 / 60) < 0.05, f"the 90-frame film, not the range: {sp}"
    assert sp["rework"] == 0.0 and sp["making"] > 0, f"the drawing before the film is making: {sp}"


def test_a_background_render_and_its_queue_wait():
    # makers run a render in the background, wait on it, then read its output: the queue wait it reports happened while
    # they waited, not in the two-second read, and the read is where its "frames rendered" shows up
    log = [
        {"type": "user", "timestamp": at(0), "message": {"content": "Render the film."}},
        use(1, "m1", "c1", "Bash", {"command": "python tools/raea_run.py main.tsx -o out/film.mp4 --composition film", "run_in_background": True}),
        result(2, "c1", "Command running in background with ID: b1"),
        use(3, "m2", "c2", "mcp__t3-code__t3_background_wait", {"taskIds": ["b1"]}),
        result(110, "c2", "completed"),
        use(111, "m3", "c3", "Bash", {"command": "tail -3 out/b1.output"}),
        result(113, "c3", "queue: waiting 0 s; held by pid 7 (render), holding it 1.0 min: x\nqueue: waiting 90 s; held by pid 7 (render), "
                          "holding it 2.5 min: x\nOK 9.0s APPLIED  90 frames rendered to out/film.mp4"),
        {"type": "assistant", "timestamp": at(115), "message": {"id": "m4", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        sp = profile(log, Path(tmp))
    assert sp["render_queue"] == 1.5, f"the 90 s wait is taken out of the time spent waiting: {sp}"
    assert sp["first_full_render_min"] is not None and abs(sp["first_full_render_min"] - 112 / 60) < 0.05, f"the read that shows it rendered: {sp}"
    assert abs(sum(sp[k] for k in EXCLUSIVE) - sp["total"]) <= 0.15, sp


def test_vd_look_and_export_count_as_renders():
    # G: "renders 0 (1343s)": the skill's own commands were render steps that counted no renders
    log = [{"type": "user", "timestamp": at(0), "message": {"content": "Make the film."}},
           use(1, "m1", "c1", "Bash", {"command": "python tools/vd.py look --at 1,2"}), result(20, "c1", "LOOK look.jpg"),
           use(21, "m2", "c2", "Bash", {"command": "python tools/vd.py export"}), result(80, "c2", "picture rendered once in 50.0 s"),
           {"type": "assistant", "timestamp": at(81), "message": {"id": "m3", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}}]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "s.jsonl").write_text("\n".join(json.dumps(e) for e in log), encoding="utf-8")
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "profile_run.py"), str(tmp / "s.jsonl"), "-o", str(tmp / "p")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert p.returncode == 0, p.stderr
        steps = list(csv.DictReader(open(tmp / "p" / "steps.csv", encoding="utf-8")))
    assert [s["renders"] for s in steps] == ["1", "1"], [(s["class"], s["renders"]) for s in steps]
    assert "renders 2 (" in p.stdout, p.stdout


def test_a_background_export_and_a_written_film_count():
    # Round: `vd export` run in the background was never seen as the first full render, Write of film.tsx counted as
    # nothing, times printed in UTC with no zone, and "not classed" said nothing of what it held
    note = {"type": "user", "timestamp": at(200), "message": {"content": "<task-notification><task-id>abc123</task-id>"
            "<status>completed</status><summary>Background command completed (exit code 0)</summary></task-notification>"}}
    log = [{"type": "user", "timestamp": at(0), "message": {"content": "Make the film."}},
           use(1, "m1", "c1", "Write", {"file_path": "film/film.tsx", "content": "x"}), result(60, "c1", "File created"),
           use(61, "m2", "c2", "Bash", {"command": "python tools/vd.py export --sound sound.wav"}),
           result(62, "c2", "Command running in background with ID: abc123. Output is being written to: x"),
           use(63, "m3", "c3", "Bash", {"command": "ls"}), result(90, "c3", "a b"),
           {"type": "assistant", "timestamp": at(91), "message": {"id": "m4", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Waiting."}]}},
           note,
           {"type": "assistant", "timestamp": at(205), "message": {"id": "m5", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}}]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "s.jsonl").write_text("\n".join(json.dumps(e) for e in log), encoding="utf-8")
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "profile_run.py"), str(tmp / "s.jsonl"), "-o", str(tmp / "p")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert p.returncode == 0, p.stderr
        sp = json.load(open(tmp / "p" / "profile.json", encoding="utf-8"))["split"]
    assert sp["first_full_render_min"] is not None and abs(sp["first_full_render_min"] - 200 / 60) < 0.05, sp
    assert sp["making"] >= 0.9, f"writing film.tsx is making: {sp}"
    assert "run times are this machine's clock (" in p.stdout and "not classed, by kind of step" in p.stdout, p.stdout


def test_a_vd_look_is_a_render_and_holds_its_queue_wait():
    # one film's maker looked through `vd look`: its queue wait had no render step to sit in, so it couldn't be placed
    log = [
        {"type": "user", "timestamp": at(0), "message": {"content": "Look."}},
        use(1, "m1", "c1", "Bash", {"command": "python tools/vd.py look --at 1,2"}),
        result(80, "c1", "LOOK out/look.jpg 1920x540, 2 tiles  total 78.00s (queue 60.00s, raea 17.00s, sheet 1.00s)"),
        {"type": "assistant", "timestamp": at(82), "message": {"id": "m2", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Seen."}]}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        sp = profile(log, Path(tmp))
    assert sp["render_queue"] == 1.0 and sp["queue_not_placed"] == 0.0, sp


def test_a_window_inside_a_long_session():
    # a film made inside a long session (18 minutes of a longer one): --since opens the window, usually inside
    # a turn, so the window's own first entry starts a run; without that the film would count as nothing
    log = [{"type": "user", "timestamp": at(0), "message": {"content": "Make several films."}}]
    for k, t in enumerate(range(0, 600, 60)):
        log += [use(t + 1, f"m{k}", f"c{k}", "Bash", {"command": f"python tools/vd.py look --at {k}"}), result(t + 51, f"c{k}", "LOOK look.jpg")]
    log.append({"type": "assistant", "timestamp": at(610), "message": {"id": "end", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}})
    with tempfile.TemporaryDirectory() as tmp:
        whole = profile(log, Path(tmp))
        late = profile(log, Path(tmp), "--since", "2026-11-12T07:05:00Z")
        mid = profile(log, Path(tmp), "--since", "2026-11-12T07:05:00Z", "--until", "2026-11-12T07:08:00Z")
    assert abs(whole["total"] - 610 / 60) <= 0.05, whole
    assert abs(late["total"] - (610 - 301) / 60) <= 0.05, f"from the first entry in the window to the end: {late}"
    assert abs(mid["total"] - (471 - 301) / 60) <= 0.05, f"from the first entry in the window to the last before --until: {mid}"
    for sp in (late, mid):
        assert abs(sum(sp[k] for k in EXCLUSIVE) - sp["total"]) <= 0.1 + 1e-9, f"the window's classes add up to it: {sp}"


def test_a_film_named_e2_is_not_sound_and_vd_through_a_variable_is_a_render():
    # one film's maker named the folder E2-clearing and ran the skill as VD=.../vd.py; "$VD" look: every step that named the
    # folder counted as sound work (an old keyword, a pitch called E2), and the skill's own commands were not renders
    sys.path.insert(0, str(TOOLS))
    import profile_run
    cls = profile_run.classify("Bash", {"command": 'cd "showcase/E2-clearing/clearing" && wc -l film.tsx'})[0]
    assert cls != "sound", cls
    for cmd in ('VD="tools/vd.py"; "$VD" look --at 1,2', 'python "${VD}" export', "python $vd sound"):
        assert profile_run.classify("Bash", {"command": cmd})[0] == "render", cmd
    assert profile_run.classify("Bash", {"command": 'python "$VD" export'})[1] == "film"


if __name__ == "__main__":
    sys.path.insert(0, str(TOOLS))
    import utf8  # noqa: F401
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
