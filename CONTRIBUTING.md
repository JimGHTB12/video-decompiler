# Contributing

Thanks for wanting to. This page is short because the rules are few.

## Before you start

- For anything bigger than a fix, open an issue first and say what you want to change and why. It saves you writing something that doesn't fit.
- Run the tests: `python tests/run.py`. They need ffmpeg and the packages in `skills/video-decompiler/requirements.txt`, and no graphics card. The few that render say "skipped" without raea.

## The rules this repository keeps

1. **A tool is tested against a fault with a known answer.** A test builds a tiny input with something planted in it (a stutter, a dropped picture, a leak) and asserts that the tool finds it, and that it stays quiet on a clean input. A new tool comes with such a test. A fix comes with the smallest input that used to break it.
2. **A claim has a number and says how it was measured.** "Tracks a push within 0.74 px" is a claim. "Works well" isn't. If you didn't measure it, say so.
3. **One fact lives in one place.** If a number, a file format or a rule is needed in two files, one of them reads it from the other. Two copies drift, and most of the faults found in this repository were two copies that had drifted.
4. **A check that can't be run is a hope.** If the documents tell an agent to do something, a tool should be able to tell whether it was done, or the report should have to say that it wasn't.
5. **Plain words.** The documents are read by agents and by people who are new to this. Short sentences, the common word, no jargon without a gloss.
6. **Say what nobody did.** If nobody has watched it or listened to it, the pull request says so.

## What not to send

- Videos, music, sound effects, fonts or pictures you don't have the right to redistribute. Tests make their own inputs with ffmpeg.
- Anything cut from someone else's film.
- Keys, tokens, or paths from your own machine.

## Pull requests

Say what was wrong, in the words of someone who hit it, then what is true now, then how you proved it. Small is good. A pull request that changes behaviour says so in its first lines.

## A note you'd give a film

If you used the skill and the film it made had a fault a tool could have caught, that's the most useful thing you can send. Describe the fault and attach the smallest thing that shows it. The method here is that every such note becomes a check or a line in `TRAPS.md`.
