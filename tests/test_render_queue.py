#!/usr/bin/env python3
"""raea_run.py lets one render run at a time on a machine.

  python tests/test_render_queue.py

Three renders at once ran an 8 GB graphics card out of memory and stopped Windows, twice in one afternoon. So a second
render waits for the first. This checks the wait itself, without raea: it needs no renderer.
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import raea_run  # noqa: E402

# a lock file of the test's own, so the test neither waits for nor holds up a real render on this machine
LOCK = Path(tempfile.mkdtemp()) / "test.lock"
# and the queue's folder too: render() stamps QUEUE/raea_run.lock.rendered when it lets go, which heavy.py --when-idle
# reads, so a test that reached the real folder told the machine's waiting jobs a render had just ended
raea_run.QUEUE = LOCK.parent
ENTRY = LOCK.with_name("unused.tsx")  # a composition that is there, as render() refuses one that isn't
ENTRY.write_text("")
# the second render here stands for another maker's, not a child of the first: it starts without the holder's mark
OTHER = {k: v for k, v in os.environ.items() if k != raea_run.HELD}
SECOND = (f"import sys, time; sys.path.insert(0, r'{TOOLS}'); import raea_run; t = time.time(); "
          f"f = raea_run.one_at_a_time(wait=30, lock=r'{LOCK}'); print('got it after %.1f s' % (time.time() - t))")


def test_a_second_render_waits_for_the_first():
    first = raea_run.one_at_a_time(wait=30, lock=LOCK)
    assert first is not None, "the queue is on unless RAEA_RUN_ALONE=0"
    second = subprocess.Popen([sys.executable, "-c", SECOND], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**OTHER})
    time.sleep(2.5)
    assert second.poll() is None, "the second render should still be waiting while the first holds the machine"
    first.close()                                          # the first render ends
    out, err = second.communicate(timeout=30)
    assert "got it after" in out and float(out.split()[3]) >= 2.0, out
    assert "queue: waiting" in err and "held by" in err, "and it says what it is waiting for"


def test_a_waiting_look_goes_before_a_waiting_render():
    """A look is seconds and a render is minutes: with both waiting, the look gets the machine first."""
    lock = Path(tempfile.mkdtemp()) / "looks.lock"
    code = lambda kind: (f"import sys, time; sys.path.insert(0, r'{TOOLS}'); import raea_run; "
                         f"f = raea_run.one_at_a_time(wait=30, lock=r'{lock}', kind='{kind}'); print(time.time(), flush=True); time.sleep(1.5)")
    first = raea_run.one_at_a_time(wait=30, lock=lock)
    render = subprocess.Popen([sys.executable, "-c", code("render")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**OTHER})
    time.sleep(1.2)                                        # the render is already waiting when the look arrives
    look = subprocess.Popen([sys.executable, "-c", code("look")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**OTHER})
    time.sleep(1.8)
    first.close()
    got_look, got_render = float(look.communicate(timeout=30)[0].split()[0]), float(render.communicate(timeout=30)[0].split()[0])
    assert got_look < got_render, f"the look should hold the machine first (look {got_look:.2f}, render {got_render:.2f})"
    assert got_render - got_look >= 1.0, "and the render waits until the look has finished"


def test_the_queue_can_be_turned_off():
    code = (f"import os, sys; os.environ['RAEA_RUN_ALONE'] = '0'; sys.path.insert(0, r'{TOOLS}'); import raea_run; "
            f"print(raea_run.one_at_a_time(lock=r'{LOCK}') is None)")
    held = raea_run.one_at_a_time(wait=30, lock=LOCK)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    held.close()
    assert done.stdout.strip() == "True", done.stdout + done.stderr


class FakeChild:
    """Stands in for raea: writes the line a finished render writes, and any frames asked for, and ends when told to."""
    started = []

    def __init__(self, args, stdout=None, **kw):
        FakeChild.started.append(args)
        out = Path(args[args.index("-o") + 1])
        if "--at" in args:
            for i in range(len(args[args.index("--at") + 1].split(","))):
                Image.new("RGB", (8, 8)).save(out / f"frame-{i:05d}.png")
        stdout.write("APPLIED fake render\n")
        stdout.flush()
        self.pid, self.returncode = 0, None

    def poll(self):
        if FakeChild.ends_at_once:  # read at each look, so the test can end it part way
            self.returncode = 0
        return self.returncode

    ends_at_once = True


class Clock:
    """Time the test controls. `jump` is how far the wall clock leaps at each look, as when the system clock is corrected."""

    def __init__(self, jump=0.0, on_sleep=None):
        self.t, self.jump, self.leapt, self.slept, self.on_sleep = 0.0, jump, 0.0, 0, on_sleep

    def monotonic(self):
        return self.t

    def time(self):
        self.leapt += self.jump
        return 1e9 + self.t + self.leapt

    def sleep(self, s):
        self.t += s
        self.slept += 1
        if self.on_sleep:
            self.on_sleep(self)


def no_raea():
    """Everything render() reaches outside Python, replaced, so nothing real runs."""
    fake = SimpleNamespace(Popen=FakeChild, DEVNULL=subprocess.DEVNULL, STDOUT=subprocess.STDOUT)
    return [patch.object(raea_run, "subprocess", fake), patch.object(raea_run, "raea_binary", lambda: "raea"), patch.object(raea_run, "checked_binary", lambda say=True: "raea"),
            patch.object(raea_run, "binary_version", lambda path: raea_run.PIN),
            patch.object(raea_run, "die_with_us", lambda proc: None), patch.object(raea_run, "kill_tree", lambda proc: None)]


def test_a_direct_caller_waits_for_a_render():
    # broke once: a picture check (render_check.py, since cut) called raea_run.render directly, and only the command line
    # took the lock, so it drew frames beside another render on the same card. Any caller of render() must wait.
    real = raea_run.one_at_a_time
    held = real(wait=30, lock=LOCK)
    FakeChild.started, FakeChild.ends_at_once, got = [], True, []
    with contextlib.ExitStack() as stack:
        for p in no_raea() + [patch.object(raea_run, "one_at_a_time", lambda wait=3600.0, lock=None, **kw: real(wait=30, lock=LOCK))]:
            stack.enter_context(p)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "still.png"
            t = threading.Thread(target=lambda: got.append(raea_run.render(ENTRY, out, ["--frame", "0"])), daemon=True)
            t.start()
            time.sleep(2.0)
            assert not FakeChild.started, "a direct caller waits while another render holds the machine"
            held.close()
            t.join(30)
    assert FakeChild.started and got, "and draws once the machine is free"
    again = real(wait=0.5, lock=LOCK)
    assert again is not None, "and lets the machine go when it's done"
    again.close()


def test_the_command_line_takes_the_lock_once():
    # the lock can't be taken twice by one process, so the command line leaves it to render(), or it would wait for itself
    real, taken = raea_run.one_at_a_time, []
    out = Path(tempfile.mkdtemp()) / "out.mp4"
    entry = out.with_name("entry.tsx")
    entry.write_text("")  # the command line refuses an entry that isn't there
    FakeChild.ends_at_once = True
    with contextlib.ExitStack() as stack:
        for p in no_raea() + [patch.object(raea_run, "one_at_a_time", lambda wait=3600.0, lock=None, **kw: taken.append(1) or real(wait=3, lock=LOCK)),
                              patch.object(sys, "argv", ["raea_run.py", str(entry), "-o", str(out)]), contextlib.redirect_stdout(io.StringIO())]:
            stack.enter_context(p)
        try:
            raea_run.main()
        except SystemExit as e:
            code = e.code
    assert code == 0 and taken == [1], f"one render, one lock: exit {code}, taken {len(taken)} times"


def test_a_render_that_ends_while_waiting_is_not_a_stall():
    # broke: after its one-second sleep the loop went straight to the time limit without asking whether raea had finished,
    # so a render that ended in that second could be killed and counted as stalled
    def finish(clock):
        clock.t += 10  # the second ran long, past the limit, and raea finished in it
        FakeChild.ends_at_once = True
    FakeChild.ends_at_once = False
    with contextlib.ExitStack() as stack:
        for p in no_raea() + [patch.object(raea_run, "time", Clock(on_sleep=finish)), patch.object(raea_run, "cpu_seconds", lambda proc: 100.0),
                              patch.object(raea_run, "LOCK", tempfile.TemporaryFile())]:  # as if this process already held the machine
            stack.enter_context(p)
        ok, _, msg, _ = raea_run.render(ENTRY, Path(tempfile.mkdtemp()) / "out.mp4", timeout=5.0, retries=0)
    assert ok and "APPLIED" in msg, f"a render that finished is a render that worked: {msg}"


def test_a_clock_correction_does_not_end_the_wait():
    # broke: the queue timed its wait by the wall clock, so a clock set forward an hour ended the wait at once
    held = raea_run.one_at_a_time(wait=30, lock=LOCK)
    clock = Clock(jump=4000.0)
    try:
        with patch.object(raea_run, "time", clock), contextlib.redirect_stderr(io.StringIO()):
            raea_run.one_at_a_time(wait=5, lock=LOCK)
        raise AssertionError("the lock is held, so the wait should run out")
    except SystemExit:
        pass
    finally:
        held.close()
    assert clock.slept >= 5, f"it waited {clock.slept} s of a 5 s allowance"


def test_where_raea_and_its_output_are():
    # broke: a relative RAEA_BIN (./bin/raea) was handed to raea started from the composition's folder, where it pointed at
    # nothing; and an output with a dot in its name (stills.v1) was taken for a file, so its folder was never made and raea
    # stopped
    import os
    d = Path(tempfile.mkdtemp())
    (d / "bin").mkdir()
    (d / "bin" / "raea").write_text("")
    here = os.getcwd()
    os.chdir(d)
    try:
        with patch.dict(os.environ, {"RAEA_BIN": os.path.join("bin", "raea")}):
            found = raea_run.raea_binary()
    finally:
        os.chdir(here)
    assert Path(found).is_absolute() and Path(found) == (d / "bin" / "raea").resolve(), f"raea by its full path: {found}"
    FakeChild.started, FakeChild.ends_at_once = [], True
    with contextlib.ExitStack() as stack:
        for p in no_raea() + [patch.object(raea_run, "LOCK", tempfile.TemporaryFile())]:
            stack.enter_context(p)
        ok, _, msg, _ = raea_run.render(ENTRY, d / "stills.v1", ["--at", "0,1"], timeout=5.0, retries=0)
        assert ok and len(list((d / "stills.v1").glob("frame-*.png"))) == 2, f"a stills folder is made before raea starts, whatever its name: {msg}"
        assert FakeChild.started[-1][FakeChild.started[-1].index("-o") + 1].endswith(os.sep), "and raea is told it is a folder"
        raea_run.render(ENTRY, d / "film.mp4", timeout=5.0, retries=0)
        assert not (d / "film.mp4").is_dir() and not FakeChild.started[-1][FakeChild.started[-1].index("-o") + 1].endswith(os.sep), "a film is still a file"


def test_bad_arguments_delete_nothing():
    # broke: raea_run.py cleared -o before it knew raea could start, so `raea_run.py final.mp4 -o edit.final.tsx` deleted the
    # film's source, and a missing entry with -o precious.mp4 deleted the film. This Python stands in for raea: it fails.
    import os
    d = Path(tempfile.mkdtemp())
    for name in ("edit.final.tsx", "final.mp4", "precious.mp4"):
        (d / name).write_text("keep me")
    env = dict(os.environ, RAEA_BIN=sys.executable, RAEA_RUN_ALONE="0")
    for args in (["final.mp4", "-o", "edit.final.tsx"], ["missing.tsx", "-o", "precious.mp4"], ["edit.final.tsx", "-o", "edit.final.tsx"], ["edit.final.tsx", "-o", "out.ts"]):
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "raea_run.py"), *args], cwd=d, env=env, capture_output=True, text=True)
        assert p.returncode != 0 and "Nothing was deleted" in p.stderr, f"{args} is refused: {p.stdout} {p.stderr}"
        assert all((d / n).read_text() == "keep me" for n in ("edit.final.tsx", "final.mp4", "precious.mp4")), f"{args} deleted a file"


def test_raeas_own_short_flags_reach_raea():
    # broke: the wrapper's parser took raea's --h (the height) as short for its own --help, printed its help and exited
    # 0 without rendering; abbreviations are off, so --h, --w and --fps go to raea untouched
    import os
    d = Path(tempfile.mkdtemp())
    (d / "film.tsx").write_text("export {};")
    env = dict(os.environ, RAEA_BIN=sys.executable, RAEA_RUN_ALONE="0")
    p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "raea_run.py"), "film.tsx", "-o", "out.mp4", "--h", "90"],
                       cwd=d, env=env, capture_output=True, text=True)
    assert "show this help message" not in p.stdout + p.stderr, "--h is raea's, not the wrapper's --help"


def test_every_caller_is_refused_before_anything_is_deleted():
    # broke: only the command line checked its arguments, so raea_run.render("missing.tsx", "precious.mp4"), as other tools
    # call it, deleted the film before raea refused the entry; and --at=0,1 was taken for a single file where --at 0,1
    # was a folder of stills
    d = Path(tempfile.mkdtemp())
    (d / "precious.mp4").write_text("keep me")
    with contextlib.ExitStack() as stack:
        for p in no_raea() + [patch.object(raea_run, "LOCK", tempfile.TemporaryFile())]:
            stack.enter_context(p)
        try:
            raea_run.render(d / "missing.tsx", d / "precious.mp4", timeout=5.0, retries=0)
            raise AssertionError("a missing entry is refused")
        except SystemExit as e:
            assert "Nothing was deleted" in str(e), e
    assert (d / "precious.mp4").read_text() == "keep me", "and the film is still there"
    assert raea_run.stills(d / "frames.png", ["--at=0,1"]) and raea_run.stills(d / "frames.png", ["--at", "0,1"]), "both spellings of --at are a folder of stills"


def main():
    for t in (test_a_second_render_waits_for_the_first, test_a_waiting_look_goes_before_a_waiting_render, test_the_queue_can_be_turned_off, test_a_direct_caller_waits_for_a_render,
              test_the_command_line_takes_the_lock_once, test_a_render_that_ends_while_waiting_is_not_a_stall, test_a_clock_correction_does_not_end_the_wait,
              test_where_raea_and_its_output_are, test_bad_arguments_delete_nothing, test_raeas_own_short_flags_reach_raea,
              test_every_caller_is_refused_before_anything_is_deleted):
        t()
        print("ok", t.__name__)
    print("render queue checks passed")


if __name__ == "__main__":
    main()
