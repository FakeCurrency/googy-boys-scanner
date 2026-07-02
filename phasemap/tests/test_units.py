"""Unit tests: buffer function, clustering, zone merging, zone state ladder."""

import pytest

from phasemap.engine.buffers import asx_tick, buffer, pct_floor
from phasemap.engine.zones import Zone, cluster_levels, merge_targets


def test_asx_tick_bands():
    assert asx_tick(0.05) == 0.001
    assert asx_tick(0.10) == 0.005
    assert asx_tick(1.50) == 0.005
    assert asx_tick(2.00) == 0.01
    assert asx_tick(25.0) == 0.01


def test_pct_floor_bands():
    assert pct_floor(0.05) == 0.020
    assert pct_floor(0.50) == 0.010
    assert pct_floor(5.00) == 0.005


def test_buffer_takes_the_max_component():
    # cents stock, tiny ATR: tick component dominates (2 * 0.001)
    assert buffer(0.05, 0.001) == pytest.approx(0.002)
    # dollar stock, large ATR: half-ATR dominates
    assert buffer(1.50, 0.10) == pytest.approx(0.05)
    # big price, small ATR: percentage floor dominates (0.005 * 20)
    assert buffer(20.0, 0.01) == pytest.approx(0.10)


def test_cluster_levels_chains_within_tolerance():
    levels = [1.00, 1.005, 1.009, 1.05, 1.052]
    out = cluster_levels(levels, 0.006)
    assert out == [(1.00, 1.009, 3), (1.05, 1.052, 2)]


def test_cluster_levels_empty():
    assert cluster_levels([], 0.01) == []


def test_merge_targets_unions_overlaps_and_counts_confluence():
    z = lambda lo, hi, src: Zone(id="t", type="TARGET", low=lo, high=hi,
                                 side="above", sources=[src])
    merged = merge_targets([z(1.00, 1.05, "a"), z(1.04, 1.10, "b"),
                            z(1.20, 1.25, "c")])
    assert len(merged) == 2
    assert merged[0].low == 1.00 and merged[0].high == 1.10
    assert merged[0].confluence == 2
    assert sorted(merged[0].sources) == ["a", "b"]
    assert merged[1].confluence == 1


def test_zone_ladder_target_above():
    z = Zone(id="t1", type="TARGET", low=1.10, high=1.15, side="above")
    z.update(1.00, 1.05, 0.98, 1.04)          # no touch
    assert z.status == "UNTESTED"
    # wick into band + close back away on the same bar = touch AND respect
    z.update(1.05, 1.12, 1.03, 1.08)
    assert z.status == "RESPECTED"
    # a touch where price CLOSES inside the band is a plain test
    z2 = Zone(id="t1b", type="TARGET", low=1.10, high=1.15, side="above")
    z2.update(1.05, 1.13, 1.03, 1.12)
    assert z2.status == "TESTED"
    z.update(1.06, 1.20, 1.05, 1.18)          # daily close beyond far edge
    assert z.status == "CONSUMED"
    z.update(1.18, 1.19, 1.00, 1.01)          # terminal — never resurrects
    assert z.status == "CONSUMED"


def test_zone_ladder_demand_below():
    z = Zone(id="demand", type="DEMAND", low=0.945, high=0.960, side="below")
    z.update(0.98, 0.99, 0.955, 0.975)        # wick in, close back above
    assert z.status == "RESPECTED"
