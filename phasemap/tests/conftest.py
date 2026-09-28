"""PhaseMap test guards (2026-09-28).

PhaseMap crypto now reads `scanner.data.fetch` (exchange klines first), and
tests/conftest.py -- which refuses every exchange -- does not cover this
directory. Without the same guard here a crypto test would reach Binance /
Coinbase for real: live network from CI, where the runner CAN reach them,
so a test would pass or fail on today's BTC price. Every venue refuses
instead; a test that wants exchange bars installs its own `_get_json`.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_exchange_network(monkeypatch):
    from scanner import exchange_data as _ex

    def _refuse(url, timeout):
        raise _ex.SourceDead("network disabled in tests")

    monkeypatch.setattr(_ex, "_get_json", _refuse)
