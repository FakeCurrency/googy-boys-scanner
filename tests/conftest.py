"""Shared pytest fixtures for the scanner test-suite.

Keeps the repo root on sys.path (so `import scanner...` works when pytest is
invoked from anywhere), keeps every test OFF the network and off the repo's
live caches (the autouse fixtures below), and provides small factory fixtures
for the journal P&L and kill-switch tests.
"""

import datetime as dt
import pathlib
import sys
import types
import urllib.parse
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config as _config  # noqa: E402
from scanner import data as _data  # noqa: E402
from scanner import sectorcache as _sectorcache  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_frame_cache(tmp_path, monkeypatch):
    """Every test gets its own empty last-good frame cache (2026-09-05).

    the since-removed turtle runner routed its download through
    `data.merge_with_cache`, the same last-good cache the VIVEK scan uses.
    Without this redirect a test that hands the runner full frames would SAVE
    them to the repo's real `.cache/frames`, and the next test expecting a
    gutted download to trip the coverage floor would find that download
    quietly refilled from the previous test's cache -- order-dependent
    results, and pytest writing the developer's live cache as a side effect.
    Tests that need a warm cache seed their own via `data.save_frame_cache`.
    """
    monkeypatch.setattr(_data, "_CACHE_DIR", tmp_path / "frames")


@pytest.fixture(autouse=True)
def _no_exchange_network(monkeypatch):
    """No test may reach a real exchange (2026-09-28). The shipped default is
    config.CRYPTO_DATA_SOURCE = "exchange", so without this every crypto path
    under test would try Binance/Bybit/Coinbase for real -- slow, flaky, and
    live network from CI. Every venue refuses instead; data.fetch() then falls
    back to `download`, which the tests already stub, so they read exactly
    as before. A test that exercises the exchange path installs its own fake
    `_get_json` (tests/test_exchange_data.py), which replaces this one."""
    from scanner import exchange_data as _ex

    def _refuse(url, timeout):
        raise _ex.SourceDead("network disabled in tests")

    monkeypatch.setattr(_ex, "_get_json", _refuse)


class YahooRefused(ConnectionError):
    """What every Yahoo call raises under test (see `_no_yahoo`)."""


