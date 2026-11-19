#!/usr/bin/env python3
"""Run every test in this folder and say what passed, what failed and what was skipped.

  python tests/run.py [NAME ...] [--jobs N] [--timeout 900]

Each test file is a script: it builds small inputs with known answers (a video with a planted stutter, a kit with a
planted leak), runs one tool on them, and exits 0 if the tool found what was planted. This runs each in its own process,
several at once (--jobs, default up to 4; --jobs 1 runs them one after another), so a list of tests in a README can
never fall behind the folder. Each process gets its own output folders (VD_OUT, VD_READS), so two tests that name a film
folder alike cannot meet in ~/.vd; renders still take raea's queue one at a time, as they do outside the tests. Tests
that need raea or bun say "skipped" when it isn't installed, and that is counted as skipped, not passed. Give names to
run only some of them: `python tests/run.py scan pack`. A name that is a test's own name runs that test alone (`queue`
is test_queue.py, not test_render_queue.py); any other name runs every test whose name contains it.

Needs ffmpeg and the packages in skills/video-decompiler/requirements.txt.
"""
import argparse
import concurrent.futures
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent

# Started first so a late heavy file (test_see, test_worked_films) does not run alone after the rest finish; never sort
# by file size, which puts test_run.py's waiting stand-in ahead of the one that wakes it.
SLOW = ("alien_features", "new_check_faults", "audio_faults", "see", "worked_films", "pack")


CREATE_SUSPENDED = 0x00000004
DRAIN = 10.0   # seconds to collect a stopped test's output: a pipe a stray process still holds must not hold the run


