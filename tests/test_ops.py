"""scripts/ops.py -- the redaction is the only security property, so most of
this file tests what the script refuses to print."""
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ops", ROOT / "scripts" / "ops.py")
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)

ENV = {
    "CRONJOB_API_KEY": "cronjob-key-FAKE-000001",
    "CLOUDFLARE_API_TOKEN": "cloudflare-tok-FAKE-000002",
    "CLOUDFLARE_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
}


# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

def test_every_secret_value_is_masked_out_of_printed_text():
    text = "bearer cronjob-key-FAKE-000001 / cloudflare-tok-FAKE-000002 / 0123456789abcdef0123456789abcdef"
    out = ops.redact(text, env=ENV)
    for v in ENV.values():
        assert v not in out
    assert out.count("***") == 3


def test_key_query_params_in_job_urls_are_masked():
    url = "https://x.pages.dev/api/morning_plays?slot=us&key=1234567891011121314151617181920"
    out = ops.redact(url, env={})
    assert "1234567891011121314151617181920" not in out
    assert "slot=us" in out and "key=***" in out


def test_caller_supplied_values_are_masked_too():
    out = ops.redact("value was callervalue-FAKE-000003", env={}, extra=["callervalue-FAKE-000003"])
    assert "callervalue-FAKE-000003" not in out


def test_cf_list_vars_prints_names_and_types_but_never_values():
    """Cloudflare returns plain_text values in the clear; a run log on a public
    repo must never carry them (GH_DISPATCH_TOKEN was stored as Text)."""
    project = {"result": {"deployment_configs": {"production": {"env_vars": {
        "GH_DISPATCH_TOKEN": {"type": "plain_text", "value": "PLAINVALUE-MUST-NOT-PRINT"},
        "TICK_SECRET": {"type": "secret_text"},
    }}}}}
    summary = ops.cf_vars_summary(project)
    assert summary == {"GH_DISPATCH_TOKEN": "plain_text", "TICK_SECRET": "secret_text"}
    assert "PLAINVALUE-MUST-NOT-PRINT" not in json.dumps(summary)


def test_cf_list_vars_action_returns_only_the_summary(monkeypatch):
    seen = {}

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        seen.update(method=method, url=url, headers=headers)
        return 200, {"result": {"deployment_configs": {"production": {"env_vars": {
            "GH_DISPATCH_TOKEN": {"type": "plain_text", "value": "PLAINVALUE-MUST-NOT-PRINT"}}}}}}

    monkeypatch.setattr(ops, "call", fake_call)
    status, result = ops.run("cf-list-vars", {}, env=ENV)
    assert status == 200
    assert "PLAINVALUE-MUST-NOT-PRINT" not in json.dumps(result)
    assert seen["method"] == "GET"
    assert seen["url"].endswith("/pages/projects/googy-boys-scanner")
    assert seen["headers"]["Authorization"] == "Bearer " + ENV["CLOUDFLARE_API_TOKEN"]


# --------------------------------------------------------------------------
# request shapes
# --------------------------------------------------------------------------

def test_cronjob_create_builds_the_documented_job_shape(monkeypatch):
    seen = {}

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        seen.update(method=method, url=url, body=body, headers=headers)
        return 200, {"jobId": 42}

    monkeypatch.setattr(ops, "call", fake_call)
    args = {"title": "slot=us", "url": "https://x/api?slot=us&key=k",
            "minutes": [35], "hours": [6], "timezone": "Australia/Melbourne"}
    status, result = ops.run("cronjob-create", args, env=ENV)
    assert (status, result) == (200, {"jobId": 42})
    assert seen["method"] == "PUT" and seen["url"] == ops.CRONJOB_API + "/jobs"
    assert seen["headers"]["Authorization"] == "Bearer " + ENV["CRONJOB_API_KEY"]
    job = seen["body"]["job"]
    assert job["title"] == "slot=us" and job["url"].endswith("key=k")
    assert job["enabled"] is True and job["saveResponses"] is True and job["requestMethod"] == 0
    assert job["schedule"] == {"timezone": "Australia/Melbourne", "minutes": [35], "hours": [6],
                               "mdays": [-1], "months": [-1], "wdays": [-1]}


