#!/usr/bin/env python3
"""The documents against the repository: every link lands, every tool and page they name exists, every `vd` step they
give is one `vd.py` has, and every flag they give a tool is one that tool takes.

  python tests/test_docs.py

An agent does what the documents say. A page that names a tool that was renamed, or a flag that was dropped, sends it to
a command that fails, and nothing else notices: the code is fine and its tests pass. This reads the pages the way an
agent would use them, by name, and looks each name up. It is first run on a page with one of each fault planted in it,
so a check that has stopped finding anything fails too.

What it can't tell: whether a sentence about what a tool does is still true. That is what the tools' own tests are for.
"""
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "video-decompiler"
EXAMPLE = SKILL / "examples" / "what-stopped-you"
PAGES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "docs" / "EVIDENCE.md", *sorted(f for f in SKILL.glob("*.md") if ".local." not in f.name)]
SKIP = {"node_modules", "__pycache__", ".git"}

# code files a project, a kit or a render makes, which the pages name and the repository rightly doesn't hold
MADE = {"edit.final.tsx", "edit.first.tsx", "edit.swap.tsx", "beats.ts", "fonts.gen.ts", "card.gen.ts", "styles.gen.ts", "type.gen.ts", "media.gen.ts", "finish.gen.ts", "dna.gen.ts", "puppet.gen.ts", "PuppetPlane.tsx"}
# pages a project or a kit makes
WRITTEN = {"GAP.md", "REPO-FACTS.md", "READINGS.md", "READING.md", "REPORT.md", "BRIEF.md", "DOSSIER.md", "SEE.md", "RIVAL.md", "SOURCES.md", "KIT-README.md", "LENS.local.md", "CLAUDE.md", "AGENTS.md", "REFERENCE.md", "NOTES.md"}
# raea's own flags, which raea_run.py hands on without naming
RAEA = {"--at", "--frame", "--quality", "--kbps", "--manifest", "--input", "--size", "--fps", "--composition"}


def text(page):
    return page.read_text(encoding="utf-8")


def where(page, n=None):
    name = page.relative_to(ROOT).as_posix() if page.is_relative_to(ROOT) else page.name
    return name if n is None else f"{name}:{n}"


def lines(pages):
    for page in pages:
        for n, line in enumerate(text(page).splitlines(), 1):
            yield page, n, line


def dead_links(pages):
    out = []
    for page in pages:
        for target in re.findall(r"\]\(([^)\s]+)\)", text(page)) + re.findall(r'src="([^"]+)"', text(page)):
            if not re.match(r"(https?:|mailto:|#)", target) and not (page.parent / target.split("#")[0]).exists():
                out.append(f"{where(page)}: {target}")
    return out


def missing_code(pages):
    have = {f.name for f in ROOT.rglob("*") if f.is_file() and f.suffix in (".py", ".ts", ".tsx") and not SKIP & set(f.parts)} | MADE
    out = []
    for page, n, line in lines(pages):
        for name in re.findall(r"(?<![\w.*{/-])((?:[\w-]+/)*[\w.-]+\.(?:py|tsx|ts))\b", line):
            base = name.rsplit("/", 1)[-1]
            if base.split(".")[0].isupper() or "NAME" in base or "*" in base:          # a placeholder: ENTRY.tsx, edit.NAME.tsx
                continue
            if base not in have:
                out.append(f"{where(page, n)}: {name}")
    return out


def missing_pages(pages):
    have = {f.name for f in ROOT.rglob("*.md") if not SKIP & set(f.parts)} | WRITTEN
    return [f"{where(page, n)}: {name}" for page, n, line in lines(pages) for name in re.findall(r"`(?:[\w-]+/)*([A-Z][A-Z-]+\.md)`", line) if name not in have]


def vd_steps():
    code = text(SKILL / "tools" / "vd.py")
    lean = text(SKILL / "tools" / "lean.py")  # the lean film folder's commands, which vd.py hands to lean.py
    return (set(re.findall(r'add_parser\("(\w+)"', code)) | set(re.findall(r'\("(\w+)", \w+[,)]', code[code.index("def main"):]))
            | set(re.findall(r'add_parser\("(\w+)"', lean)))


