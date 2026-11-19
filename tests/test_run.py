#!/usr/bin/env python3
"""tests/run.py prints each test's line as that test finishes, even when its output goes to a pipe.

  python tests/test_run.py

An agent runs the suite through a pipe. Python holds a pipe's output until it has a block of it, so a run of about ten
minutes printed nothing until the end, and looked hung.

This runs a copy of run.py over two stand-in tests. The second waits for a file that this test makes only once it has read
the first test's line, so the check doesn't depend on how fast the machine is: if run.py held its output, the first line
would never come while the second test waits, and the second would give up and fail.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix="O'Connor ") as tmp:  # the user's temp folder can hold a quote
        d = Path(tmp)
        shutil.copy(HERE / "run.py", d / "run.py")
        flag = d / "first line read"
        (d / "test_a.py").write_text("print('a done')\n", encoding="utf-8")
        (d / "test_b.py").write_text(
            "import sys, time\nfrom pathlib import Path\n"
            f"flag = Path({str(flag)!r})\n"  # repr, so a temp folder with a quote in it (O'Connor) is still a string
            "for _ in range(600):\n    if flag.exists():\n        print('b done'); sys.exit(0)\n    time.sleep(0.1)\n"
            "print('the first line never came while this test ran'); sys.exit(1)\n", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(d / "run.py")], stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        first = p.stdout.readline()
        flag.write_text("")
        rest = p.stdout.read()
        p.wait()
    assert "test_a.py" in first, f"the first test's line comes first: {first!r}"
    assert p.returncode == 0 and "ok       test_b.py" in rest, f"and it came while the second test still ran: {first!r} {rest[-300:]!r}"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        shutil.copy(HERE / "run.py", d / "run.py")
        for name in ("test_a.py", "test_pack.py", "test_see.py", "test_alien_features.py"):
            (d / name).write_text("print('done')\n", encoding="utf-8")
        done = subprocess.run([sys.executable, str(d / "run.py"), "--jobs", "1"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        order = [l.split()[1] for l in done.stdout.splitlines() if l.startswith("ok ")]
    assert order == ["test_alien_features.py", "test_see.py", "test_pack.py", "test_a.py"], f"named slow files start before alphabetical ones: {order}"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        shutil.copy(HERE / "run.py", d / "run.py")
        (d / "test_a.py").write_text("from pathlib import Path; Path('ran').write_text(''); print('done')\n", encoding="utf-8")
        bad = subprocess.run([sys.executable, str(d / "run.py"), "a", "not_a_real_test", "--jobs", "1"],
                             cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert bad.returncode != 0 and "not_a_real_test" in (bad.stdout + bad.stderr) and not (d / "ran").exists(), (
            f"an unknown selector is refused before running matches: {bad.returncode} {bad.stdout!r} {bad.stderr!r}")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        shutil.copy(HERE / "run.py", d / "run.py")
        (d / "test_a.py").write_text("print('1 passed, 0 failed, 0 skipped')\n", encoding="utf-8")
        (d / "test_b.py").write_text("print('skipped: tool not here')\n", encoding="utf-8")
        done = subprocess.run([sys.executable, str(d / "run.py"), "--jobs", "1"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert done.returncode == 0 and "ok       test_a.py" in done.stdout and "skipped  test_b.py" in done.stdout and "1 passed, 0 failed, 1 skipped" in done.stdout, (
            f"only explicit skipped: lines count as skipped: {done.stdout!r}")
    import runpy
    import psutil
    runner = runpy.run_path(str(HERE / "run.py"))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        pids = d / "pids"
        script = d / "test_timeout.py"
        script.write_text(
            "import subprocess, sys, time\nfrom pathlib import Path\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
            "g = int(subprocess.check_output([sys.executable, '-c', "
            "\"import subprocess, sys; q = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print(q.pid)\"], text=True))\n"
            f"Path({str(pids)!r}).write_text(f'{{c.pid}} {{g}}')\n"
            "time.sleep(10)\n",
            encoding="utf-8",
        )
        code, out, took = runner["run_one"](script, 1.0)
        alive = []
        for pid in map(int, pids.read_text(encoding="utf-8").split()):
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    alive.append(pid)
                    proc.kill()
                    proc.wait(5)
            except psutil.NoSuchProcess:
                pass
        assert code == 124 and took < 8 and not alive, f"timeout kills and reaps the tree: code={code} took={took:.2f} alive={alive}"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        leaked = d / "leaked.txt"
        script = d / "test_leak.py"
        script.write_text(
            "import tempfile\nfrom pathlib import Path\n"
            "made = tempfile.mkdtemp(prefix='vd-fb4-leak-')\n"
            f"Path({str(leaked)!r}).write_text(made, encoding='utf-8')\n",
            encoding="utf-8",
        )
        code, out, _ = runner["run_one"](script, 10.0)
        made = Path(leaked.read_text(encoding="utf-8"))
        still_there = made.exists()
        if still_there:
            shutil.rmtree(made, ignore_errors=True)
        assert code == 0 and not still_there, f"mkdtemp inside a test is removed with run_one's folder: {made}"
    for check in (a_child_started_at_once_is_in_the_job, a_passing_tests_folder_goes_once_its_child_has_ended, a_held_pipe_does_not_hold_the_run,
                  a_kill_that_is_refused_does_not_stop_the_runner):
        check(runner)
    print("run checks passed")


def _gone(pid):
    """Whether process `pid` has ended; one still running is ended here, so a failed check leaves nothing behind."""
    import psutil
    try:
        q = psutil.Process(pid)
        if q.is_running() and q.status() != psutil.STATUS_ZOMBIE:
            q.kill()
            try:
                q.wait(5)
            except psutil.TimeoutExpired:   # on Linux and macOS: killed, and a parent still running has not collected it
                if q.status() != psutil.STATUS_ZOMBIE:
                    raise
            return False
    except psutil.NoSuchProcess:
        pass
    return True


def a_child_started_at_once_is_in_the_job(runner):
    # a review's finding: the test ran before its Windows job was attached, so a test that started a child and ended at
    # once left the child outside the job. The attach is delayed here on purpose, as a busy machine can schedule it:
    # started suspended, the test cannot have run in that time
    g = runner["run_one"].__globals__
    real_tie = g["_tie_job"]
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        pid_file = d / "child.pid"
        script = d / "test_quick.py"
        script.write_text("import subprocess, sys\nfrom pathlib import Path\n"
                          "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                          f"Path({pid_file.as_posix()!r}).write_text(str(c.pid))\n", encoding="utf-8")
        g["_tie_job"] = lambda p: (time.sleep(0.35), real_tie(p))[1]
        try:
            code, out, _ = runner["run_one"](script, 10.0)
        finally:
            g["_tie_job"] = real_tie
        child = int(pid_file.read_text(encoding="utf-8")) if pid_file.exists() else None
        assert child is not None and _gone(child) and code == 0, f"a child started at once is in the job and ended with it: code={code} child={child} {out[-300:]}"


def a_passing_tests_folder_goes_once_its_child_has_ended(runner):
    # a review's finding: on a pass the runner removed the test's own folder while a child it had just ended still held
    # a file in it (11 of 12 folders were left). Closing the job ends the child a moment later; to make that moment as
    # long as it can be, the job is not closed here, so only ending and waiting for the child first lets the folder go
    g = runner["run_one"].__globals__
    real_close = g["_close_job"]
    held_jobs = []
    with tempfile.TemporaryDirectory() as tmp:
        g["_close_job"] = held_jobs.append
        ready = Path(tmp) / "ready"
        script = Path(tmp) / "test_holds.py"
        script.write_text("import os, subprocess, sys, time\nfrom pathlib import Path\n"
                          "code = \"import os, time; from pathlib import Path; f = open(os.path.join(os.environ['TEMP'], 'held.txt'), 'w'); "
                          f"Path({ready.as_posix()!r}).write_text('1'); time.sleep(30)\"\n"
                          "c = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                          f"while not Path({ready.as_posix()!r}).exists():\n    time.sleep(0.05)\n"
                          "print('own', os.environ['TEMP'])\nprint('child', c.pid)\n", encoding="utf-8")
        try:
            code, out, _ = runner["run_one"](script, 30.0)
        finally:
            g["_close_job"] = real_close
        own = Path(next(l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("own "))).parent
        left = own.exists()
        _gone(int(next(l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("child "))))
        for job in held_jobs:
            real_close(job)
        if left:
            time.sleep(1)
            shutil.rmtree(own, ignore_errors=True)
        assert code == 0 and not left, f"a passing test's folder goes once its child has been ended: code={code} left={left} {out[-300:]}"


def a_kill_that_is_refused_does_not_stop_the_runner(runner):
    # a review's finding: Windows refuses to end a process its job has just ended (AccessDenied), and the refusal went
    # up through run_one's clean-up, which runs after every test, and stopped the runner. Here every kill is refused
    # once it has been done
    import psutil
    stop = runner["run_one"].__globals__["_stop_tree"]
    real = psutil.Process.kill

    def refused(self):
        real(self)
        raise psutil.AccessDenied(self.pid)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=(os.name != "nt"))
    psutil.Process.kill = refused
    try:
        stop(child, None)
    finally:
        psutil.Process.kill = real
        if child.poll() is None:
            child.kill()
            child.wait(10)
    assert child.returncode is not None, "the child is ended and waited for"


def a_held_pipe_does_not_hold_the_run(runner):
    # a review's finding: after a timeout the output was collected without limit while a process the runner had not
    # ended still held the pipe. Here nothing is ended (the tree stop is replaced), so only the limit can end the wait
    g = runner["run_one"].__globals__
    real_stop, real_drain = g["_stop_tree"], g.get("DRAIN")
    with tempfile.TemporaryDirectory() as tmp:
        pid_file = Path(tmp) / "holder.pid"
        script = Path(tmp) / "test_pipe.py"
        script.write_text("import subprocess, sys, time\nfrom pathlib import Path\n"
                          "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
                          f"Path({pid_file.as_posix()!r}).write_text(str(c.pid))\n"
                          "time.sleep(20)\n", encoding="utf-8")
        g["_stop_tree"], g["DRAIN"] = (lambda p, job: None), 0.5
        try:
            t0 = time.time()
            code, out, _ = runner["run_one"](script, 1.0)
            took = time.time() - t0
        finally:
            g["_stop_tree"], g["DRAIN"] = real_stop, real_drain
            if pid_file.exists():
                holder = int(pid_file.read_text(encoding="utf-8"))
                if os.name != "nt":     # nothing was ended above, and no job closes here: the test's own group, script and holder
                    try:
                        os.killpg(os.getpgid(holder), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                _gone(holder)
        assert code == 124 and took < 8, f"a held pipe does not hold the run: code={code} took={took:.1f} s"

if __name__ == "__main__":
    main()