def test_cronjob_update_sends_only_the_fields_given(monkeypatch):
    seen = {}

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        seen.update(method=method, url=url, body=body)
        return 200, {}

    monkeypatch.setattr(ops, "call", fake_call)
    ops.run("cronjob-update", {"id": 7, "enabled": False}, env=ENV)
    assert seen["method"] == "PATCH" and seen["url"] == ops.CRONJOB_API + "/jobs/7"
    assert seen["body"] == {"job": {"enabled": False}}


def test_cf_set_var_patches_the_production_config(monkeypatch):
    seen = {}

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        seen.update(method=method, url=url, body=body)
        return 200, {"result": {"deployment_configs": {"production": {"env_vars": {
            "NEW": {"type": "secret_text"}}}}}}

    monkeypatch.setattr(ops, "call", fake_call)
    status, result = ops.run("cf-set-var", {"name": "NEW", "value": "v"}, env=ENV)
    assert seen["method"] == "PATCH"
    assert seen["body"] == {"deployment_configs": {"production": {"env_vars": {
        "NEW": {"type": "secret_text", "value": "v"}}}}}
    assert result == {"set": "NEW", "type": "secret_text", "env_vars": {"NEW": "secret_text"}}


def test_cf_delete_var_sends_null(monkeypatch):
    seen = {}

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        seen.update(body=body)
        return 200, {"result": {}}

    monkeypatch.setattr(ops, "call", fake_call)
    ops.run("cf-delete-var", {"name": "OLD"}, env=ENV)
    assert seen["body"] == {"deployment_configs": {"production": {"env_vars": {"OLD": None}}}}


def test_cf_redeploy_posts_a_production_deployment(monkeypatch):
    seen = {}

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        seen.update(method=method, url=url, raw=raw_body, headers=headers)
        return 200, {"result": {"id": "dep1", "url": "https://dep1.x.pages.dev",
                                "latest_stage": {"name": "queued"}}}

    monkeypatch.setattr(ops, "call", fake_call)
    status, result = ops.run("cf-redeploy", {}, env=ENV)
    assert seen["method"] == "POST" and seen["url"].endswith("/deployments")
    assert b'name="branch"' in seen["raw"] and b"main" in seen["raw"]
    assert seen["headers"]["Content-Type"].startswith("multipart/form-data")
    assert result["deployment_id"] == "dep1" and result["stage"] == "queued"


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

@pytest.mark.parametrize("action,missing", [
    ("cronjob-list", "CRONJOB_API_KEY"),
    ("cf-list-vars", "CLOUDFLARE_API_TOKEN"),
])
def test_a_missing_secret_names_itself_and_never_calls_out(monkeypatch, action, missing):
    monkeypatch.setattr(ops, "call", lambda *a, **k: pytest.fail("must not call out"))
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(ops.OpsError, match=missing):
        ops.run(action, {}, env=env)


def test_an_unknown_action_is_refused_before_any_secret_is_read(monkeypatch):
    monkeypatch.setattr(ops, "call", lambda *a, **k: pytest.fail("must not call out"))
    with pytest.raises(ops.OpsError, match="unknown action"):
        ops.run("cronjob-nuke", {}, env=ENV)


def test_main_exit_codes_and_redacted_output(monkeypatch, capsys):
    monkeypatch.setattr(ops, "call", lambda *a, **k: (401, {"error": "bad key cronjob-key-FAKE-000001"}))
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    rc = ops.main(["cronjob-list", "{}"])
    out = capsys.readouterr().out
    assert rc == 1 and "HTTP 401" in out
    assert "cronjob-key-FAKE-000001" not in out
    assert ops.main(["cronjob-list", "not json"]) == 2
    assert ops.main([]) == 2


def test_the_workflow_uses_the_script_through_env_and_declares_the_three_secrets():
    wf = (ROOT / ".github" / "workflows" / "ops.yml").read_text()
    for s in ("CRONJOB_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        assert f"{s}: ${{{{ secrets.{s} }}}}" in wf
    assert 'python3 scripts/ops.py "$ACTION" "$ARGS"' in wf
    assert "permissions:\n  contents: read" in wf
    assert "git " not in wf.split("jobs:")[1], "ops.yml must never touch git"
    for a in ops.ACTIONS:
        assert f"- {a}\n" in wf, f"{a} missing from the dispatch choice list"