def _is_yahoo(url) -> bool:
    url = getattr(url, "full_url", url)          # a urllib Request or a str
    host = (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    return host == "yahoo.com" or host.endswith(".yahoo.com")


@pytest.fixture(autouse=True)
def _no_yahoo(monkeypatch):
    """No test may reach Yahoo either (REFINE200, 2026-10-14) -- the twin of
    `_no_exchange_network`. Eleven tests used to call Yahoo for real on every
    run: scan_vivek_market always attaches the 4H plans (VIVEK_H4_PLANS), which
    download 1h bars for every result row, and run_market refetches an
    off-universe held name. With no network each one sat out data._fetch_batch's
    full back-off (DATA_RETRIES x DATA_BACKOFF, ~19s) -- 3.7 minutes of sleep a
    run -- and in CI, where the network is real, the pass rate and the runtime
    hung on how hard Yahoo was throttling GitHub's IPs that day.

    Every yfinance entry point refuses instead: `yf.download`, and the
    YfData.get/post choke point that Ticker.history / .calendar / .get_info and
    marketcaps' bulk quote all go through; plain urllib/requests calls to a
    *.yahoo.com host refuse too. DATA_BACKOFF is zeroed so the "degrades, never
    fails" path runs at once; the retry COUNT and the long cooldowns are left
    alone (tests/test_data_download.py asserts on them, with its own fakes).
    A test that exercises a download installs its own `data.yf.download` (or
    YfData) fake, which replaces this one, exactly like the exchange refusal."""
    import requests
    import yfinance as yf
    from yfinance.data import YfData

    def _refuse(*a, **k):
        raise YahooRefused("Yahoo disabled in tests")

    monkeypatch.setattr(yf, "download", _refuse)
    monkeypatch.setattr(YfData, "get", _refuse)
    monkeypatch.setattr(YfData, "post", _refuse)
    monkeypatch.setattr(_config, "DATA_BACKOFF", [0.0])

    real_urlopen = urllib.request.urlopen

    def _urlopen(url, *a, **k):
        if _is_yahoo(url):
            raise YahooRefused("Yahoo disabled in tests")
        return real_urlopen(url, *a, **k)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    real_request = requests.sessions.Session.request

    def _request(self, method, url, *a, **k):
        if _is_yahoo(url):
            raise YahooRefused("Yahoo disabled in tests")
        return real_request(self, method, url, *a, **k)

    monkeypatch.setattr(requests.sessions.Session, "request", _request)


@pytest.fixture(autouse=True)
def _isolated_sector_cache(tmp_path, monkeypatch):
    """The sector cache is a SIGNAL PATH (data/sector_map.json feeds decide()'s
    per-sector cap), rewritten by every scan. Tests used to read the live file:
    39 of them merged whatever sectors the last scan had cached into their rows,
    so a scan commit could move a unit test. Every test now starts from an
    EMPTY cache in tmp_path (a missing file = an empty cache, sectorcache's own
    rule) and its writes land there too. A test that needs entries writes them
    via sectorcache.save / to sectorcache.CACHE_FILE, or patches the module
    itself, as before."""
    monkeypatch.setattr(_sectorcache, "CACHE_FILE", tmp_path / "sector_map.json")
    monkeypatch.setattr(_sectorcache, "PUBLIC_FILE",
                        tmp_path / "public_sector_map.json")


@pytest.fixture
def freeze_now(monkeypatch):
    """Pin ``<module>.dt.datetime.now(tz)`` to one aware instant, for ONE module.

    For modules that ``import datetime as dt`` and read the clock as
    ``dt.datetime.now(tz)``. The module gets its own ``dt`` whose ``datetime``
    answers ``now`` with the instant in the asked-for zone; every other
    attribute is the real one, and nothing outside that module moves.
    """
    def _freeze(module, instant):
        class _Frozen(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz)
        shim = types.SimpleNamespace(**{k: getattr(dt, k) for k in dir(dt)
                                        if not k.startswith("__")})
        shim.datetime = _Frozen
        monkeypatch.setattr(module, "dt", shim)
    return _freeze


@pytest.fixture
def make_journal():
    """Factory for a {"open": [...], "closed": [...]} journal dict."""
    def _factory(open_=None, closed=None):
        return {"open": list(open_ or []), "closed": list(closed or [])}
    return _factory


@pytest.fixture
def closed_trade():
    """Factory for a closed-trade record (the shape summarize() reads)."""
    from scanner.scalp_journal import _session_day

    def _factory(pnl=100.0, r=1.0, **kw):
        rec = {
            "symbol": "BTCUSDT",
            "direction": "long",
            "pnl": pnl,
            "r": r,
            "session_day": _session_day(),
            "opened_ts": "2026-06-27T00:00:00Z",
            "market_regime": "trending",
        }
        rec.update(kw)
        return rec
    return _factory


@pytest.fixture
def stub_alerts(monkeypatch):
    """Silence outbound alert side-effects so the kill-switch tests stay hermetic."""
    import scanner.broker.alert_dispatch as ad
    monkeypatch.setattr(ad, "send", lambda *a, **k: None, raising=False)
    try:
        import scanner.broker.alert_router as ar
        monkeypatch.setattr(ar, "smart_send", lambda *a, **k: None, raising=False)
    except Exception:
        pass
    return True


@pytest.fixture(autouse=True)
def _no_live_alert_channels(monkeypatch):
    """No test may deliver a real alert (REFINE200 #127, 2026-10-14). Telegram
    sends whenever its secrets are set and config.TELEGRAM_ENABLED is on, so a
    developer shell that exports them (with the mute lifted) would have pytest
    ping the owner's phone. Tests that exercise a channel set their own fake values."""
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GBS_SMTP_HOST",
                 "GBS_SMTP_USER", "GBS_SMTP_PASS", "GBS_ALERT_TO"):
        monkeypatch.delenv(name, raising=False)
