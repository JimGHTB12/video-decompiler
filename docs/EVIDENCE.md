# The record behind the front page

The front page makes claims. This page is the record behind them: who made what, what was tested, what the tests showed, and what nobody has checked. Everything here happened on 12 and 13 November 2026. These were exploratory runs, not a benchmark: where a number comes from one run, it says so.

## Who did what

James Dimachkie directed this and judged it. Coding agents wrote it: the tools, the pages and the films' code were typed by Claude models, and reviewed in several rounds by a model from another family (GPT) before release. The commit names Claude as co-author for that reason.

What was the person's:

- the aim, the kinds of film, and which films by other makers were worth learning from;
- watching the cuts of the four films alone, at speed, with the sound on, and saying what was wrong. Plus One took 6 cuts, Stet 10, Onoma 4, Linden 5;
- the rules the work ran under. No film reaches the person until blind readers have read it. Nothing ships that changes a film he accepted. Every report says what nobody did.

What was the agents': everything typed, and the reviews of each other's work.

## The four accepted films

"Accepted" means that one person, the one each film was made for, watched it and said yes. Nobody else has judged them. Each film's folder under [`library/films`](../skills/video-decompiler/library/films) holds its board (written before any code), what one round of blind readers changed, and its known limits. Click a film on the front page to watch it with its sound.

## The four films, made again from this repository

A worked film ships whole, so the claim can be measured: copy it with `vd new`, run `vd export`, and hold the file against the cut the person accepted. Done on Windows with raea 0.1.1-rc4, the day of release:

| film | picture, against the accepted cut | sound |
|---|---|---|
| Stet | all 1,728 frames the same | the same, sample for sample |
| Onoma | all 1,740 frames the same | no sample different; the export's track ends 8 ms sooner, in silence |
| Plus One | 641 of 2,304 frames the same (654 and 511 in two earlier runs); the others at a PSNR of 46 dB or better | the mix is the same file, byte for byte; the export carries it 0.75 dB lower, to keep its peak under the limit |
| Linden | 578 of 1,800 frames the same (623 and 1,136 in two earlier runs); the others at a PSNR of 44.6 dB or better | no sample different; the export's track ends 5 ms sooner, in silence |

The two that do not match to the last frame are the two built on large pictures. raea does not draw those the same to the last bit twice, so the count of matching frames changes from run to run. Measured on Plus One on the day of release: 128 frames drawn twice from the same code, with no encoding, differed in 116, by at most two levels of 255; one frame drawn five times came out five ways.

So when a change to such a film has to be shown to change nothing, one export held against another cannot show it. For the last change to Plus One, four things did: every changed expression equals the number it replaced; the 644 frames before the pictures arrive are identical as drawn; raea's record of every text on all 2,304 frames is the same byte for byte; and for each of six later frames, drawn five times with each version, the new code drew a picture that is byte for byte one the old code drew. `TRAPS.md` has the method.

## Starting cold

The test of a skill is what a fresh agent makes with it. Five times, a fresh agent was given the skill, one paragraph about a made-up meal-planning app, and a film the person admires to hold its own against; from the third test on, also four screens of real apps of that kind to look at. Nothing else. From the second test on, the agent took its film through the skill's own blind readers and its own fixes before any person saw it. No person stepped in during a run: each agent worked alone from its brief until it stopped.

The paragraph, as given in tests 3 to 5 (tests 1 and 2 asked for "a launch film like the one in the material folder", had a different film there, and had no sentence about food):

> Make me a launch film for Larder, held against the studio film in the material folder. Larder is a meal-planning app for a household: the week's seven dinners sit on one page; you open a day and swap the dish, and the shopping list rewrites itself; at the end you send the list to whoever is doing the shop. Larder is made up, so invent its interface and its names, but nothing a viewer would take for a real company's fact. I want it to look like a real, finished product, with food you can see. 30 to 40 seconds, 1920 by 1080, music and no voice.

The skill changed between tests, which was their purpose. This repository's history is one commit, so those earlier states cannot be checked from here.

| test | made by | the skill it was given | minutes | tool calls | its two line-up readers | the person, afterwards |
|---|---|---|---|---|---|---|
| 1 | Claude Opus 5.5 | the first candidate | 25 | 102 | none: it stopped at its first cut | nothing recorded |
| 2 | Claude Opus 5.5 | corrected after test 1 | 57 | 94 | both ranked it below the accepted film | "it looks like it was made by a freelance motion designer" |
| 3 | Claude Fable 5.2 | as test 2, with later fixes | 75 | 185 | both below the accepted film | the best of the first four |
| 4 | Claude Opus 5.5 | with `WORLD.md`, material first, several cuts | 87 | not counted | both below the accepted film | below test 3 |
| 5 | Claude Fable 5.2 | the release candidate of 13 November | 101 | 247 | both below the accepted film | tests 3 and 5 are "close to the level of the others"; "the typography could be a little better" |