def _tie_job(proc):
    """Put a Windows test process in a job object so orphaned grandchildren are caught, or raise OSError. The process
    is started suspended and resumed only once it is in the job (run_one): attached after it had started, a test that
    spawned a child and exited at once left the child outside the job (a review's finding)."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("a", ctypes.c_longlong), ("b", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("c", ctypes.c_size_t),
                    ("d", ctypes.c_size_t), ("e", wintypes.DWORD), ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IO), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    info = EXT()
    info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if job and k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) and k.AssignProcessToJobObject(job, int(proc._handle)):
        return job
    err = ctypes.get_last_error()
    if job:
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle(job)
    raise OSError(f"could not put the test in a job object (Windows error {err})")


def _job_pids(job):
    if os.name != "nt" or not job:
        return []
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    k.QueryInformationJobObject.restype = wintypes.BOOL
    cap = 256
    for _ in range(3):
        class PIDLIST(ctypes.Structure):
            _fields_ = [("assigned", wintypes.DWORD), ("count", wintypes.DWORD), ("pids", ctypes.c_size_t * cap)]
        pl = PIDLIST()
        if k.QueryInformationJobObject(job, 3, ctypes.byref(pl), ctypes.sizeof(pl), None):
            return [int(pl.pids[i]) for i in range(pl.count)]
        if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
            return []
        cap = max(cap * 2, int(pl.assigned) + 32)
    return []


def _close_job(job):
    if os.name == "nt" and job:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle(job)


def _group_procs(pgid):
    """The processes of one POSIX process group."""
    found = []
    for q in psutil.process_iter():
        try:
            if os.getpgid(q.pid) == pgid:
                found.append(q)
        except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
            pass
    return found


def _stop_tree(proc, job):
    """Kill and reap the test process, its children, and any orphaned grandchildren before removing its folder."""
    procs = {}
    if proc.poll() is None:   # once it has been reaped its number may be another process's
        try:
            parent = psutil.Process(proc.pid)
            for q in parent.children(recursive=True) + [parent]:
                procs[q.pid] = q
        except psutil.NoSuchProcess:
            pass
    for pid in _job_pids(job):
        if pid not in procs:
            try:
                procs[pid] = psutil.Process(pid)
            except psutil.NoSuchProcess:
                pass
    if os.name == "nt" and job:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.TerminateJobObject(job, 1)
        for pid in _job_pids(job):
            if pid not in procs:
                try:
                    procs[pid] = psutil.Process(pid)
                except psutil.NoSuchProcess:
                    pass
    elif os.name != "nt":
        # the test is its own session, so its group still holds what it left once it has ended. Found before the kill,
        # so that they are waited for below: killed and not waited for, one was still alive when run_one returned
        for q in _group_procs(proc.pid):
            procs.setdefault(q.pid, q)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for q in _group_procs(proc.pid):   # and again, as the Windows branch does: one started between the look and the kill
            procs.setdefault(q.pid, q)
    for q in list(procs.values()):
        try:
            q.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):   # gone, or one Windows will not end twice: the job ended it
            pass
    proc.wait(timeout=30)
    psutil.wait_procs(list(procs.values()), timeout=10)


def run_one(f, timeout):
    """One test file in its own process with its own output folders: (code, output, seconds)."""
    t0 = time.time()
    own = Path(tempfile.mkdtemp(prefix=f"vd-{f.stem}-"))
    tmp = own / "tmp"
    tmp.mkdir()
    env = {**os.environ, "VD_OUT": str(own / "out"), "VD_READS": str(own / "reads"),
           "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp)}
    p, job = None, None
    try:
        # on Windows the test is started suspended, put in its job, then let run: nothing it starts can escape the job
        p = subprocess.Popen([sys.executable, "-X", "utf8", str(f)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env,
                             start_new_session=(os.name != "nt"), creationflags=CREATE_SUSPENDED if os.name == "nt" else 0)
        try:
            job = _tie_job(p)
        except OSError as e:
            p.kill()
            p.communicate(timeout=DRAIN)
            return 125, f"{e}: the test was not run", time.time() - t0
        if os.name == "nt":
            psutil.Process(p.pid).resume()
        try:
            stdout, stderr = p.communicate(timeout=timeout)
            code, out = p.returncode, stdout + stderr
        except subprocess.TimeoutExpired:
            _stop_tree(p, job)
            try:
                stdout, stderr = p.communicate(timeout=DRAIN)
            except subprocess.TimeoutExpired:   # a pipe still held by a process outside the tree: what came is enough
                stdout, stderr = "", f"(its output pipe was still held after {DRAIN:.0f} s)"
            code, out = 124, f"took longer than {timeout:.0f} s\n" + (stdout + stderr)[-2000:]
    finally:
        if p is not None:
            # every process the test left, ended and waited for, on a pass too: the temp folder is removed only when
            # nothing holds it (a passing test's child kept 11 of 12 folders open past their removal, a review's finding)
            _stop_tree(p, job)
        _close_job(job)
    left = _remove(own)
    if left:
        code, out = (code or 126), out + f"\nrun.py: could not remove the test's own folder {own}: {left}"
    return code, out, time.time() - t0


def _remove(folder, patience=5.0):
    """Remove a test's own folder; '' when it went, else why not, once `patience` seconds of retries are over (a file a
    virus scanner still has open goes in a moment; one a process the runner could not end holds does not)."""
    end = time.monotonic() + patience
    while True:
        try:
            shutil.rmtree(folder)
            return ""
        except FileNotFoundError:
            return ""
        except OSError as e:
            if time.monotonic() > end:
                return str(e)
            time.sleep(0.2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="run only these tests: a test's own name, or part of several names")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1), help="test files run at once (1: in turn)")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds one test file may take")
    a = ap.parse_args()
    every = sorted(HERE.glob("test_*.py"), key=lambda f: (SLOW.index(f.stem[5:]) if f.stem[5:] in SLOW else len(SLOW), f.name))
    stems = {f.stem for f in every}

    def matches(f, n):
        # `queue` is test_queue.py and nothing else; only a name that is no test's own name picks every test containing it
        return f.stem in (n, "test_" + n) if {n, "test_" + n} & stems else n in f.stem

    missing = [n for n in a.names if not any(matches(f, n) for f in every)]
    if missing:
        raise SystemExit("no test matches " + ", ".join(missing))
    files = [f for f in every if not a.names or any(matches(f, n) for n in a.names)]
    if not files:
        raise SystemExit("no tests found")
    passed, failed, skipped, started = [], [], [], time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        running = {pool.submit(run_one, f, a.timeout): f for f in files}
        for done in concurrent.futures.as_completed(running):   # each reported as it ends; the summary is in name order
            f = running[done]
            code, out, took = done.result()
            if code != 0:
                failed.append(f.name)
                print(f"FAIL     {f.name}  ({took:.0f} s)")
                print("         " + "\n         ".join(out.strip().splitlines()[-25:]), flush=True)
            elif (why := next((l.strip() for l in out.splitlines() if l.strip().lower().startswith("skipped:")), "")):
                skipped.append(f.name)
                print(f"skipped  {f.name}  ({why})", flush=True)
            else:
                passed.append(f.name)
                print(f"ok       {f.name}  ({took:.0f} s)", flush=True)
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped, in {time.time() - started:.0f} s.")
    if failed:
        print("failed: " + ", ".join(sorted(failed)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
