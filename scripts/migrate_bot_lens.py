"""One-time migration: stamp lens="vivek" on bot-book trades that predate the
field (scanner/broker/vivek_run.py stamps it on every NEW position since
2026-07-20; the journal lens tracker reads t.lens).

Explicit + reversible:
    python scripts/migrate_bot_lens.py            # add lens="vivek" where missing
    python scripts/migrate_bot_lens.py --revert   # remove exactly those stamps

Atomic writes (tmp + os.replace); prints a per-file count. Safe to re-run.
"""
import argparse
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = (ROOT / "journal" / "vivek_bot_book.json",
         ROOT / "public" / "data" / "vivek_bot_book.json")


def migrate(path: pathlib.Path, revert: bool) -> int:
    if not path.exists():
        print(f"{path}: missing - skipped")
        return 0
    book = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for key in ("open", "closed"):
        for t in book.get(key) or []:
            if not isinstance(t, dict):
                continue
            if revert:
                if t.get("lens") == "vivek":
                    del t["lens"]
                    n += 1
            elif "lens" not in t:
                t["lens"] = "vivek"
                n += 1
    if n:                                       # untouched file -> no write
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(book, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    print(f"{path}: {'removed' if revert else 'stamped'} lens on {n} trade(s)")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Stamp lens='vivek' on bot-book trades missing it")
    ap.add_argument("--revert", action="store_true",
                    help="remove lens='vivek' stamps (undo this migration)")
    args = ap.parse_args()
    total = sum(migrate(p, args.revert) for p in FILES)
    print(f"total: {total} trade(s) updated")


if __name__ == "__main__":
    main()