[Test 3's film](media/test3.mp4) is here to watch, with its sound, as its agent left it (a 720p copy; [its sources](media/test3-sources.md)). Test 5's is not: nine of its ten photographs were confirmed CC0 in their catalogues' own records on the day of release, and the record for the tenth could not be read again, so that film stays out until it can.

What the table shows:

- In all four tests that reached readers, both readers ranked the test film below the accepted film beside it: eight readings, none the other way.
- A film taken through readers took 57 to 101 minutes and 94 to 247 tool calls. Tokens were not counted.
- The two films the person placed closest to the four were the two made by the stronger model.

## One model, one brief, one idea

Tests 3 and 5 had the same model, the same paragraph and the same material. Only the skill differed: several pages were added between them. The second agent never saw the first film; its session log names no file outside its own folders. Both films open on the same question, use the same lines, and stage the same shot of a phone between two words.

So running an agent again does not give a second idea. A different film has to come from different material or a different film to hold it against. This is one pair, not a rate.

The pair was then read blind by two readers from two families of model, with an accepted film in the same line-up and the letters dealt differently for each reader:

| reader | first | second | third |
|---|---|---|---|
| Claude Opus 5.5 | test 5 | test 3 | Plus One |
| GPT-6.1 Sol | Plus One | test 5 | test 3 |

Both readings are [here in full](READINGS.md). Both put the later film above the earlier one, and for the same reason: its parts have room to move, where the earlier film's collide. The person called the differences minor. So the pages added between the two tests did no harm that anyone could find, and no good that the person could see.

## What a reader model is worth

- **Its rank against an accepted film held.** In all four tests both readers put the test film below it, and the person agreed on the ones he watched.
- **Its label did not.** Readers answer "who made this?" with one of four labels. Three readers of four called the best accepted film the work of "a freelance motion designer", the same label they gave test films.
- **Readers of stills prefer room.** One reader ranked the film the person likes best last of three, for being full. A reader from another family ranked it first. This is why the skill asks for two readers from different models, ranks against an accepted film, and tells the agent never to choose between good films by a reader's rank.
- **Readers cannot hear, and they read stills**: the whole film at two frames a second, and every frame of its five busiest seconds. They misjudged the size of text until the briefs told them how wide a tile is.

## What the engine's own record is worth

`vd look` reports from raea's record of what it drew (each text's box, each layer's mask), not from pixels. It finds text off the frame and layers that never showed. It cannot see text lying over a picture: in test 5, two readers found a title crossing a photograph that the report had passed.

## Tests, and what clean machines found

There are 137 tests in 23 files, each built on an input with a fault planted in it. Until the day before release they had run on one laptop only. Their first run on hosted machines failed on Linux and on Windows. Two tests had assumed things about that laptop: an optional package, and how a temp folder is spelled. One showed a real limit on Linux in a helper: a waiting job cannot always tell that the process that started it has gone. The tool's notes now say so.

On the day of release a model from another family than the one that wrote the tools reviewed their code. It found twelve bugs and five risks. The twelve are mended, eleven with a test. Three of the risks are mended too. A second review, of everything changed in the tools since the last tested release, found five more faults, all in code written that day; those are mended with tests of their own. The two risks left are on the front page, under "When something goes wrong".

Since then every change runs on Linux, Windows and macOS, and once more on a Mac that installs raea as a stranger would, sets up by the README's own lines, runs every test with nothing skipped and then exports a short film whole. raea's installer gives pre-releases too: on the day of release that Mac got 0.1.2 in the morning and 0.1.3-rc4 in the afternoon, and passed on both. From then on it runs twice: on 0.1.2, which must pass, and on whatever the installer gives that day, which is watched.

The four films were also drawn with the raea they were accepted on (0.1.1-rc4) and with 0.1.2, the release of that day: 24 moments, and one busy moment of each at full size, compared pixel for pixel on Windows. No pixel differed.

## What is not known

- What the skill adds over an agent given raea and no skill. Nobody has run that comparison.
- Whether anyone but one person finds the four films good.
- Whether the skill works for a real product. All nine films are for made-up ones.
- Which pages matter. The one controlled pair differed by several pages at once, and the person found the two films close. No page has been taken away to see what breaks.
- Whether the record of how the four films set type (in `BOARD.md`) changes the type of a film started cold.
- How the films sound to anyone else. No agent can hear: levels are checked, tunes are not.
- A worked film exported whole on a Mac (the short starter film was; the four have only been drawn there at sampled moments), and anything rendered on Linux.
- What a film costs in tokens.

## Checking this yourself

- The films: click one on the front page, or render one on your machine with the README's "A first film".
- A blind line-up: `vd pack FILM.mp4 --against OTHER.mp4`, then the readers' briefs in [`EYES.md`](../skills/video-decompiler/EYES.md), word for word.
- The tests: `python tests/run.py`.
