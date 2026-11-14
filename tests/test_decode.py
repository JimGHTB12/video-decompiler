#!/usr/bin/env python3
"""A damaged film is an error to every tool that reads its pictures, never a result from part of it.

  python tests/test_decode.py

ffmpeg reading a film cut short or with a hole in it exits 0, says "Invalid NAL unit size" on stderr and hands over what
it could: half the pictures, or all of them broken. scan.py checked only the exit status (and the export then passed the
film), sheet.py and measure_film.py not even that, so a reader's packet or a measure could be made from half a film.
Planted here: a film cut at half its bytes, and one with 4000 bytes zeroed in its middle.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "skills" / "video-decompiler" / "tools"
sys.path.insert(0, str(TOOLS))
import decode  # noqa: E402
import lean  # noqa: E402
import measure_film  # noqa: E402
import scan  # noqa: E402


def films(tmp):
    ok = tmp / "ok.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(ok)], check=True)
    data = ok.read_bytes()
    cut, hole = tmp / "cut.mp4", tmp / "hole.mp4"
    cut.write_bytes(data[:len(data) // 2])
    mid = len(data) // 2
    hole.write_bytes(data[:mid] + bytes(4000) + data[mid + 4000:])
    return ok, cut, hole


def refused(fn, *args):
    try:
        out = fn(*args)
        if hasattr(out, "__next__"):
            list(out)
    except SystemExit as e:
        return str(e)
    return None


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ok, cut, hole = films(tmp)
        assert decode.frame_count(ok) == 180 and len(scan.changes(ok)) == 179, "a whole film reads whole"
        for bad in (cut, hole):
            said = refused(scan.changes, bad)
            assert said and "nothing is made from it" in said, f"scan refuses {bad.name}: {said}"
            said = refused(measure_film.frames, bad, 48, 27)
            assert said and "nothing is made from it" in said, f"measure_film refuses {bad.name}: {said}"
            for how in (["--native", "--from", "0", "--to", "6"], ["--fps", "4"]):
                out = tmp / f"sheet-{bad.stem}-{how[0][2:]}.jpg"
                p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "sheet.py"), str(bad), "-o", str(out), *how, "--cols", "4", "--rows", "2", "--width", "160"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                left = sorted(tmp.glob(f"sheet-{bad.stem}-{how[0][2:]}*.jpg"))
                assert p.returncode != 0 and not left and "nothing is made from it" in p.stderr, f"sheet.py {how[0]} on {bad.name}: {p.returncode} {left} {p.stderr[-300:]}"
        # a stretch asked for alone reads whole, and a caller that stops early stops ffmpeg without an error
        p = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "sheet.py"), str(ok), "-o", str(tmp / "fine.jpg"), "--native", "--from", "1", "--to", "2",
                            "--cols", "8", "--rows", "4", "--width", "160"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert p.returncode == 0 and (tmp / "fine.jpg").is_file(), p.stderr
        cmd = ["ffmpeg", "-v", "error", "-i", str(ok), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
        for k, _ in enumerate(decode.pictures(cmd, 320 * 180, "ok.mp4")):
            if k == 2:
                break
        assert refused(lambda: list(decode.pictures(cmd, 320 * 180 + 7, "ok.mp4"))), "a picture cut off part way is an error"
        # the export's scan of a damaged film says it did not run, and leaves no old report standing as this film's
        report = tmp / "scan.txt"
        report.write_text("SCAN old.mp4: ok\n", encoding="utf-8")
        assert lean.scanned(cut, report) is None
        assert "NOT scanned" in report.read_text(encoding="utf-8") and "ok" not in report.read_text(encoding="utf-8").split(":")[0], report.read_text(encoding="utf-8")
    print("decode checks passed")


if __name__ == "__main__":
    import utf8  # noqa: F401
    main()
