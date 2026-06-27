"""Shared pytest fixtures for the scanner test-suite.

Keeps the repo root on sys.path (so `import scanner...` works when pytest is
invoked from anywhere) and provides small factory fixtures for building the
position / journal dicts the risk, breaker, journal and pre-trade tests need.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.scalp_journal import _session_day  # noqa: E402


@pytest.fixture
def today():
    """Current AEST session-day key (matches how positions are tagged)."""
    return _session_day()


@pytest.fixture
def make_pos():
    """Factory for a scalp/broker position dict with sensible defaults.

    Override any field via kwargs, e.g. make_pos(risk_per_trade=250, sector="energy").
    """
    def _factory(**kw):
        pos = {
            "symbol": "BTCUSDT",
            "name": "Bitcoin",
            "asset_type": "crypto",
            "sector": "crypto",
            "direction": "long",
            "entry": 50_000.0,
            "stop": 49_000.0,
            "target": 53_000.0,
            "units": 0.01,
            "risk_per_trade": 100.0,
            "grade": "A",
            "score": 7,
        }
        pos.update(kw)
        return pos
    return _factory


@pytest.fixture
def make_journal():
    """Factory for a {"open": [...], "closed": [...]} journal dict."""
    def _factory(open_=None, closed=None):
        return {"open": list(open_ or []), "closed": list(closed or [])}
    return _factory


@pytest.fixture
def closed_trade():
    """Factory for a closed-trade record (the shape summarize()/breakers read)."""
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
    """Silence outbound alert side-effects so breaker/expectancy tests stay hermetic."""
    import scanner.broker.alert_dispatch as ad
    monkeypatch.setattr(ad, "send", lambda *a, **k: None, raising=False)
    try:
        import scanner.broker.alert_router as ar
        monkeypatch.setattr(ar, "smart_send", lambda *a, **k: None, raising=False)
    except Exception:
        pass
    return True
