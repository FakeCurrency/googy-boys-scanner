"""Write scan results to JSON the frontend can load."""

import json
import pathlib


def write(payload: dict, out_dir: str | pathlib.Path, name: str | None = None) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name or payload['market']}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
