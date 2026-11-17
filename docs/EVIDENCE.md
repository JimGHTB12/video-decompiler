# The record behind the front page

The front page makes claims. This page is the record behind them: who made what, what was tested, what the tests showed, and what nobody has checked. Everything here happened on 12 and 13 November 2026, with a sixth cold-start test added on 16 November 2026. These were exploratory runs, not a benchmark: where a number comes from one run, it says so.

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

The test of a skill is what a fresh agent makes with it. Six times, a fresh agent was given the skill, one paragraph about a made-up meal-planning app, and a film the person admires to hold its own against; from the third test on, also four screens of real apps of that kind to look at. Nothing else. From the second test on, the agent took its film through the skill's own blind readers and its own fixes before any person saw it. No person stepped in during a run: each agent worked alone from its brief until it stopped.

The paragraph, as given in tests 3 to 6 (tests 1 and 2 asked for "a launch film like the one in the material folder", had a different film there, and had no sentence about food):

> Make me a launch film for Larder, held against the studio film in the material folder. Larder is a meal-planning app for a household: the week's seven dinners sit on one page; you open a day and swap the dish, and the shopping list rewrites itself; at the end you send the list to whoever is doing the shop. Larder is made up, so invent its interface and its names, but nothing a viewer would take for a real company's fact. I want it to look like a real, finished product, with food you can see. 30 to 40 seconds, 1920 by 1080, music and no voice.

The skill changed between tests, which was their purpose. Earlier states before commit `57a7525`, the first public release, cannot be checked from this repository's history.

| test | made by | the skill it was given | minutes | tool calls | its two line-up readers | the person, afterwards |
|---|---|---|---|---|---|---|
| 1 | Claude Opus 5.5 | the first candidate | 25 | 102 | none: it stopped at its first cut | nothing recorded |
| 2 | Claude Opus 5.5 | corrected after test 1 | 57 | 94 | both ranked it below the accepted film | "it looks like it was made by a freelance motion designer" |
| 3 | Claude Fable 5.2 | as test 2, with later fixes | 75 | 185 | both below the accepted film | the best of the first four |
| 4 | Claude Opus 5.5 | with `WORLD.md`, material first, several cuts | 87 | not counted | both below the accepted film | below test 3 |
| 5 | Claude Fable 5.2 | the release candidate of 13 November | 101 | 247 | both below the accepted film | tests 3 and 5 are "close to the level of the others"; "the typography could be a little better" |
| 6 | Claude Opus 5.5 | a pre-release build of 16 November | 71 | 132 | both ranked it below test 5 and Plus One | not yet watched |

[Test 3's film](media/test3.mp4) ([its sources](media/test3-sources.md)) and [Test 6's film](media/test6.mp4) ([its sources](media/test6-sources.md)) are here to watch, with their sound, as their agents left them (720p copies; all eleven Wikimedia Commons photographs in test 6 were confirmed CC0 in their catalogue records on 16 November). Test 5's is not: nine of its ten photographs were confirmed CC0 in their catalogues' own records on the day of release, and the record for the tenth could not be read again, so that film stays out until it can.

What the table shows:

- In all five tests that reached readers, both readers ranked the test film below the accepted film beside it: ten readings, none the other way.
- A film taken through readers took 57 to 101 minutes and 94 to 247 tool calls. Tokens were not counted.
- The two films the person placed closest to the four were the two made by the stronger model. In test 6, Claude Fable 5.2 had reached its weekly rate cap, so Claude Opus 5.5 ran instead.

## One model, one brief, one idea

Tests 3 and 5 had the same model, the same paragraph and the same material. Only the skill differed: several pages were added between them. The second agent never saw the first film; its session log names no file outside its own folders. Both films open on the same question, use the same lines, and stage the same shot of a phone between two words.

So running an agent again does not give a second idea. A different film has to come from different material or a different film to hold it against. This is one pair, not a rate.

The pair was then read blind by two readers from two families of model, with an accepted film in the same line-up and the letters dealt differently for each reader:

| reader | first | second | third |
|---|---|---|---|
| Claude Opus 5.5 | test 5 | test 3 | Plus One |
| GPT-6.1 Sol | Plus One | test 5 | test 3 |

Both readings are [here in full](READINGS.md). Both put the later film above the earlier one, and for the same reason: its parts have room to move, where the earlier film's collide. The person called the differences minor. So the pages added between the two tests did no harm that anyone could find, and no good that the person could see.

