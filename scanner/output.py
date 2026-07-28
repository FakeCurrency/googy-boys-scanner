"""Write scan results to JSON the frontend can load.

Every JSON file the scan publishes goes out through ``write_json`` here, for
two reasons that were each a live defect (TOP100 #62 and #64).

**#62 — one bad bar must not blank a whole page.** ``json.dumps`` defaults to
``allow_nan=True``, which happily emits a bare ``NaN`` / ``Infinity`` token.
That is not JSON: ``JSON.parse`` rejects it and so does ``response.json()``, so
ONE non-finite value anywhere in a market payload takes the ENTIRE page down
rather than showing one blank cell. ``_finite`` walks the payload first and maps
every non-finite float to ``null`` — the same choice ``regime._r`` and
``vivek_backtest`` already made locally — and ``allow_nan=False`` then stands
behind it as a backstop, so anything that evades the walk fails LOUDLY at write
time instead of silently at load time in the browser. Sanitising first is what
makes that backstop safe to turn on: flipping ``allow_nan=False`` alone would
have converted a quietly-broken file into a hard scan failure, which is the
worse trade.

**#64 — a half-written file must never be published.** ``Path.write_text``
truncates first and writes second, so a crash, a timeout kill or a full disk
mid-write leaves a truncated file that parses as nothing at all. Writing to a
sibling temp file and ``os.replace``-ing it in is atomic on POSIX: a reader sees
either the whole old file or the whole new one, never a fragment. The repo
already did this in ``journal_common.atomic_write`` (reused here rather than
re-implemented) and in three hand-rolled local copies; the scan's own six
outputs were the ones still doing it the unsafe way.

**Two hand-rolled copies deliberately remain**, and the reason is worth stating
because their absence from the sweep is a decision rather than an oversight:
``universe._save_universe_cache`` and ``sectorcache.save_cache``. Both are
already atomic, so #64 does not apply, and both serialise a payload of strings
and ints ONLY — a ticker list and a ``{SYMBOL: sector}`` map — so there is no
float for #62's NaN to arrive in. ``spec_run``'s two writes were the third such
copy and DID need converting: they publish rounded OHLC floats, where one NaN
bar would have blanked a whole chart page. The exemption is pinned by
``tests/test_publish_integrity.py`` so a fourth hand-rolled writer trips a test
instead of inheriting an exemption it was never argued for.

Callers pass their own ``indent`` / ``separators`` / ``newline`` because the
published files are committed by the scan workflow — changing one file's
formatting would land a whole-file diff on the next scan commit and bury the
real change.
"""

import json
import math
import pathlib

from .journal_common import atomic_write


def _finite(obj):
    """Recursively map every non-finite float in ``obj`` to ``None``.

    Containers are rebuilt rather than mutated, so a caller's payload is never
    altered underneath it — ``run.py`` keeps using ``vk`` after publishing the
    slim price file from it. Tuples come back as lists, which is what
    ``json.dumps`` would have emitted anyway.

    ``isinstance(obj, float)`` covers ``np.float64`` as well, because numpy's
    64-bit float is a genuine subclass of Python's. The narrower numpy scalars
    (``np.float32`` and friends) are NOT, and are handled by ``_default``.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def _default(obj):
    """``json.dumps`` fallback for values it cannot encode natively.

    Reached for numpy scalars that are not float subclasses (``np.float32``,
    ``np.int64``, ``np.bool_``), which ``_finite`` deliberately leaves alone
    because they are not ``float``. ``.item()`` is numpy's documented way to get
    the nearest Python scalar, and it preserves int-ness — casting everything
    through ``float()`` instead would republish every count as ``3.0``.

    The ``ndim`` guard is load-bearing and was put there by a failing test:
    ``.item()`` also succeeds on a ONE-ELEMENT ndarray, so without it
    ``{"prices": np.array([1.0])}`` would have published as ``1.0`` — an array
    silently flattened into a scalar, which is worse than the NaN this module
    exists to stop. Only a 0-d value (every numpy scalar, and ``np.array(1.0)``)
    converts.

    Anything else re-raises the ``TypeError`` json would have raised. An
    ndarray or a datetime in a payload is a bug at the producer, and failing
    here is how it gets found; coercing it to ``str`` would ship something that
    looks like data.
    """
    if getattr(obj, "ndim", 0) == 0 and callable(getattr(obj, "item", None)):
        try:
            return _finite(obj.item())
        except Exception:
            pass
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def dumps(payload, *, indent: int | None = 2, separators: tuple | None = None,
          sort_keys: bool = False, ensure_ascii: bool = True) -> str:
    """``json.dumps`` with the non-finite hazard closed. See the module docstring."""
    return json.dumps(_finite(payload), indent=indent, separators=separators,
                      sort_keys=sort_keys, ensure_ascii=ensure_ascii,
                      allow_nan=False, default=_default)


def write_json(path: str | pathlib.Path, payload, *, indent: int | None = 2,
               separators: tuple | None = None, sort_keys: bool = False,
               ensure_ascii: bool = True, newline: bool = False) -> pathlib.Path:
    """Publish ``payload`` to ``path`` atomically, with non-finite floats nulled.

    ``newline`` appends a trailing "\\n" — some existing files have one and some
    do not, and that is preserved per-caller so this change lands as a behaviour
    fix with a zero-byte diff on every published artefact. (It is a *content*
    trailing newline; the LF-vs-CRLF pinning is the ``newline="\\n"`` handed to
    ``atomic_write`` below, which is a different thing wearing the same word.)
    """
    path = pathlib.Path(path)
    text = dumps(payload, indent=indent, separators=separators, sort_keys=sort_keys,
                 ensure_ascii=ensure_ascii)
    atomic_write(path, text + "\n" if newline else text, newline="\n")
    return path


def write(payload: dict, out_dir: str | pathlib.Path, name: str | None = None) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return write_json(out / f"{name or payload['market']}.json", payload)
