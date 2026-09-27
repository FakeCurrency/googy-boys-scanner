"""scanner.vps.publish -- the whole-file re-apply loop, against REAL temp repos.

deploy/DESIGN.md section 8: a dirty tracked file outside the path list still
publishes; whole-file re-apply keeps an upstream sibling; rebuild-combined runs
in the clone; must-change ANY-OF / per-market / manual branches; push rejection
retries then succeeds; a non-VPS data commit upstream HALTs and nothing is
pushed; a failed attempt leaves the clone clean; redaction.

Layout per test: ``origin.git`` (bare) <- ``home`` (the working checkout, never
committed to) and ``publish`` (the clone the loop commits from). A third clone
``other`` plays the second writer / the racing pusher. The only subprocess the
loop spawns besides git (``vivek_run --rebuild-combined`` / ``--verify``) is
replaced by a stub that writes the two derived files, so nothing here needs
the scan engine.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess

import pytest

from scanner import config
from scanner.vps import jobs as J
from scanner.vps import ledger as LG
from scanner.vps import publish as P

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 29, 5, 31, tzinfo=UTC)
VPS = ("vivek5-vps", "294004674+FakeCurrency@users.noreply.github.com")
BOT = ("github-actions[bot]", "github-actions[bot]@users.noreply.github.com")
SEED_FILES = {
    "README.md": "readme\n",
    "journal/vivek_bot_book.json": '{"open": [], "closed": [], "updated_at": "seed"}\n',
    "journal/vivek_bot_book.asx.json": '{"market": "asx", "open": [], "v": 1}\n',
    "journal/vivek_bot_book.nasdaq.json": '{"market": "nasdaq", "open": [], "v": 1}\n',
    "journal/vivek_bot_book.crypto.json": '{"market": "crypto", "open": [], "v": 1}\n',
    "journal/alert_state.json": '{"seed": true}\n',
    "journal/confluence_state.json": "{}\n",
    "public/data/vivek_bot_book.json": '{"open": [], "closed": [], "updated_at": "seed"}\n',
    "public/data/reco_note.json": '{"date": "2026-09-28", "note": "old"}\n',
    "public/data/asx_vivek.json": '{"generated_at": "seed", "results": []}\n',
    "public/data/asx_prices.json": '{"generated_at": "seed"}\n',
    "public/data/nasdaq_vivek.json": '{"generated_at": "seed"}\n',
    "public/data/phasemap/asx/latest.json": '{"run_date": "seed"}\n',
    "public/data/phasemap/nasdaq/latest.json": '{"run_date": "seed"}\n',
    "public/data/phasemap/crypto/latest.json": '{"run_date": "seed"}\n',
    "public/data/asx_spec.json": '{"generated_at": "seed"}\n',
    "public/data/nasdaq_spec.json": '{"generated_at": "seed"}\n',
    "data/history/asx/AAA.json": "[1]\n",
    "data/history/asx/BBB.json": "[2]\n",
    "data/alert_forward_returns.json": '{"entries": []}\n',
    "data/edge_rosters.json": '{"entries": []}\n',
    "public/data/book_stress.json": '{"generated_at": "seed"}\n',
    "public/data/edge_summary.json": '{"generated_at": "seed"}\n',
    "backups/2026-09-27T21-35-00/manifest.json": "{}\n",
}
EDGE_JOB = "alert" + "_returns.yml"        # keep the literal out of this file's grep footprint


def git(cwd, *args, ident=VPS, check=True, env=None):
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": ident[0], "GIT_AUTHOR_EMAIL": ident[1],
              "GIT_COMMITTER_NAME": ident[0], "GIT_COMMITTER_EMAIL": ident[1],
              "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd)})
    if env:
        e.update(env)
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=e)
    if check and res.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} in {cwd}: {res.stderr}")
    return res


def write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def commit_in(clone: pathlib.Path, files: dict, msg: str, ident=VPS, push=True) -> str:
    """Commit (and push) files from another clone -- the second writer / racer."""
    git(clone, "fetch", "origin", "main")
    git(clone, "reset", "-q", "--hard", "origin/main")
    for rel, text in files.items():
        if text is None:
            git(clone, "rm", "-q", "--", rel)
        else:
            write(clone, rel, text)
            git(clone, "add", "--", rel)
    git(clone, "-c", f"user.name={ident[0]}", "-c", f"user.email={ident[1]}", "commit", "-q", "-m", msg, ident=ident)
    if push:
        git(clone, "push", "-q", "origin", "HEAD:main", ident=ident)
    return git(clone, "rev-parse", "HEAD").stdout.strip()


def origin_file(origin: pathlib.Path, rel: str):
    res = git(origin, "show", f"main:{rel}", check=False)
    return res.stdout if res.returncode == 0 else None


def origin_log(origin: pathlib.Path) -> list[str]:
    return git(origin, "log", "--format=%s", "main").stdout.splitlines()


@pytest.fixture
def world(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    for rel, text in SEED_FILES.items():
        write(seed, rel, text)
    git(seed, "add", "-A")
    git(seed, "-c", "user.name=Seed", "-c", "user.email=seed@example.com", "commit", "-q", "-m", "seed",
        ident=("Seed", "seed@example.com"))
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "HEAD:main")
    home, clone, other = tmp_path / "home", tmp_path / "publish", tmp_path / "other"
    for d in (home, clone, other):
        git(tmp_path, "clone", "-q", str(origin), str(d))
    state = tmp_path / "state"
    state.mkdir()
    head = git(origin, "rev-parse", "main").stdout.strip()
    (state / "publish_head").write_text(head + "\n")
    monkeypatch.setenv("GIT_AUTHOR_NAME", VPS[0])
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", VPS[1])
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("VIVEK_GIT_PUBLISH", raising=False)
    monkeypatch.setenv("VIVEK_HOME", str(home))
    monkeypatch.setenv("VIVEK_PUBLISH", str(clone))
    monkeypatch.setenv("VIVEK_STATE_DIR", str(state))

    class W:
        pass
    w = W()
    w.origin, w.home, w.clone, w.other, w.state, w.seed_sha = origin, home, clone, other, state, head
    w.alerts = []
    w.notify = lambda sev, title, details="": w.alerts.append((sev, title, details)) or []
    w.rebuild_calls = []

    def stub_exec(argv, *, cwd, env):
        w.rebuild_calls.append({"argv": list(argv), "cwd": cwd, "env": dict(env)})
        if "--rebuild-combined" in argv:
            canon = {}
            for m in config.MARKETS:
                p = pathlib.Path(cwd) / "journal" / f"vivek_bot_book.{m}.json"
                canon[m] = json.loads(p.read_text()) if p.exists() else None
            text = json.dumps({"derived_from": canon}) + "\n"
            for rel in ("journal/vivek_bot_book.json", "public/data/vivek_bot_book.json"):
                write(pathlib.Path(cwd), rel, text)
            return 0, "combined view rebuilt: 0 open, 0 closed"
        if "--verify" in argv:
            return 0, "book verify OK - 3 market file(s)"
        return 1, "unexpected"
    w.exec = stub_exec
    w.sleeps = []
    w.publish = lambda job, args, ctx, **kw: P.publish(
        job, args, ctx, home=home, clone=clone, state_dir=state, python="PY", exec_fn=w.exec,
        sleep=lambda s: w.sleeps.append(s), now=NOW, notify=w.notify, **kw)
    return w


def reco(w, note="new note"):
    write(w.home, "public/data/reco_note.json", json.dumps({"date": "2026-09-29", "note": note}) + "\n")
    return J.JOBS["reco_note.yml"], {}, {"captures": {"reco": "reco_note.json written for 2026-09-29"}}


# ── the loop ──────────────────────────────────────────────────────────────────

def test_a_dirty_tracked_file_outside_the_list_still_publishes_and_the_checkout_is_untouched(world):
    w = world
    write(w.home, "journal/alert_state.json", '{"dirty": 1}\n')          # tracked, never staged
    write(w.home, "stray.txt", "untracked debris\n")
    job, args, ctx = reco(w)
    res = w.publish(job, args, ctx)
    assert res.status == "pushed" and res.exit_code == 0 and res.sha, res.lines
    assert origin_log(w.origin)[0] == "data: recommendations note 2026-09-29"
    assert json.loads(origin_file(w.origin, "public/data/reco_note.json"))["note"] == "new note"
    assert origin_file(w.origin, "journal/alert_state.json") == SEED_FILES["journal/alert_state.json"]
    assert origin_file(w.origin, "stray.txt") is None
    # the working checkout's git state never moved
    assert git(w.home, "rev-parse", "HEAD").stdout.strip() == w.seed_sha
    assert " M journal/alert_state.json" in git(w.home, "status", "--porcelain").stdout
    assert (w.state / "publish_head").read_text().strip() == res.sha
    assert git(w.clone, "status", "--porcelain").stdout == ""
    author = git(w.origin, "log", "-1", "--format=%an <%ae>", "main").stdout.strip()
    assert author == f"{VPS[0]} <{VPS[1]}>"
    assert w.rebuild_calls == [], "reco_note has no combined book to rebuild"


def test_whole_file_reapply_keeps_an_upstream_sibling_and_rebuilds_the_combined_book_in_the_clone(world):
    w = world
    # upstream (another VPS run, same identity) refreshed nasdaq while this asx run was scanning
    commit_in(w.other, {"journal/vivek_bot_book.nasdaq.json": '{"market": "nasdaq", "v": 2}\n',
                        "public/data/nasdaq_vivek.json": '{"generated_at": "newer"}\n'}, "data: scan 2026-09-29 05:07 UTC")
    write(w.home, "journal/vivek_bot_book.asx.json", '{"market": "asx", "v": 9}\n')
    write(w.home, "public/data/asx_vivek.json", '{"generated_at": "mine"}\n')
    write(w.home, "public/data/asx_prices.json", '{"generated_at": "mine"}\n')
    write(w.home, "journal/vivek_bot_book.json", '{"stale": "snapshot"}\n')   # the run's own derived copy
    (w.home / "data" / "history" / "asx" / "BBB.json").unlink()                 # this run removed a file
    write(w.home, "data/history/asx/CCC.json", "[3]\n")
    job = J.JOBS["scan.yml"]
    args = J.parse_args(job, {"market": "asx", "slot": "hourly"})
    res = w.publish(job, args, {"scanned_market": "asx", "captures": {}})
    assert res.status == "pushed", res.lines
    assert json.loads(origin_file(w.origin, "journal/vivek_bot_book.asx.json"))["v"] == 9, "this run's copy wins"
    assert json.loads(origin_file(w.origin, "journal/vivek_bot_book.nasdaq.json"))["v"] == 2, "the sibling's newer copy is kept"
    assert origin_file(w.origin, "public/data/nasdaq_vivek.json") == '{"generated_at": "newer"}\n'
    combined = json.loads(origin_file(w.origin, "journal/vivek_bot_book.json"))
    assert combined["derived_from"]["asx"]["v"] == 9 and combined["derived_from"]["nasdaq"]["v"] == 2, \
        "the combined book is REBUILT from both canonical files, not replayed from the run's snapshot"
    assert origin_file(w.origin, "public/data/vivek_bot_book.json") == origin_file(w.origin, "journal/vivek_bot_book.json")
    assert origin_file(w.origin, "data/history/asx/BBB.json") is None, "a directory pathspec mirrors deletions"
    assert origin_file(w.origin, "data/history/asx/CCC.json") == "[3]\n"
    rebuild, verify = w.rebuild_calls
    assert rebuild["argv"] == ["PY", "-m", "scanner.broker.vivek_run", "--rebuild-combined"]
    assert rebuild["cwd"] == str(w.clone) and "PYTHONPATH" not in rebuild["env"]
    assert verify["argv"][-1] == "--verify" and verify["cwd"] == str(w.clone)
    assert origin_log(w.origin)[0] == "data: scan 2026-09-29 05:31 UTC"


def test_scheduled_scan_asserts_per_market_hard_and_a_skip_marker_downgrades_only_that_market(world):
    w = world
    job = J.JOBS["scan.yml"]
    args = J.parse_args(job, {"market": "asx", "slot": "hourly"})
    write(w.home, "public/data/asx_vivek.json", '{"generated_at": "mine"}\n')     # book NOT re-stamped
    res = w.publish(job, args, {"scanned_market": "asx", "captures": {}})
    assert res.status == "failed" and res.exit_code == 1
    assert any("ASSERT-STAGED FAILED (bot book [asx])" in ln for ln in res.lines)
    assert origin_log(w.origin) == ["seed"] and git(w.clone, "status", "--porcelain").stdout == ""
    assert w.alerts and w.alerts[-1][0] == "WARNING"
    # the same run with .scan-skipped naming asx: advisory only, nothing else to commit -> green
    write(w.home, config.SCAN_SKIP_MARKER, "asx\r\n")
    write(w.home, "public/data/asx_vivek.json", SEED_FILES["public/data/asx_vivek.json"])
    res = w.publish(job, args, {"scanned_market": "asx", "captures": {}})
    assert res.status in ("nothing", "pushed") and res.exit_code == 0, res.lines
    assert any("asx: no data downloaded" in ln for ln in res.lines)
    assert any("every market this cycle (asx) published nothing" in ln for ln in res.lines)
    (w.home / config.SCAN_SKIP_MARKER).unlink()
    # manual branch: one SOFT assert, a test run that stages nothing is green
    manual = J.parse_args(job, {"market": "asx", "reason": "manual"})
    res = w.publish(job, manual, {"scanned_market": "asx", "captures": {}})
    assert res.status == "nothing" and res.exit_code == 0
    assert any("book not staged (manual run" in ln for ln in res.lines)


def test_crypto_in_a_full_cycle_is_soft_but_a_crypto_only_scheduled_run_is_hard(world):
    w = world
    job = J.JOBS["scan.yml"]
    write(w.home, "journal/vivek_bot_book.asx.json", '{"market": "asx", "v": 2}\n')
    write(w.home, "public/data/asx_vivek.json", '{"generated_at": "x"}\n')
    write(w.home, "journal/vivek_bot_book.nasdaq.json", '{"market": "nasdaq", "v": 2}\n')
    write(w.home, "public/data/nasdaq_vivek.json", '{"generated_at": "x"}\n')
    args = J.parse_args(job, {"market": "all", "slot": "manual", "reason": "cron"})
    res = w.publish(job, args, {"scanned_market": "all", "captures": {}})
    assert res.status == "pushed", res.lines
    assert sum("best-effort leg of a full cycle" in ln for ln in res.lines) == 2


def test_edge_policy_all_four_sentinels_skip_else_any_of(world):
    w = world
    job = J.JOBS[EDGE_JOB]
    caps = {k: t for k, t in (("ar", "ALERT_" + "RETURNS_UNCHANGED"), ("er", "EDGE_" + "ROSTERS_UNCHANGED"),
                              ("bs", "BOOK_" + "STRESS_UNCHANGED"), ("es", "EDGE_" + "SUMMARY_UNCHANGED"))}
    res = w.publish(job, {"slot": "primary"}, {"captures": dict(caps)})
    assert res.status == "skipped" and "Nothing new in any artefact" in res.message
    assert origin_log(w.origin) == ["seed"]
    caps["bs"] = "book stress: base +1R"
    write(w.home, "public/data/book_stress.json", '{"generated_at": "now", "n_long": 3}\n')
    res = w.publish(job, {"slot": "primary"}, {"captures": dict(caps)})
    assert res.status == "pushed" and origin_log(w.origin)[0] == "data: edge ledgers 2026-09-29"
    assert any("assert_staged(edge ledgers): OK" in ln for ln in res.lines)
    res = w.publish(job, {"slot": "primary"}, {"captures": dict(caps)})     # claimed a change, staged nothing
    assert res.status == "failed" and any("ASSERT-STAGED FAILED (edge ledgers)" in ln for ln in res.lines)


def test_phasemap_collects_a_missing_market_and_still_pushes_the_healthy_ones(world):
    w = world
    job = J.JOBS["phasemap.yml"]
    write(w.home, "public/data/phasemap/nasdaq/latest.json", '{"run_date": "2026-09-29"}\n')
    write(w.home, "public/data/phasemap/crypto/latest.json", '{"run_date": "2026-09-29"}\n')
    res = w.publish(job, J.parse_args(job, {}), {"specs_ok": False, "captures": {}})
    assert res.status == "pushed" and res.exit_code == 1, res.lines
    assert json.loads(origin_file(w.origin, "public/data/phasemap/nasdaq/latest.json"))["run_date"] == "2026-09-29"
    assert any("ASSERT-STAGED FAILED (phasemap asx)" in ln for ln in res.lines)
    assert any("Specs reported failure - skipping its must-change gate" in ln for ln in res.lines)
    assert any("a must-change gate tripped" in ln for ln in res.lines)
    res = w.publish(job, J.parse_args(job, {"reason": "manual"}), {"specs_ok": True, "captures": {}})
    assert res.status == "nothing" and res.exit_code == 0 and any("no latest.json staged (manual run)" in ln for ln in res.lines)


def test_push_rejection_retries_from_fetch_and_then_succeeds(world, monkeypatch):
    w = world
    job, args, ctx = reco(w)
    pushes = {"n": 0}
    real_run = subprocess.run

    def racing_run(argv, **kw):
        if argv[:2] == ["git", "push"] and pushes["n"] == 0:
            pushes["n"] += 1
            commit_in(w.other, {"README.md": "someone pushed first\n"}, "docs: race")
        return real_run(argv, **kw)
    res = w.publish(job, args, ctx, run=racing_run)
    assert res.status == "pushed", res.lines
    assert any("Push race - retry 1" in ln for ln in res.lines) and w.sleeps == [2]
    log = origin_log(w.origin)
    assert log[0] == "data: recommendations note 2026-09-29" and log[1] == "docs: race"
    assert origin_file(w.origin, "README.md") == "someone pushed first\n", "rebuilt on top of the newer main"


def test_push_exhaustion_is_loud_and_leaves_the_clone_clean(world):
    w = world
    job, args, ctx = reco(w)

    def always_rejected(argv, **kw):
        if argv[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 1, "", "! [rejected] main -> main (fetch first)")
        return subprocess.run(argv, **kw)
    res = w.publish(job, args, ctx, run=always_rejected, max_attempts=3)
    assert res.status == "failed" and "Could not push after retries" in res.message
    assert w.sleeps == [2, 4] and origin_log(w.origin) == ["seed"]
    assert git(w.clone, "status", "--porcelain").stdout == ""
    assert git(w.clone, "rev-parse", "HEAD").stdout == git(w.clone, "rev-parse", "origin/main").stdout


def test_a_non_vps_data_commit_upstream_HALTS_and_nothing_is_pushed(world):
    w = world
    bot_sha = commit_in(w.other, {"journal/vivek_bot_book.asx.json": '{"market": "asx", "closed_by": "hand"}\n'},
                        "journal: manual close FPH long @ 1.0", ident=BOT)
    job, args, ctx = reco(w)
    res = w.publish(job, args, ctx)
    assert res.status == "halted" and res.exit_code == 4 and res.sha is None
    halt = json.loads((w.state / "HALT").read_text())
    assert halt["shas"] == [bot_sha] and halt["authors"] == [f"{BOT[0]} <{BOT[1]}>"]
    assert halt["paths"] == ["journal/vivek_bot_book.asx.json"] and halt["job"] == "reco_note.yml"
    assert origin_log(w.origin)[0] == "journal: manual close FPH long @ 1.0", "nothing pushed on top"
    assert w.alerts[-1][0] == "CRITICAL" and "second writer" in w.alerts[-1][1]
    assert (w.state / "publish_head").read_text().strip() == w.seed_sha, "publish_head does not advance"
    # a second attempt halts again (the HALT is not consumed by publish); clear-halt moves publish_head
    assert w.publish(job, args, ctx).status == "halted"
    sha = P.clear_halt(state_dir=w.state, clone=w.clone)
    assert sha == bot_sha and not (w.state / "HALT").exists()
    assert w.publish(job, args, ctx).status == "pushed"


def test_a_non_vps_commit_outside_the_data_roots_does_not_halt(world):
    w = world
    commit_in(w.other, {"README.md": "owner edit\n", "scanner/config.py": "# code\n"}, "config: tune", ident=BOT)
    job, args, ctx = reco(w)
    res = w.publish(job, args, ctx)
    assert res.status == "pushed" and not (w.state / "HALT").exists()
    assert origin_file(w.origin, "README.md") == "owner edit\n"


def test_accept_upstream_syncs_data_roots_into_the_checkout_and_clears_the_halt(world):
    w = world
    commit_in(w.other, {"journal/vivek_bot_book.asx.json": '{"market": "asx", "closed_by": "hand"}\n',
                        "data/history/asx/AAA.json": "[1, 1]\n"}, "journal: manual close", ident=BOT)
    job, args, ctx = reco(w)
    assert w.publish(job, args, ctx).status == "halted"
    write(w.home, "journal/vivek_bot_book.asx.json", '{"market": "asx", "v": "vps"}\n')
    synced = P.accept_upstream(state_dir=w.state, clone=w.clone, home=w.home)
    assert "journal/vivek_bot_book.asx.json" in synced and "data/history" in synced
    assert (w.home / "journal" / "vivek_bot_book.asx.json").read_text() == '{"market": "asx", "closed_by": "hand"}\n'
    assert (w.home / "data" / "history" / "asx" / "AAA.json").read_text() == "[1, 1]\n"
    assert not (w.state / "HALT").exists()
    assert git(w.home, "rev-parse", "HEAD").stdout.strip() == w.seed_sha, "files synced, git state untouched"
    assert (w.home / "public" / "data" / "reco_note.json").read_text() == SEED_FILES["public/data/reco_note.json"], \
        "origin is the truth after accept-upstream: the run's unpublished note was overwritten too"
    job, args, ctx = reco(w, "after the halt")
    assert w.publish(job, args, ctx).status == "pushed"


def test_close_position_bot_rebuilds_combined_and_names_the_roster(world):
    w = world
    job = J.JOBS["close_position.yml"]
    batch = json.dumps([{"symbol": "FPH", "market": "asx", "direction": "long", "price": "1"},
                        {"symbol": "XYZ", "market": "nasdaq", "direction": "long", "price": "2"}])
    args = J.parse_args(job, {"symbol": "FPH+1", "market": "asx", "price": "1", "batch": batch})
    write(w.home, "journal/vivek_bot_book.asx.json", '{"market": "asx", "v": "closed"}\n')
    res = w.publish(job, args, {"captures": {}})
    assert res.status == "pushed" and origin_log(w.origin)[0] == "journal: manual close x2 - FPH XYZ"
    assert w.rebuild_calls and w.rebuild_calls[0]["cwd"] == str(w.clone)
    assert json.loads(origin_file(w.origin, "journal/vivek_bot_book.json"))["derived_from"]["asx"]["v"] == "closed"
    w.rebuild_calls.clear()
    single = J.parse_args(job, {"symbol": "ABC", "market": "asx", "price": "3.5", "journal_type": "swing"})
    res = w.publish(job, single, {"captures": {}})
    assert res.status == "nothing" and res.message.startswith("Nothing to commit (position not found")
    assert w.rebuild_calls == [], "a legacy close never touches the bot book"
    write(w.home, "journal/journal.json", '{"open": []}\n')
    res = w.publish(job, single, {"captures": {}})
    assert res.status == "pushed" and origin_log(w.origin)[0] == "journal: manual close ABC long @ 3.5"


def test_reco_sentinel_skips_publish_and_verify_failure_in_the_clone_fails(world):
    w = world
    job, args, ctx = reco(w)
    ctx["captures"]["reco"] = "RECO_NOTE_UNCHANGED - keeping today's hand-written Claude note"
    res = w.publish(job, args, ctx)
    assert res.status == "skipped" and "Hand-written Claude note" in res.message and origin_log(w.origin) == ["seed"]
    cb = J.JOBS["crypto_bot.yml"]
    write(w.home, "journal/vivek_bot_book.crypto.json", '{"market": "crypto", "v": 3}\n')

    def bad_verify(argv, *, cwd, env):
        if "--verify" in argv:
            return 1, "BOOK VERIFY FAIL: journal/vivek_bot_book.json STALE - run --rebuild-combined"
        return w.exec(argv, cwd=cwd, env=env)
    res = P.publish(cb, J.parse_args(cb, {"slot": "hourly"}), {"captures": {}}, home=w.home, clone=w.clone,
                    state_dir=w.state, python="PY", exec_fn=bad_verify, sleep=w.sleeps.append, now=NOW, notify=w.notify)
    assert res.status == "failed" and "--verify exited 1" in res.message
    assert origin_log(w.origin) == ["seed"] and git(w.clone, "status", "--porcelain").stdout == ""


def test_backup_directory_pathspec_stages_the_new_snapshot_and_the_pruned_one(world):
    w = world
    write(w.home, "backups/2026-09-29T21-35-00/journal/vivek_bot_book.json", "{}\n")
    import shutil
    shutil.rmtree(w.home / "backups" / "2026-09-27T21-35-00")
    job = J.JOBS["backup_book.yml"]
    res = w.publish(job, J.parse_args(job, {"slot": "primary"}), {"captures": {}})
    assert res.status == "pushed" and origin_log(w.origin)[0] == "backup: journal state 2026-09-29 05:31 UTC"
    assert origin_file(w.origin, "backups/2026-09-29T21-35-00/journal/vivek_bot_book.json") == "{}\n"
    assert origin_file(w.origin, "backups/2026-09-27T21-35-00/manifest.json") is None


def test_momentum_stages_exactly_its_own_file(world):
    w = world
    job = J.JOBS["momentum.yml"]
    write(w.home, "public/data/momentum/asx.json", '{"generated_at": "2026-09-29T06:41:00Z"}\n')
    write(w.home, "public/data/momentum/nasdaq.json", '{"generated_at": "stray"}\n')
    res = w.publish(job, {"market": "asx"}, {"market": "asx", "file": "asx.json", "captures": {}})
    assert res.status == "pushed" and origin_log(w.origin)[0] == "data: momentum asx 2026-09-29 05:31 UTC"
    assert origin_file(w.origin, "public/data/momentum/nasdaq.json") is None, "one pathspec: the sibling is not swept in"
    assert any("assert_staged(momentum asx): OK" in ln for ln in res.lines)


def test_vivek_backtest_legs_carry_the_leg_in_the_message(world):
    w = world
    job = J.JOBS["vivek_backtest.yml"]
    res = w.publish(job, {}, {"leg": "nasdaq", "captures": {}})
    assert res.status == "nothing" and res.message == "no change"
    write(w.home, "public/data/vivek_backtest_longonly.json", '{"status": "partial"}\n')
    res = w.publish(job, {}, {"leg": "nasdaq", "captures": {}})
    assert res.status == "pushed" and origin_log(w.origin)[0] == "data: VIVEK backtest (long-only) [nasdaq] 2026-09-29 05:31 UTC"


def test_disabled_publish_touches_no_git_and_a_missing_clone_is_loud(world, monkeypatch):
    w = world
    job, args, ctx = reco(w)
    monkeypatch.setenv("VIVEK_GIT_PUBLISH", "0")
    calls = []
    res = w.publish(job, args, ctx, run=lambda argv, **kw: calls.append(argv))
    assert res.status == "disabled" and calls == []
    monkeypatch.delenv("VIVEK_GIT_PUBLISH")
    res = P.publish(job, args, ctx, home=w.home, clone=w.home / "nope", state_dir=w.state, notify=w.notify)
    assert res.status == "failed" and "publish clone missing" in res.message and w.alerts[-1][0] == "CRITICAL"


def test_git_errors_are_redacted_before_they_reach_the_result(world):
    w = world
    job, args, ctx = reco(w)

    def leaky(argv, **kw):
        if argv[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 128, "", "fatal: unable to access 'https://x-access:ghp_SECRET@github.com/o/r/'")
        return subprocess.run(argv, **kw)
    res = w.publish(job, args, ctx, run=leaky)
    assert res.status == "failed" and "ghp_SECRET" not in res.message and "https://***@github.com" in res.message
    assert LG.redact(res.message) == res.message


def test_mirror_dir_matches_rsync_delete_semantics(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    write(src, "a/x.txt", "x")
    write(src, "b/y.txt", "y")
    write(dst, "a/x.txt", "old")
    write(dst, "a/gone.txt", "gone")
    write(dst, "c/deep/z.txt", "z")
    os.utime(src / "a" / "x.txt", (1_600_000_000, 1_600_000_000))
    P.mirror_dir(src, dst)
    assert (dst / "a" / "x.txt").read_text() == "x" and (dst / "b" / "y.txt").read_text() == "y"
    assert not (dst / "a" / "gone.txt").exists() and not (dst / "c").exists()
    assert int(os.stat(dst / "a" / "x.txt").st_mtime) == 1_600_000_000, "timestamps preserved (cp --preserve)"


def test_publish_paths_scope_and_data_roots(world):
    job = J.JOBS["scan.yml"]
    asx = P.publish_paths(job, {"market": "asx"}, {"scanned_market": "asx"})
    assert asx[:15] == list(job.publish.paths) and asx[15:] == [t.replace("{m}", "asx") for t in job.publish.paths_per_market]
    everything = P.publish_paths(job, {"market": "all"}, {"scanned_market": "all"})
    assert len(everything) == 15 + 6 * 3
    assert P.read_skip_marker(world.home) == []
    write(world.home, config.SCAN_SKIP_MARKER, "nasdaq\r\ncrypto\n")
    assert P.read_skip_marker(world.home) == ["nasdaq", "crypto"]
    assert P.close_roster({"batch": json.dumps([{"symbol": f"S{i}"} for i in range(12)])}).endswith("S8 S9 ...")
    assert P.close_roster({"symbol": "FPH", "direction": "long", "price": "12.34"}) == "FPH long @ 12.34"
