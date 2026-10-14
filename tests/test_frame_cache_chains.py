"""The scan frame cache's two chains (REFINE200 #87, 2026-10-14).

crypto_bot.yml runs every hour and used to restore and re-save the WHOLE
.cache/frames -- the ASX and NASDAQ pickles with it -- on every run: two dozen
full archives a day into a 10 GB repo cache, which evicted the Ignition lens's
once-a-day caches. Crypto frames now have their own chain, and scan.yml (which
scans crypto only on a heal or by hand) layers that chain in.

What has to stay true for that to be safe:
  * both writers name the crypto chain with the IDENTICAL `path` string --
    actions/cache only restores an entry saved with the same path, so a
    one-character drift silently splits the chain in two;
  * the glob covers every crypto frame file data.py writes, and no other
    market's;
  * the stock chain keeps its key and path, so nothing it holds is lost.
"""

from __future__ import annotations

import fnmatch
import pathlib

import yaml

from scanner import config, data

ROOT = pathlib.Path(__file__).resolve().parents[1]
CRYPTO_PATH = ".cache/frames/crypto*"


def _caches(wf: str, job: str) -> list[dict]:
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"))
    return [s["with"] for s in doc["jobs"][job]["steps"]
            if str(s.get("uses", "")).startswith("actions/cache")
            and ".cache/frames" in str(s["with"]["path"])]


def test_crypto_bot_caches_only_the_crypto_frames_in_their_own_chain():
    (c,) = _caches("crypto_bot.yml", "crypto")
    assert c["path"] == CRYPTO_PATH
    assert c["key"] == "vivek-frames-crypto-${{ github.run_id }}"
    assert c["restore-keys"].strip() == "vivek-frames-crypto-"


def test_scan_keeps_the_stock_chain_and_layers_the_crypto_chain_over_it():
    stock, crypto = _caches("scan.yml", "scan")
    assert stock["path"] == ".cache/frames"
    assert stock["key"] == "vivek-frames-${{ github.run_id }}"
    assert stock["restore-keys"].strip() == "vivek-frames-"
    assert crypto == _caches("crypto_bot.yml", "crypto")[0], \
        "the crypto chain must be named identically by both writers"


def test_the_glob_covers_the_crypto_frame_files_and_nothing_else(monkeypatch):
    def name(market):
        return data._cache_path(market).name
    pattern = CRYPTO_PATH.rsplit("/", 1)[1]
    for source in ("exchange", "yahoo"):
        monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", source)
        assert fnmatch.fnmatch(name("crypto"), pattern), source
    for market in ("asx", "nasdaq", "ignition-crypto"):
        assert not fnmatch.fnmatch(name(market), pattern), market
