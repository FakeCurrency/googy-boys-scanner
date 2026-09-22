"""CLI: python -m scanner.momentum.run --market asx|nasdaq|crypto

PHASE 1 STUB.  The publisher lands in Phase 3; this file exists now so the
write-set fence has something to read and so the output path is declared in
exactly one place from the start.

THE WRITE-SET IS THE FENCE.  This module may only ever write under
`public/data/momentum/`.  It must not name any other lens's artefact, the
bot book, the alert history or the funnel ledger -- pinned by
`tests/test_momentum_fences.py`.
"""

from __future__ import annotations

import argparse
import pathlib

from . import config

# The ONE output location. A subdirectory rather than
# `public/data/<market>_momentum.json` on purpose: nothing in the repo globs
# `public/data/*.json` today, but a subdirectory cannot be caught by one that
# appears later, and deletion is a single `git rm -r`.
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "public" / "data" / "momentum"


def out_path(market: str) -> pathlib.Path:
    """The only path this lens is allowed to write."""
    return OUT_DIR / f"{market}.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scanner.momentum.run",
        description="VIVEK MOMENTUM - report-only divergence lens (%s)"
                    % config.RULESET_VERSION,
    )
    p.add_argument("--market", default="asx", choices=sorted(config.MARKETS),
                   help="market to screen")
    p.add_argument("--mode", default=config.DEFAULTS.mode,
                   choices=sorted(config.MODES),
                   help="A = divergence only (default); B = A or B; C = both, aligned")
    p.add_argument("--limit", type=int, default=0,
                   help="screen at most N symbols (0 = no limit); for smoke tests")
    p.add_argument("--dry-run", action="store_true",
                   help="screen but publish nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print("momentum: ruleset %s, market=%s, mode=%s"
          % (config.RULESET_VERSION, args.market, args.mode))
    print("momentum: PHASE 1 STUB - the screen lands in Phase 2 and the "
          "publisher in Phase 3; nothing was written")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
