#!/usr/bin/env python3
"""The render queue you can see, and the raea it will use: version order (a local build counts below the pin), the
holder's note read back by a waiter, heavy.py refusing while FILMS-RUNNING exists and starting with --now. Uses a
private home folder, so it never touches the machine's real queue. No raea needed.

  python tests/test_queue.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import raea_run  # noqa: E402

# Paths go into the small programs these tests write as Python's own spelling of the string ({str(path)!r}), never between
# quotes typed here: a checkout or a temp folder with an apostrophe in its path (O'Connor) made r'...' a syntax error.


def test_version_order():
    k, pin = raea_run.version_key, raea_run.version_key(raea_run.PIN)
    assert k("0.1.1-rc4") >= pin and k("0.1.1") > pin and k("0.1.2-local-abc") > pin
    assert k("0.1.0-local-1ed49d6") < pin, "the old build on PATH is older than the pin"
    assert k("0.1.1-local-ffff") < pin, "a local build of the pinned number may lack its fixes, so it counts as older"
    assert k("0.1.1-rc3") < pin and k("garbage") is None


def test_the_newest_raea_that_meets_the_pin_is_found_with_no_variable():
    # one film's maker: vd doctor failed until RAEA_BIN was set, and the front page never named it
    from unittest.mock import patch
    versions = {"old": "0.1.0-local-1ed49d6", "rc4": "0.1.1-rc4", "rc3": "0.1.1-rc3"}
    env = {k: v for k, v in os.environ.items() if k not in ("RAEA_BIN", "RAEA_ANY_VERSION")}
    with patch.dict(os.environ, env, clear=True), patch.object(raea_run, "_FOUND", None),             patch.object(raea_run, "candidates", lambda: (["old", "rc4", "rc3"], ["here", "PATH"])),             patch.object(raea_run, "binary_version", lambda p: versions[p]):
        assert raea_run.checked_binary(say=False) == "rc4", "the newest that meets the pin, not the first on PATH"
    with patch.dict(os.environ, env, clear=True), patch.object(raea_run, "_FOUND", None),             patch.object(raea_run, "candidates", lambda: (["old"], ["beside the skill", "~/.raea", "PATH"])),             patch.object(raea_run, "binary_version", lambda p: versions[p]):
        try:
            raea_run.checked_binary(say=False)
            raise AssertionError("an old raea alone is refused")
        except SystemExit as e:
            said = str(e)
            assert "Looked in: beside the skill, ~/.raea, PATH" in said and "Set RAEA_BIN" in said, said


def test_one_pin():
    import re
    said = re.search(r'^RAEA = "([^"]+)"', (TOOLS / "vd.py").read_text(encoding="utf-8"), re.M).group(1)
    assert said == raea_run.PIN, f"vd.py says {said}, raea_run.py enforces {raea_run.PIN}"


def test_holder_note_is_read_back():
    with tempfile.TemporaryDirectory() as tmp:
        lock = Path(tmp) / "q.lock"
        f = raea_run.one_at_a_time(lock=lock, what="cargo build", kind="heavy")
        try:
            pid, cmd, held, kind = raea_run.read_holder(lock)
            assert pid == os.getpid() and cmd == "cargo build" and kind == "heavy" and held < 5
        finally:
            f.close()


def heavy(home, *args):
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    return subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "heavy.py"), *args], capture_output=True, text=True, env=env, timeout=60)


def test_heavy_waits_for_films():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".raea").mkdir()
        (Path(tmp) / ".raea" / "FILMS-RUNNING").write_text("")
        p = heavy(tmp, "--", sys.executable, "-c", "print('ran')")
        assert p.returncode != 0 and "not started" in p.stderr and "ran" not in p.stdout, p
        p = heavy(tmp, "--now", "--", sys.executable, "-c", "print('ran')")
        assert p.returncode == 0 and "ran" in p.stdout, p
        # an encode is not a compile: ffmpeg takes its turn at once even while films are being made
        p = heavy(tmp, "--", "ffmpeg", "-version")
        assert p.returncode == 0 and "ffmpeg version" in p.stdout, p.stderr
        assert "scheduled, never dropped in" in heavy(tmp, "--help").stdout.replace("\n", " ")


def clean_env(**extra):
    return {**{k: v for k, v in os.environ.items() if k != raea_run.HELD}, **extra}


def test_a_child_of_the_holder_does_not_wait_for_its_parent():
    # 03:28: heavy.py held the queue and started measure_film.py, whose transcriber waited for the lock its parent held
    import time
    with tempfile.TemporaryDirectory() as tmp:
        lock = Path(tmp) / "q.lock"
        child = (f"import sys; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                 f"h = raea_run.one_at_a_time(wait=20, lock={str(lock)!r}, kind='heavy'); "
                 f"print('child took its turn under its parent' if h is not None and '.under.' in str(h.lock) else 'child: ' + repr(h))")
        holder = (f"import subprocess, sys; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                  f"h = raea_run.one_at_a_time(wait=20, lock={str(lock)!r}, kind='heavy'); "
                  f"sys.stdout.write(subprocess.run([sys.executable, '-c', {child!r}], capture_output=True, text=True).stdout); h.close()")
        t = time.monotonic()
        p = subprocess.run([sys.executable, "-c", holder], capture_output=True, text=True, env=clean_env(), timeout=60)
        assert "child took its turn under its parent" in p.stdout and time.monotonic() - t < 15, (p.stdout, p.stderr, time.monotonic() - t)
        # a process that is not the holder's descendant waits, even carrying a copy of the holder's mark
        alone = (f"import sys, time; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                 f"h = raea_run.one_at_a_time(wait=20, lock={str(lock)!r}, kind='heavy'); print('held', flush=True); time.sleep(30)")
        other_holder = subprocess.Popen([sys.executable, "-c", alone], stdout=subprocess.PIPE, text=True, env=clean_env())
        try:
            assert other_holder.stdout.readline().strip() == "held"
            other = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; raea_run.one_at_a_time(wait=2, lock={str(lock)!r})"],
                                   capture_output=True, text=True, env=clean_env(**{raea_run.HELD: f"{other_holder.pid}|{lock.resolve()}"}), timeout=60)
            assert other.returncode != 0 and "gave up waiting" in other.stdout + other.stderr, other
        finally:
            other_holder.kill()
            other_holder.wait()
        # letting go takes the mark and the note with it
        h = raea_run.one_at_a_time(wait=20, lock=lock, kind="heavy")
        assert os.environ.get(raea_run.HELD, "").startswith(f"{os.getpid()}|") and raea_run.read_holder(lock)[0] == os.getpid()
        h.close()
        assert raea_run.HELD not in os.environ and raea_run.read_holder(lock) is None


def private_lock(home):
    (Path(home) / ".raea").mkdir(exist_ok=True)
    return Path(home) / ".raea" / "raea_run.lock"


def test_a_heavy_job_that_does_nothing_is_ended_and_lets_the_queue_go():
    import time
    with tempfile.TemporaryDirectory() as tmp:
        lock = private_lock(tmp)
        t = time.monotonic()
        p = heavy(tmp, "--now", "--stall", "3", "--", sys.executable, "-c", "import time; time.sleep(50)")
        assert p.returncode == 3 and "stalled" in p.stdout and time.monotonic() - t < 25, (p.stdout, p.stderr)
        h = raea_run.one_at_a_time(wait=3, lock=lock, kind="heavy")
        assert h is not None, "the queue was let go"
        h.close()
        busy = heavy(tmp, "--now", "--stall", "2", "--", sys.executable, "-c", "import time; t = time.time()\nwhile time.time() - t < 5: pass\nprint('done')")
        assert busy.returncode == 0 and "done" in busy.stdout, (busy.stdout, busy.stderr)


def test_a_heavy_waiter_gives_up_and_goes_when_its_starter_does():
    import time
    import psutil
    with tempfile.TemporaryDirectory() as tmp:
        lock = private_lock(tmp)
        Path(str(lock) + ".rendered").touch()                  # a render just now, so the queue is not idle
        p = heavy(tmp, "--when-idle", "600", "--give-up", "3", "--", sys.executable, "-c", "print('ran')")
        assert p.returncode == 2 and "gave up after" in p.stdout and "did not run" in p.stdout, (p.stdout, p.stderr)
        assert p.stdout.startswith("heavy.py: waiting for the render queue"), "its first line says what it waits for"
        env = clean_env(USERPROFILE=str(tmp), HOME=str(tmp))

        def living(pid):                                       # an ended process nobody has collected yet is not living
            try:
                return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return False

        def outlives(pid, seconds=20):
            t = time.monotonic()
            while living(pid) and time.monotonic() - t < seconds:
                time.sleep(0.5)
            return living(pid)
        # a starter that leaves while its waiter waits (it stays until the waiter's first line is out): the waiter goes too
        said = Path(tmp) / "waiter.txt"
        starter = (f"import subprocess, sys, time\nout = open({str(said)!r}, 'w')\n"
                   f"p = subprocess.Popen([sys.executable, '-X', 'utf8', {str(TOOLS / 'heavy.py')!r}, '--when-idle', '600', '--', "
                   f"sys.executable, '-c', 'print(1)'], stdout=out, stderr=subprocess.DEVNULL)\nt = time.time()\n"
                   f"while time.time() - t < 30 and 'waiting for the render queue' not in open({str(said)!r}).read(): time.sleep(0.1)\nprint(p.pid)")
        pid = int(subprocess.run([sys.executable, "-c", starter], capture_output=True, text=True, env=env, timeout=60).stdout.strip())
        assert not outlives(pid), "the waiter outlived the process that started it"
        assert "the process that started this one has gone" in said.read_text(encoding="utf-8", errors="replace"), said.read_text(encoding="utf-8", errors="replace")
        # a starter gone before its waiter has begun. Windows keeps the starter's number on the waiter, so the waiter
        # knows at once. Linux and macOS hand the waiter to init, which it cannot tell from a starter: there it leaves
        # when --give-up runs out (heavy.py says so), which the first lines of this test covered
        if os.name == "nt":
            starter = (f"import subprocess, sys; p = subprocess.Popen([sys.executable, '-X', 'utf8', {str(TOOLS / 'heavy.py')!r}, '--when-idle', '600', '--', "
                       f"sys.executable, '-c', 'print(1)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print(p.pid)")
            pid = int(subprocess.run([sys.executable, "-c", starter], capture_output=True, text=True, env=env, timeout=60).stdout.strip())
            assert not outlives(pid), "the waiter outlived a starter that left at once"


def test_a_starter_that_has_ended_and_not_been_collected_has_gone():
    # a review's finding: on Linux and macOS a process that has ended and not yet been collected by its parent keeps its
    # number and its start time, and psutil calls it running, so its waiter stayed
    from unittest.mock import patch
    import psutil
    import heavy

    class Proc:
        def __init__(self, state, parent=None):
            self.state, self._parent = state, parent

        def parent(self):
            return self._parent

        def cmdline(self):
            return ["python", self.state]

        def create_time(self):
            return 1.0

        def is_running(self):
            return True

        def status(self):
            return self.state
    for state, gone in ((psutil.STATUS_ZOMBIE, True), (psutil.STATUS_RUNNING, False), (psutil.STATUS_SLEEPING, False)):
        with patch.object(heavy.psutil, "Process", lambda parent=Proc(state): Proc("me", parent)):
            assert heavy.started_by()() is gone, f"a starter that is {state}: gone is {gone}"


def test_two_children_of_one_holder_never_hold_at_once():
    # a review's finding: exempt by ancestry, two render wrappers started by one heavy job both skipped the lock and could draw
    # at once. They now take turns on a lock of the holder's own.
    import time
    with tempfile.TemporaryDirectory() as tmp:
        lock, log = Path(tmp) / "q.lock", Path(tmp) / "log"
        child = (f"import sys, time; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                 f"h = raea_run.one_at_a_time(wait=30, lock={str(lock)!r}, kind='render'); t0 = time.time(); time.sleep(1.5); t1 = time.time(); "
                 f"open({str(log)!r}, 'a').write(f'{{t0}} {{t1}}\\n'); h.close()")
        holder = (f"import subprocess, sys; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                  f"h = raea_run.one_at_a_time(wait=20, lock={str(lock)!r}, kind='heavy'); "
                  f"ps = [subprocess.Popen([sys.executable, '-c', {child!r}]) for _ in range(2)]; [q.wait() for q in ps]; h.close()")
        t = time.monotonic()
        p = subprocess.run([sys.executable, "-c", holder], capture_output=True, text=True, env=clean_env(), timeout=90)
        spans = sorted(tuple(map(float, l.split())) for l in log.read_text().splitlines())
        assert p.returncode == 0 and len(spans) == 2, (p.stdout, p.stderr, spans)
        assert spans[0][1] <= spans[1][0], f"the two children held at the same time: {spans}"
        assert time.monotonic() - t < 30, "and both ran, in turn, without waiting for the holder"


def stamp_code(lock, log, name, hold, extra=""):
    """A made process that takes the queue, writes `name start end` to log, holds `hold` seconds, and lets go."""
    return (f"import sys, time; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; {extra}"
            f"h = raea_run.one_at_a_time(wait=60, lock={str(lock)!r}, kind='render'); t0 = time.time(); time.sleep({hold}); t1 = time.time(); "
            f"open({str(log)!r}, 'a').write(f'{name} {{t0}} {{t1}}\\n'); h.close()")


def spans(log):
    return {l.split()[0]: tuple(map(float, l.split()[1:])) for l in Path(log).read_text().splitlines()}


def test_a_holder_keeps_the_machine_until_its_jobs_finish():
    # a review's finding: the holder closed its lock while its child still drew under it, and an unrelated process took the
    # machine and drew beside the child
    import time
    with tempfile.TemporaryDirectory() as tmp:
        lock, log = Path(tmp) / "q.lock", Path(tmp) / "log"
        child = stamp_code(lock, log, "child", 3.0)
        holder = (f"import subprocess, sys, time; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                  f"h = raea_run.one_at_a_time(wait=20, lock={str(lock)!r}, kind='heavy'); c = subprocess.Popen([sys.executable, '-c', {child!r}]); "
                  f"time.sleep(1.0); print('closing', flush=True); h.close(); print('closed', flush=True); c.wait()")
        hp = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True, env=clean_env())
        assert hp.stdout.readline().strip() == "closing"
        outsider = subprocess.run([sys.executable, "-c", stamp_code(lock, log, "outsider", 0.2)], capture_output=True, text=True, env=clean_env(), timeout=60)
        hp.wait(timeout=60)
        got = spans(log)
        assert outsider.returncode == 0 and set(got) == {"child", "outsider"}, (got, outsider.stderr)
        assert got["outsider"][0] >= got["child"][1] - 0.05, f"the outsider drew while the holder's child was still drawing: {got}"


def test_a_job_admitted_after_its_holder_has_gone_waits_for_the_machine():
    # a review's finding: a child waiting on its holder's own lock when the holder went (here, killed) must not think it is covered
    import time
    import psutil
    with tempfile.TemporaryDirectory() as tmp:
        lock, log = Path(tmp) / "q.lock", Path(tmp) / "log"
        first, second = stamp_code(lock, log, "first", 2.5), stamp_code(lock, log, "second", 0.5)
        holder = (f"import os, subprocess, sys, time; sys.path.insert(0, {str(TOOLS)!r}); import raea_run; "
                  f"h = raea_run.one_at_a_time(wait=20, lock={str(lock)!r}, kind='heavy'); "
                  f"a = subprocess.Popen([sys.executable, '-c', {first!r}]); time.sleep(0.8); b = subprocess.Popen([sys.executable, '-c', {second!r}]); "
                  f"print(os.getpid(), flush=True); time.sleep(60)")
        hp = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True, env=clean_env())
        pid = int(hp.stdout.readline())
        time.sleep(0.8)                                       # "second" is now waiting on the holder's own lock
        psutil.Process(pid).kill()                            # the holder dies without letting go: the system frees the machine
        outsider = subprocess.run([sys.executable, "-c", stamp_code(lock, log, "outsider", 3.0)], capture_output=True, text=True, env=clean_env(), timeout=60)
        t = time.monotonic()
        while len(Path(log).read_text().splitlines()) < 3 and time.monotonic() - t < 30:
            time.sleep(0.25)
        hp.kill()
        got = spans(log)
        assert set(got) == {"first", "second", "outsider"}, got
        o, s2 = got["outsider"], got["second"]
        assert s2[0] >= o[1] - 0.05 or s2[1] <= o[0] + 0.05, f"the second job drew beside the unrelated holder: {got}"


def test_the_stall_watch_is_opt_in():
    # a review's finding: a model loading from disk or work on the graphics card uses little CPU and is not stalled
    with tempfile.TemporaryDirectory() as tmp:
        assert "(default: off)" in " ".join(heavy(tmp, "--help").stdout.split())


def test_the_stall_watch_counts_only_cpu_actually_used():
    # a review's finding: a total over living descendants falls when a busy worker exits, and the fall read as the next stage idle
    sys.path.insert(0, str(TOOLS))
    import heavy as hv
    last = {}
    add, last = hv.accumulate(last, {10: 1.0, 11: 50.0})          # the job and a busy worker
    assert add == 51.0
    add, last = hv.accumulate(last, {10: 1.1, 12: 0.4})           # the worker has gone; the next stage has started
    assert abs(add - 0.5) < 1e-9, f"the next stage's 0.4 s and the job's 0.1 s, nothing taken off for the worker: {add}"
    add, last = hv.accumulate(last, {10: 1.1, 12: 0.4})
    assert add == 0.0


def test_a_renderer_that_could_not_be_tied_to_its_command_is_said():
    # a review's risk: when Windows refused to tie the renderer's life to the command, nothing was checked and nothing
    # was said, and a stopped command could leave its renderer at work with the queue open to the next
    import contextlib
    import io
    import os
    import subprocess
    import types
    if os.name != "nt":
        assert raea_run.die_with_us(types.SimpleNamespace(_handle=0)) is None
        return
    said = io.StringIO()
    with contextlib.redirect_stderr(said):
        raea_run.die_with_us(types.SimpleNamespace(_handle=0))      # no such process: the tie fails
    assert "could not tie" in said.getvalue() and "stopped too" in said.getvalue(), said.getvalue()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            job = raea_run.die_with_us(child)
        assert job and said.getvalue() == "", f"a real child is tied and nothing is said: {said.getvalue()!r}"
    finally:
        child.kill()
        child.wait()


if __name__ == "__main__":
    import utf8  # noqa: F401
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
