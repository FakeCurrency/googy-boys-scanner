"""Per-ticker failure bookkeeping for the scan loops (TOP100 #60 / #66).

Both scan loops in this package swallow per-ticker exceptions ON PURPOSE — one
malformed frame out of 2,212 must not take a whole market's scan down — but
each of them swallowed it into *silence*:

* ``scan.py`` printed behind ``if progress:`` and the only production caller
  (``run.py``) passes ``progress=False``, so a scheduled run printed nothing.
* ``spec_run.py`` used a bare ``continue`` and, worse, a bare ``pass``.

The cost is that "this name throws every single session" and "this name never
sets up" produce byte-identical output. A systematic breakage — a column
rename, a dtype change, one suffix wrong across a whole sector of the universe
— therefore looks exactly like a quiet market, which is the one reading nobody
investigates. This module is the accounting that tells the two apart: count the
failures, name the exception KINDS, print a line WHETHER OR NOT anything failed,
and publish a capped sample so a fix can start from the committed artefact
rather than from an Actions log that expires in 90 days.

Three deliberate limits:

* **It is not an alert channel.** It changes what a scan SAYS, never what it
  does — nothing is re-raised, no name is dropped, no threshold moves. Routing
  a scan-health number into Discord is an alerting-threshold decision and
  therefore the owner's.
* **The published sample is CAPPED** (``SCAN_ERROR_SAMPLE_MAX``). These payloads
  are committed by the scan workflow, so an unbounded list would write thousands
  of rows into a tracked file and bury the real diff on the exact run you most
  need to read. The count already tells you a failure is systemic; the sample
  only has to tell you what it looks like.
* **Messages are ASCII-folded** before they are printed or published, because
  project rule 9 (Windows consoles are cp1252) applies to whatever an arbitrary
  third-party exception decided to put in its message.
"""

from collections import Counter

from . import config


def _clean(text, limit: int) -> str:
    """One-line, cp1252-safe, length-capped rendering of an exception message.

    Newlines are collapsed rather than kept: these go into a single summary line
    and into a JSON field that a human skims, and a pandas traceback fragment
    with embedded newlines would wreck both. Non-ASCII folds to ``?`` (rule 9).

    ``str()`` is guarded because an exception is free to define a ``__str__``
    that itself throws, and this function runs INSIDE the handler that is
    swallowing an error on purpose. Letting that escape would convert a
    contained per-ticker failure into a fatal one — the exact inversion this
    module exists to prevent.
    """
    try:
        text = str(text)
    except Exception:
        return "(unprintable)"
    msg = " ".join(text.split())
    msg = msg.encode("ascii", "replace").decode("ascii")
    if limit > 0 and len(msg) > limit:
        msg = msg[:max(1, limit - 3)] + "..."
    return msg


class ErrorLog:
    """The per-ticker exceptions one scan loop swallowed, over one market.

    ``label`` is what the summary line calls this loop — it must identify BOTH
    the lens and the market ("vivek [asx]"), because a full cycle prints three
    of these back to back and a bare "errors: 41" tells you nothing about which
    market to go and look at.

    The caps are read from ``config`` at construction rather than at import, so
    a test can set them without reloading the module.
    """

    def __init__(self, label: str, *, sample_max: int | None = None,
                 msg_max: int | None = None, kinds_max: int | None = None,
                 loud_pct: float | None = None):
        self.label = label
        self._rows: list[tuple[str, str, str]] = []
        self.sample_max = config.SCAN_ERROR_SAMPLE_MAX if sample_max is None else sample_max
        self.msg_max = config.SCAN_ERROR_MSG_MAX if msg_max is None else msg_max
        self.kinds_max = config.SCAN_ERROR_KINDS_MAX if kinds_max is None else kinds_max
        self.loud_pct = config.SCAN_ERROR_LOUD_PCT if loud_pct is None else loud_pct

    # ── collection ───────────────────────────────────────────────────────────

    def record(self, symbol, exc) -> None:
        """Note that ``symbol`` failed with ``exc``. Never raises."""
        kind = type(exc).__name__ if isinstance(exc, BaseException) else ""
        self._rows.append((str(symbol), kind, _clean(exc, self.msg_max) or "(no message)"))

    def __len__(self) -> int:
        return len(self._rows)

    def __bool__(self) -> bool:
        return bool(self._rows)

    def kinds(self) -> Counter:
        """Exception class name -> count. Unclassifiable entries read 'unknown'."""
        return Counter(k or "unknown" for _, k, _ in self._rows)

    # ── rendering ────────────────────────────────────────────────────────────

    def sample(self) -> list[dict]:
        """Up to ``sample_max`` rows — ONE PER DISTINCT KIND FIRST.

        A systemic break floods the log with a single exception type, so a plain
        head-of-list sample would be twelve copies of it and the one rare
        failure — the interesting one — is exactly the row that gets cut. Kinds
        are visited in first-seen order and the remainder keeps its original
        order, so the sample is deterministic for a given run.
        """
        cap = max(0, self.sample_max)
        if not cap:
            return []
        seen: set[str] = set()
        first: list[tuple[str, str, str]] = []
        rest: list[tuple[str, str, str]] = []
        for row in self._rows:
            (rest if row[1] in seen else first).append(row)
            seen.add(row[1])
        return [{"symbol": s, "error": f"{k}: {m}" if k else m}
                for s, k, m in (first + rest)[:cap]]

    def summary(self, scanned: int = 0) -> str:
        """The one line this loop prints, ASCII-only, with a leading indent.

        Printed even at zero failures on purpose: "no line" and "the accounting
        never ran" are the same thing in a log, and a standing ``0 failed of
        2212`` is what makes a jump to ``41 failed`` legible at a glance.

        The ``!!`` marker leads rather than trails (the house style used by
        ``run.py``'s note lines) so it survives a long tail of exception kinds.
        """
        n = len(self)
        head = f"{self.label}: {n} failed"
        if scanned:
            head += f" of {scanned}"
        if not n:
            return "  " + head
        pct = (100.0 * n / scanned) if scanned else 0.0
        if scanned:
            head += f" ({pct:.1f}%)"
        counts = self.kinds()
        shown = counts.most_common(max(1, self.kinds_max))
        kinds = ", ".join(f"{k} x{c}" for k, c in shown)
        hidden = len(counts) - len(shown)
        if hidden > 0:
            kinds += f", +{hidden} more"
        loud = self.loud_pct > 0 and pct >= self.loud_pct
        return f"  {'!! ' if loud else ''}{head} - {kinds}"

    def report(self, scanned: int = 0) -> str:
        """Print :meth:`summary` and hand it back (so a caller can also test it)."""
        line = self.summary(scanned)
        print(line, flush=True)
        return line

    def payload(self, prefix: str = "") -> dict:
        """The additive fields a scan publishes: a full count and a capped sample.

        Additive by construction — every consumer of these payloads reads named
        keys and the CI schema gates check ``schema_version`` alone, so this
        needs no schema bump. Bumping would be actively harmful: it marks every
        already-committed scan file as a build behind and shows a stale-data
        warning on the site until all three markets have rescanned.

        ``prefix`` is how a payload carries MORE THAN ONE failure mode without
        summing them (``chart_errors``, ``price_errors``). Summing is the thing
        to avoid: "41 failed" that could mean either "41 names are missing from
        the page" or "41 names are on the page with an empty chart" is a number
        you cannot act on. An UNPREFIXED ``errors`` means the same thing in
        every file — a name that failed to produce a row — so a reader learns
        one vocabulary rather than one per payload.
        """
        return {f"{prefix}errors": len(self), f"{prefix}error_sample": self.sample()}