def wrong_steps(pages):
    steps = vd_steps()
    return [f"{where(page, n)}: vd {step}" for page, n, line in lines(pages)
            for step in re.findall(r"\bvd\.py ([a-z]+)\b", line) + re.findall(r"`vd ([a-z]+)\b", line) if step not in steps]


def wrong_flags(pages):
    homes = [SKILL / "tools", SKILL / "library" / "tools", EXAMPLE / "tools", ROOT / "tests"]
    out = []
    for page, n, line in lines(pages):
        mine = [EXAMPLE / "tools"] + homes if EXAMPLE in page.parents else homes       # the example's pages mean its own tools first
        for m in re.finditer(r"\b([\w]+\.py)\b([^`\n]*)", line):
            tool, rest = m.group(1), re.split(r"\b\w+\.py\b", m.group(2))[0]
            rest = re.split(r"\b(?:ffmpeg|ffprobe|raea render|pip)\b", rest)[0]         # the line has gone on to another program's flags
            source = next((d / tool for d in mine if (d / tool).exists()), None)
            if source is None:
                continue                                                               # missing_code says so
            code = text(source)
            for flag in re.findall(r"(?<![\w-])(--[a-z][\w-]*)", rest):
                if f'"{flag}"' not in code and f"'{flag}'" not in code and not (tool == "raea_run.py" and flag in RAEA):
                    out.append(f"{where(page, n)}: {tool} {flag}")
    return out


CHECKS = (("links that lead nowhere", dead_links), ("code files the pages name that aren't in the repository", missing_code), ("pages the pages name that don't exist", missing_pages),
          ("steps the pages give that vd.py doesn't have", wrong_steps), ("flags the pages give a tool that the tool doesn't take", wrong_flags))


def test_each_check_finds_a_planted_fault():
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "PLANTED.md"
        page.write_text("See [the method](NOWHERE/GONE.md) and `FINSH.md`.\nRun `python tools/shet.py FILM --native`, then `vd.py rendr`, then `python tools/sheet.py FILM --nativ`.\n"
                        "This line is fine: `python tools/sheet.py FILM --native`, `vd.py render`, `TRAPS.md`, `ENTRY.tsx`, [raea](https://raea.io).\n", encoding="utf-8")
        found = {what: check([page]) for what, check in CHECKS}
    assert found["links that lead nowhere"] == ["PLANTED.md: NOWHERE/GONE.md"], found
    assert found["code files the pages name that aren't in the repository"] == ["PLANTED.md:2: tools/shet.py"], found
    assert found["pages the pages name that don't exist"] == ["PLANTED.md:1: FINSH.md"], found
    assert found["steps the pages give that vd.py doesn't have"] == ["PLANTED.md:2: vd rendr"], found
    assert found["flags the pages give a tool that the tool doesn't take"] == ["PLANTED.md:2: sheet.py --nativ"], found


def test_the_pages_name_only_what_is_here():
    assert {"new", "look", "sound", "render", "export", "measure", "pin", "profile", "doctor"} <= vd_steps(), vd_steps()
    assert len(PAGES) >= 6, "the pages were found"
    wrong = [f"{what}:\n    " + "\n    ".join(found) for what, check in CHECKS if (found := check(PAGES))]
    assert not wrong, "\n  " + "\n  ".join(wrong)


def test_a_first_run_is_told_what_it_needs():
    # broke: three people new to this, on fresh clones, read `python` and `pip install` on a Mac that has neither, were told
    # to run steps "from the installed folder" a plugin hides. The set-up is the README's; the front page names the commands
    readme, skill = text(ROOT / "README.md"), text(SKILL / "SKILL.md")
    env = re.search(r'VENV = Path\.home\(\) / "([^"]+)" / "([^"]+)"', text(SKILL / "tools" / "vd.py")).groups()
    home = "~/" + "/".join(env)
    assert f"python3 -m venv {home}" in readme and f"{home}/bin/python -m pip install -r" in readme and rf"$HOME\{env[0]}\{env[1]}\Scripts\python" in readme, "the README makes the environment vd.py names, on both kinds of system"
    bare = [f"{where(page, n)}" for page, n, line in lines(PAGES) if re.search(r"(?<!-m )pip install", line)]
    assert not bare, f"a pip install that isn't python -m pip can install into another Python: {bare}"
    assert "ask your agent where the skill is installed" in readme, "the README says how to find the skill"
    named = set(re.findall(r"`vd ([a-z]+)", skill))
    assert named and named == vd_steps() - {"doctor"} | ({"doctor"} & named), f"the front page names exactly the commands vd.py has: page {sorted(named)}, vd.py {sorted(vd_steps())}"


