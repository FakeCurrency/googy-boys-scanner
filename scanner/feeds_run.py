"""CLI entry point for the feeds update.

Usage:
    python -m scanner.feeds_run
    python -m scanner.feeds_run --out public/data
"""

import argparse
import json
import logging
import pathlib

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

DEFAULT_OUT = pathlib.Path(__file__).resolve().parents[1] / "public" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube feeds + AI narrative builder")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="directory to write feeds.json into")
    args = parser.parse_args()

    from .feeds import build_feeds_json

    print("Building feeds …", flush=True)
    payload = build_feeds_json()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "feeds.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    n_channels = len(payload["channels"])
    n_videos   = sum(len(c["videos"]) for c in payload["channels"])
    has_narr   = payload["narrative"] is not None
    print(f"  feeds: {n_channels} channel(s), {n_videos} video(s), "
          f"narrative={'yes' if has_narr else 'no (ANTHROPIC_API_KEY not set)'} → {out_path}")


if __name__ == "__main__":
    main()
