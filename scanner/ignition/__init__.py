"""IGNITION -- the coil -> ignition lens. REPORT-ONLY.

Built 2026-09-28 after QNT ran 71 -> 373 in four sessions while the deck
showed nothing: the VIVEK row that had it graded A (a 1D break at the daily
200) was deleted the moment price left the 200-SMA, and nothing else in the
repo looks for the SHAPE -- months of compression, then a close out of the
base on a multiple of normal volume -- as a thing in its own right.

IT CHANGES NO TRADES, AND THAT IS STRUCTURAL. Nothing under `scanner/broker/`
can import this package and nothing here imports the bot, the HIGH-CONVICTION
rule or the confluence machinery; `tests/test_ignition_fences.py` fails the
push if either becomes false. The lens owns one directory,
`public/data/ignition/`, and writes nothing else.

Built to be deleted in one commit -- `git rm -r scanner/ignition
public/data/ignition` plus the workflow, the deck pill, the two suites and the
config block -- because removability and non-breakingness are the same
property (HANDOFF_2026-09-22 Part 17.0).

    engine.py    pure feature/state maths, shared by the screen AND the replay
    run.py       CLI: screen a market, or replay it (--backtest)
    backtest.py  the walk-forward replay and its honesty blocks
    thumbs.py    mini-chart arrays for the panel (display only)
"""

__all__ = ["RULESET_VERSION"]

from scanner.config import IGNITION_RULESET_VERSION as RULESET_VERSION  # noqa: F401