def test_the_licence_goes_where_the_code_goes():
    # broke: the README tells a Codex user to copy only skills/video-decompiler, a kit is a copy of library/, and a part can
    # be lifted out alone. The licence was at the repository's root, so none of the three carried it
    mit = text(ROOT / "LICENSE").replace("\r\n", "\n").strip()
    assert text(SKILL / "LICENSE").replace("\r\n", "\n").strip() == mit, "the skill's folder holds the same licence as the repository"
    library = text(SKILL / "library" / "LICENSE-library.txt")
    assert library.replace("\r\n", "\n").strip().endswith(mit), "and so does the library, which every kit is copied from"
    # and each worked film, which vd new --like copies whole (vd new --kind copies the same file in: tests/test_lean.py)
    for film in sorted(p for p in (SKILL / "library" / "films").iterdir() if p.is_dir()):
        assert (film / "LICENSE-video-decompiler.txt").is_file() and text(film / "LICENSE-video-decompiler.txt") == library, f"{film.name} carries the notice"
    # what the notice says it covers is what the library holds
    covered = library.split("MIT License")[0]
    for part in ("lib", "motions", "transitions", "standins", "starter", "recipes", "films"):
        assert (SKILL / "library" / part).is_dir() and part in covered, part
    assert not re.search(r"\b(methods|layouts|tools|kinds)\b", covered), "no part the library no longer has"


def test_the_library_draws_on_any_machine_and_keeps_to_its_own_traps():
    # M1: the page starter and a recipe named Windows faces (Bahnschrift, Segoe UI, Consolas), which fall back to a serif
    # without a word where they are not installed, while the fonts the library ships were wired to nothing
    import base64
    lib = SKILL / "library"
    faces = text(lib / "lib" / "faces.ts")
    for name, file in (("INTER_700", "inter-700-normal.woff2"), ("INTER_600", "inter-latin-600-normal.woff2"), ("JETBRAINS_MONO", "jetbrains-mono-400-normal.woff2")):
        shipped = base64.b64encode((lib / "media" / "fonts" / file).read_bytes()).decode()
        assert f'export const {name} = "data:font/woff2;base64,{shipped}";' in faces, f"lib/faces.ts embeds {file} as it is shipped"
    code = [f for f in sorted((lib / "starter").rglob("*.tsx")) + sorted((lib / "recipes").glob("*.tsx"))]
    windows = [f"{f.relative_to(SKILL).as_posix()}: {m}" for f in code for line in text(f).splitlines() if not line.lstrip().startswith("//")
               for m in re.findall(r"""["'`][^"'`\n]*\b(?:Bahnschrift|Segoe UI|Consolas|Cascadia|Arial Black)\b""", line)]
    assert not windows, f"faces only Windows has, named in code: {windows}"
    base = text(lib / "starter" / "lean" / "base.tsx")
    assert 'from "./lib/faces"' in base and "export const Faces" in base, "the kit's base embeds the shipped faces"
    for film in ("film.tsx", "app.tsx"):
        assert "<Faces />" in text(lib / "starter" / "lean" / film), f"starter {film} puts the faces in the film"
    # S5: TRAPS.md says a soft shadow above about 1 is noisy, and the later recipe shows 0.6 clean; the older sources had up to 2.5
    soft = [f"{f.relative_to(SKILL).as_posix()}: {v}" for f in lib.rglob("*.tsx") for v in re.findall(r"soft_shadow_size=\{([\d.]+)\}", text(f)) if float(v) > 1.0]
    assert not soft, f"soft shadows above 1: {soft}"
    # S3: render-once.sh was an export route beside vd export that removed the film folder's frames/ and encoded every
    # film at 30 a second; the library holds no shell route of its own
    assert not list(lib.rglob("*.sh")), list(lib.rglob("*.sh"))


