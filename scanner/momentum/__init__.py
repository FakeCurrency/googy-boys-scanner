"""VIVEK MOMENTUM -- the divergence lens. REPORT-ONLY.

A fourth, additive scanner lens: RSI regular divergence off strict pivots
(Rule A) and a scored 20/50 moving-average cross (Rule B), on daily bars,
over ASX / NASDAQ / crypto.

IT CHANGES NO TRADES, AND THAT IS STRUCTURAL, NOT A PROMISE.  Nothing under
`scanner/broker/` can reach this package and nothing here imports the bot or
the HIGH-CONVICTION rule; `tests/test_momentum_fences.py` fails the push if
either becomes false.  The lens owns exactly one output directory,
`public/data/momentum/`, and writes nothing else.

Built to be deleted in one commit -- `git rm -r scanner/momentum
public/data/momentum` plus the page, the suite and the nav entry -- because
removability and non-breakingness are the same property (HANDOFF_2026-09-22
Part 17.0).

The maths is a port of the owner's specification pack at
`tradingview/scanner-spec/`, whose reference implementation passes 28
assertions including a causality proof.  Where this package and that
reference disagree, the reference is right and this is a bug.
"""

__all__ = ["RULESET_VERSION"]

from .config import RULESET_VERSION  # noqa: F401