## Test 6: a different world, and what still trailed

Test 6 (`Claude Opus 5.5`, given a pre-release build of 16 November that is not in this repository's history, the same brief and the same material folder, with zero session-log references outside its own folders) finished four cuts in 71 minutes and 132 tool calls (`34.13 s` at `60 fps`, `0` one-frame pops, `-15.3 LUFS`, `-2.0 dBTP`, WCAG 2.3.1 flash `ok`). Its export was packed blind against test 5 (`Claude Fable 5.2`) and `Plus One`, again dealing the letters differently for two readers from different model families:

| reader | first | second | third |
|---|---|---|---|
| Claude Opus 5.5 | test 5 | Plus One | test 6 |
| GPT-6.1 Sol | Plus One | test 5 | test 6 |

Both readings are [in full in READINGS.md](READINGS.md#the-16-november-line-up-test-6-test-5-and-plus-one). What this single run showed:

- **Different visual world and cold-start type.** Unlike tests 3 and 5's horizontal procession of plates, test 6 staged an exploded diagram (`7.5–9.0 s`): Thursday's row opens into a recipe card and draws leader lines from the plate to `Dill`, `Courgettes`, `Salmon fillets` and `Spinach` (named by Reader 1 as the film's strongest moment, and cited by Reader 2 in calling the film the work of a freelance motion designer). Its `BOARD.md` also adopted the type rules added from the four accepted films: `Fraunces` capped at three words, `Geist` for sentences and interface, and `Geist Mono` tracked `+0.12em` for day capitals.
- **Optional commands were skipped.** Given `"or"` choices (`vd borrow` or `vd pin`, `vd evolve` when open, `vd foley`), the cold agent took the older `vd new --like plusone`, `vd pin` and `sound.py` path and ran none of the new optional commands.
- **Framing and background choices kept it third.** Both readers placed test 6 behind test 5 and `Plus One` for the same two stretches: a camera push toward `"Send list"` (`17.4–20.5 s`, `f1045–1084`) that leaves `"Squash soup"` cropped to `"sh soup"` at the left edge for three seconds with the cursor parked over button labels, and the shop scene (`21.3–25.7 s`, `f1279–1541`) where `"Sent to Sam."` and `"17 items, on Sam's phone."` sit over a blurred produce photograph (`market-soft.jpg`) behind a translucent CSS gradient vignette. Both readers also independently caught test 5's `12.45–12.60 s` (`f747–757`) `"Chicken & spinach pizza"` collision over the pizza photograph again.

## What a reader model is worth

- **Its rank against an accepted film held.** In all five tests that reached readers, both readers put the test film below it, and the person agreed on the ones he watched.
- **Its label did not.** Readers answer "who made this?" with one of four labels. Four readings of six called the best accepted film the work of "a freelance motion designer", the same label they gave test films; in the 16 November line-up, `Claude Opus 5.5` called test 6 "skilled hobbyist" while `GPT-6.1 Sol` called it "freelance motion designer".
- **Readers of stills prefer room.** One reader ranked the film the person likes best last of three in the first line-up and second in the next, for being full. A reader from another family ranked it first both times. This is why the skill asks for two readers from different models, ranks against an accepted film, and tells the agent never to choose between good films by a reader's rank.
- **Readers cannot hear, and they read stills**: the whole film at two frames a second, and every frame of its five busiest seconds. They misjudged the size of text until the briefs told them how wide a tile is.

## What the engine's own record is worth, and the drawn pixels

In tests 1 to 5, `vd look` reported only from raea's record of what it drew (each text's box, each layer's mask), not from rendered pixels. It found text off the frame and layers that never showed, but could not see text lying over a busy picture: in test 5, two blind readers caught `"Chicken & spinach pizza"` crossing the pizza photograph at 12.45–12.60 s (`f747–756`), which the draw-tree report had passed.

Since then `vd look` also reads the drawn pixels for one fault: text over a busy ground, under WCAG's contrast floor for its size as shown. The ground is a picture where raea's layer mask shows one under the text, and otherwise whatever is not text (a CSS background, an SVG, a drawn ground); see-through ink is mixed with the ground it shows. Its tests are pictures made in code with a known answer, and on 16 November it was run on real frames with raea 0.1.2: on Test 5 at 12.5 s it reports "Chicken" at 1.16:1 and "& spinach pizza" at 1.33:1 over the pizza photograph, the collision both readers saw; on the four accepted films, at six moments each (3, 8, 13, 18, 23 and 27 s), it finds nothing on Stet, Onoma and Linden, and on Plus One at 27 s it names two name labels ("Omar" and "Max", drawn part-transparent) over a dark ground strewn with bright confetti, which read clearly by eye: two lines to look at, not faults. Without the mask it says nothing, because on a plain grey ground it called readable heavy type (4.54:1) unreadable. A check for a large jump of the eye across a cut runs only when two adjacent frames are asked for and differ as a cut does, and its limit, 45 degrees, is not measured. The export's scan also screens for flashing (WCAG 2.3.1). It counts only paired, same-direction changes in brightness or red over a quarter of a ten-degree field, the terms of the rule itself; an earlier version counted pans, slides and a dot grid aliased by sampling, in windows too small for that field, and flagged all four accepted films. Calibrated, it finds 3 or 4 such changes in the busiest second of each (the limit is 6) and flags none, while its tests catch a full-frame flash at 4 Hz, a box over 30% of the field and a red flash, and pass a 3 Hz flash, a box over 20%, black against #010101 and a pan over stripes. One passage is close: in Stet at 2.7 s a row's tint and the re-run button change together about 5 times a second, over about a fifth of the field as measured here (a third of the frame's width by 4/9 of its height, the reference screen's 10 degrees with the film fitted to it). One reviewer measured the field as a third of the frame each way, as on a wide screen viewed close, and there the same passage covers more than a quarter and fails. The four films are its only real footage, and the field assumes a full screen; how it does on other films is not known.

## Tests, and what clean machines found

There are 206 tests in 27 files. Most are built on an input with a fault planted in it; some of the newer commands' tests, in `test_alien_features.py`, check only that a command makes what it says on a clean input. Until the day before release they had run on one laptop only. Their first run on hosted machines failed on Linux and on Windows. Two tests had assumed things about that laptop: an optional package, and how a temp folder is spelled. One showed a real limit on Linux in a helper: a waiting job cannot always tell that the process that started it has gone. The tool's notes now say so.

On the day of release a model from another family than the one that wrote the tools reviewed their code. It found twelve bugs and five risks. The twelve are mended, eleven with a test. Three of the risks are mended too. A second review, of everything changed in the tools since the last tested release, found five more faults, all in code written that day; those are mended with tests of their own. The two risks left, both in the render queue, were mended on 16 November, each with a test; the one about a force-killed job runs only on macOS and Linux, so this laptop has not run it.

Since then every change runs on Linux, Windows and macOS, and once more on a Mac that installs raea as a stranger would, sets up by the README's own lines, runs every test with nothing skipped and then exports a short film whole. raea's installer gives pre-releases too: on the day of release that Mac got 0.1.2 in the morning and 0.1.3-rc4 in the afternoon, and passed on both. From then on it runs twice: on 0.1.2, which must pass, and on whatever the installer gives that day, which is watched.

The four films were also drawn with the raea they were accepted on (0.1.1-rc4) and with 0.1.2, the release of that day: 24 moments, and one busy moment of each at full size, compared pixel for pixel on Windows. No pixel differed.

## What is not known

- What the skill adds over an agent given raea and no skill. Nobody has run that comparison.
- Whether anyone but one person finds the four films good, and what that person makes of test 6 when watched at speed with sound.
- Whether the skill works for a real product. All ten films are for made-up ones.
- Which pages matter. The one controlled pair differed by several pages at once, and the person found the two films close. In test 6 `Claude Opus 5.5` adopted `BOARD.md`'s type rules from the four accepted films, but both the model and the skill differed from test 5, so no controlled pair isolates that page alone.
- What any of the newer optional commands (`vd borrow`, `vd evolve`, `vd foley`, `vd capture`, `vd launch`, `vd audio`, `vd bridge`, `vd playable`) changes in a cold-started film: test 6's agent skipped all of them when offered as `"or"` choices.
- How the films sound to anyone else. No agent can hear: levels are checked, tunes are not.
- A worked film exported whole on a Mac (the short starter film was; the four have only been drawn there at sampled moments), and anything rendered on Linux.
- What a film costs in tokens.

## Checking this yourself

- The films: click one on the front page, or render one on your machine with the README's "A first film".
- A blind line-up: `vd pack FILM.mp4 --against OTHER.mp4`, then the readers' briefs in [`EYES.md`](../skills/video-decompiler/EYES.md), word for word.
- The tests: `python tests/run.py`.