PARSE = ("$e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseInput([Console]::In.ReadToEnd(), [ref]$t, [ref]$e); "
         "if ($e) { $e | % { $_.Message }; exit 1 }")


def test_the_hosted_mac_sets_up_by_the_front_pages_own_lines():
    # a check that can't be run is a hope: the three lines the front page gives for macOS and Linux are the lines the
    # hosted Mac runs before its tests, so they cannot go stale unseen
    readme, flow = text(ROOT / "README.md"), text(ROOT / ".github" / "workflows" / "tests.yml")
    block = readme.split("On macOS and Linux", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
    given = [line.strip().replace("SKILL_FOLDER", "skills/video-decompiler") for line in block.splitlines() if line.strip()]
    assert len(given) == 3 and all(line in flow for line in given), f"not run by the hosted Mac: {[line for line in given if line not in flow]}"
    assert "GITHUB_PATH" not in flow, "raea is found where its installer puts it, with nothing set, as the README says"


def test_the_powershell_commands_parse():
    # broke: the Windows set-up lines began with $HOME\..., and PowerShell can't start a command with a variable
    # ("Unexpected token"). Parsed by PowerShell's own parser where there is one; nothing is run
    import shutil
    import subprocess
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        print("PowerShell isn't on this machine, so its blocks weren't parsed")
        return
    blocks = 0
    for page in (ROOT / "README.md", SKILL / "SKILL.md"):
        page_text = text(page)
        for m in re.finditer(r"(?m)^( *)```\w*\n(.*?)^\1```", page_text, re.S):
            if "PowerShell" not in page_text[:m.start()].rstrip().splitlines()[-1]:
                continue
            body = "\n".join(line[len(m.group(1)):] for line in m.group(2).splitlines())
            p = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", PARSE], input=body, capture_output=True, text=True)
            assert p.returncode == 0, f"{page.name}: a PowerShell block doesn't parse: {p.stdout.strip()} {p.stderr.strip()[:300]}\n{body}"
            blocks += 1
    assert blocks >= 1, f"the set-up block for PowerShell was found: {blocks}"


def test_doctors_repair_lines_can_be_pasted():
    # a review's finding: doctor printed its Python's path in quotes and then "-m pip install ...", which PowerShell does
    # not parse without the call operator, and on macOS and Linux it left a home folder with a space in it unquoted
    import shlex
    import shutil
    import subprocess
    import sys
    sys.path.insert(0, str(SKILL / "tools"))
    import vd
    parts = ("/Users/a b/.venvs/video-decompiler/bin/python", "-m", "pip", "install", "-r", "/Users/a b/it's here/requirements.txt")
    assert shlex.split(vd.cmdline(*parts, system="posix")) == list(parts), vd.cmdline(*parts, system="posix")
    home = r"D:\Work of O'Connor"                             # a space and an apostrophe, the two things a path can do to a shell
    win = vd.cmdline(home + r"\python.exe", "-m", "pip", "install", "-r", home + r"\skill\requirements.txt", system="nt")
    assert win.startswith("& '") and "O''Connor" in win, win
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        print("PowerShell isn't on this machine, so doctor's Windows line wasn't parsed")
        return
    p = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", PARSE], input=win, capture_output=True, text=True)
    assert p.returncode == 0, f"doctor's Windows repair line doesn't parse: {p.stdout.strip()} {p.stderr.strip()[:300]} | {win}"


def test_the_evidence_page_counts_the_tests_there_are():
    # the page said 121 tests while the folder held 135: a number in a page goes stale the day a test is added
    files = sorted((ROOT / "tests").glob("test_*.py"))
    count = sum(len(re.findall(r"^def test_", f.read_text(encoding="utf-8"), re.M)) for f in files)
    said = re.search(r"There are (\d+) tests in (\d+) files", (ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8"))
    assert said, "docs/EVIDENCE.md says how many tests there are"
    assert (int(said.group(1)), int(said.group(2))) == (count, len(files)), f"docs/EVIDENCE.md says {said.group(1)} tests in {said.group(2)} files; there are {count} in {len(files)}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("document checks passed")
