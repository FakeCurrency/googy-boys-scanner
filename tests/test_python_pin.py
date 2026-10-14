"""Every job that runs the repo's Python runs it on the repo's interpreter
(REFINE200 #85, 2026-10-14).

CI runs 3.12 (actions/setup-python) and the owner's venv is newer, but
reco_note.yml and backup_book.yml called the runner IMAGE's python3 -- a
version that moves whenever ubuntu-latest does, untested by anything. The
only jobs allowed the system python3 are the deliberate pre-pip GATES, whose
whole point is to decide in seconds whether the expensive job runs at all.

Scope: the workflows this package owns (the lens and evidence workflows pin
their own gates in their own suites).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ("kill_switch.yml", "crypto_bot.yml", "scan.yml", "backup_book.yml",
             "reco_note.yml", "morning_plays.yml", "lens_backtest.yml",
             "vivek_backtest.yml", "test_alerts.yml")
# (workflow, job): stdlib-only gates that run before any setup/pip, by design.
SYSTEM_PYTHON_GATES = {("scan.yml", "gate"), ("crypto_bot.yml", "gate")}
_PY = re.compile(r"(^|[\s|;(])python3?(\s|$)")


def _jobs():
    for wf in WORKFLOWS:
        doc = yaml.safe_load((ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"))
        for name, job in doc["jobs"].items():
            yield wf, name, job


@pytest.mark.parametrize("wf,name,job", list(_jobs()), ids=lambda v: v if isinstance(v, str) else "")
def test_python_runs_on_the_pinned_interpreter(wf, name, job):
    steps = job.get("steps", [])
    setup = [i for i, s in enumerate(steps)
             if str(s.get("uses", "")).startswith("actions/setup-python")]
    runs_py = [i for i, s in enumerate(steps) if _PY.search(s.get("run") or "")]
    if not runs_py:
        return
    if (wf, name) in SYSTEM_PYTHON_GATES:
        assert not setup, f"{wf}:{name} is a pre-pip gate; it should not pay for setup-python"
        return
    assert setup, f"{wf}:{name} runs python on the runner image's interpreter"
    assert setup[0] < runs_py[0], f"{wf}:{name} runs python before setup-python"
    assert str(steps[setup[0]]["with"]["python-version"]) == "3.12"
