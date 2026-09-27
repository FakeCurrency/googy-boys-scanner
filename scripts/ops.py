"""ops.py -- Claude's standing-access hands for the two dashboards it cannot
reach: cron-job.org and Cloudflare Pages -- and, since the VPS kit
(deploy/DESIGN.md, 2026-09-27), the box's own /api/dispatch.

WHY THIS EXISTS (2026-09-10, owner: "you should be able to set up jobs and all
to make this hands off"). The plays-digest trigger took the owner a night of
screenshots because the only two things it needed -- a Cloudflare env var and a
cron-job.org job -- live behind dashboards a cloud Claude session cannot log
into, and the session's egress proxy refuses api.cron-job.org and
api.cloudflare.com outright (HTTP 000). A GitHub Actions runner has neither
limit. So this script runs INSIDE ops.yml: Claude dispatches the workflow with
an `action` + JSON `args`, the runner calls the API with a secret only it can
read, and Claude reads the result back off the job log / step summary.

Stdlib (urllib + json) plus ONE repo import, `scanner.config.clean_secret`
-- config.py itself imports nothing beyond the stdlib, so ops.yml still runs
without a pip install. No repo writes, no git.

ACTIONS
    cronjob-list                       every job on the account
    cronjob-get      {"id": N}
    cronjob-history  {"id": N}         recent executions + predictions
    cronjob-create   {"title","url","minutes":[35],"hours":[6],"wdays":[-1],
                      "timezone":"Australia/Melbourne","enabled":true,
                      "saveResponses":true}
    cronjob-update   {"id": N, ...any of the create fields}
    cronjob-delete   {"id": N}
    cf-list-vars                       production env var NAMES + types only
    cf-set-var       {"name","value","type":"secret_text"|"plain_text"}
    cf-delete-var    {"name"}
    cf-redeploy                        new production deployment (picks up vars)
    vps-dispatch     {"workflow":"scan.yml","inputs":{"market":"asx"}}
                                       POST {workflow, inputs} to the VPS's
                                       /api/dispatch with the bearer token.
                                       THIS is how a cloud Claude session
                                       starts a scan / close / plays digest
                                       after cutover: dispatch_scan.yml and
                                       the scan-kick are disabled then, and
                                       the session's proxy cannot reach the
                                       box. The adapter validates the pair
                                       (deploy/DESIGN.md 3.5) and answers
                                       202 {ok,id} / 400 / 401 / 422 / 429.

SECRETS (GitHub Actions secrets, read from env -- never printed)
    CRONJOB_API_KEY          cron-job.org -> Settings -> API -> Create key
    CLOUDFLARE_API_TOKEN     Cloudflare -> My Profile -> API Tokens ->
                             custom token, permission "Cloudflare Pages: Edit"
    CLOUDFLARE_ACCOUNT_ID    the 32-hex id in every dash.cloudflare.com URL
    VPS_DISPATCH_URL         https://<VIVEK_DOMAIN>/api/dispatch (https ONLY --
                             the token rides in a header; plain http would
                             carry it in clear and is refused)
    VPS_DISPATCH_TOKEN       the DISPATCH_TOKEN install.sh generated into
                             /etc/vivek5/api.env (the same value cutover puts
                             in Cloudflare Pages). Both are read through
                             config.clean_secret (the 2026-08-01 BOM lesson).

REDACTION IS THE ONLY SECURITY PROPERTY HERE and it is pinned in
tests/test_ops.py: any secret value present in the environment is masked out of
everything printed, `key=...` query values in job URLs are masked, and
cf-list-vars prints names and types but NEVER values -- Cloudflare returns
plain_text values in the clear, and a run log is a public artefact on a public
repo. `GH_DISPATCH_TOKEN` was stored as plain Text at the time of writing;
this is exactly the leak that rule prevents.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from scanner import config as _config  # noqa: E402  (clean_secret only; stdlib-only module)

CRONJOB_API = "https://api.cron-job.org"
CF_API = "https://api.cloudflare.com/client/v4"
CF_PAGES_PROJECT = os.environ.get("CF_PAGES_PROJECT", "googy-boys-scanner")
UA = "vivek5-ops/1.0"
TIMEOUT_S = 30

# Every value here is masked out of everything printed. The VPS URL is in the
# list on purpose: the repo is public, so a run log naming the box's hostname
# is a disclosure -- its hostname is masked on its own as well (see
# _secret_values), because an SSL error quotes the host without the URL.
SECRET_ENV = ("CRONJOB_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
              "VPS_DISPATCH_URL", "VPS_DISPATCH_TOKEN")

ACTIONS = (
    "cronjob-list", "cronjob-get", "cronjob-history", "cronjob-create",
    "cronjob-update", "cronjob-delete",
    "cf-list-vars", "cf-set-var", "cf-delete-var", "cf-redeploy",
    "vps-dispatch",
)


class OpsError(Exception):
    pass


# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

def _secret_values(env=None):
    env = os.environ if env is None else env
    vals = []
    for k in SECRET_ENV:
        for v in {(env.get(k) or "").strip(), _config.clean_secret(env.get(k))}:
            if len(v) >= 6:
                vals.append(v)
    try:
        host = urllib.parse.urlsplit(_config.clean_secret(env.get("VPS_DISPATCH_URL"))).hostname or ""
    except ValueError:
        host = ""
    if len(host) >= 6:
        vals.append(host)
    return vals


def redact(text, env=None, extra=()):
    """Mask every secret value and every `key=<value>` query parameter."""
    out = str(text)
    for v in list(_secret_values(env)) + [e for e in extra if e and len(str(e)) >= 6]:
        out = out.replace(str(v), "***")
    out = re.sub(r"([?&](?:key|token|secret)=)[^&\s\"']+", r"\1***", out)
    return out


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies Authorization onto a 30x target of ANY host/scheme; the
    VPS client must never do that (a 3xx comes back as its own status)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def call(method, url, headers=None, body=None, raw_body=None, follow_redirects=True):
    """One request. Returns (status, parsed_json_or_text). Never raises on an
    HTTP status -- the caller decides what a 4xx means. follow_redirects=False
    answers a 3xx with its own status instead of re-sending the headers."""
    data = None
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    if raw_body is not None:
        data = raw_body
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    opener = urllib.request.urlopen if follow_redirects else _NO_REDIRECT_OPENER.open
    try:
        with opener(req, timeout=TIMEOUT_S) as resp:
            status = resp.status
            payload = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        payload = e.read().decode("utf-8", "replace")
    try:
        return status, json.loads(payload) if payload.strip() else {}
    except ValueError:
        return status, payload


# --------------------------------------------------------------------------
# cron-job.org
# --------------------------------------------------------------------------

def _cj_headers(env):
    key = (env.get("CRONJOB_API_KEY") or "").strip()
    if not key:
        raise OpsError("CRONJOB_API_KEY is not set (GitHub Actions secret)")
    return {"Authorization": f"Bearer {key}"}


_JOB_FIELDS = ("title", "url", "enabled", "saveResponses", "requestMethod")
_SCHED_FIELDS = ("timezone", "minutes", "hours", "mdays", "months", "wdays", "expiresAt")


def cronjob_body(args):
    """Translate the flat args dict into cron-job.org's {"job": {...}} shape.
    Only fields present in args are sent, so an update touches nothing else."""
    job = {k: args[k] for k in _JOB_FIELDS if k in args}
    sched = {k: args[k] for k in _SCHED_FIELDS if k in args}
    if sched:
        # -1 means "every" on cron-job.org; a create needs every axis stated.
        if "mdays" not in sched:
            sched["mdays"] = [-1]
        if "months" not in sched:
            sched["months"] = [-1]
        if "wdays" not in sched:
            sched["wdays"] = [-1]
        job["schedule"] = sched
    return {"job": job}


def _need_id(args):
    try:
        return int(args["id"])
    except (KeyError, TypeError, ValueError):
        raise OpsError('args needs an integer "id"')


def do_cronjob(action, args, env):
    h = _cj_headers(env)
    if action == "cronjob-list":
        return call("GET", f"{CRONJOB_API}/jobs", h)
    if action == "cronjob-get":
        return call("GET", f"{CRONJOB_API}/jobs/{_need_id(args)}", h)
    if action == "cronjob-history":
        return call("GET", f"{CRONJOB_API}/jobs/{_need_id(args)}/history", h)
    if action == "cronjob-create":
        if not args.get("url"):
            raise OpsError('cronjob-create needs a "url"')
        body = cronjob_body(args)
        body["job"].setdefault("enabled", True)
        body["job"].setdefault("saveResponses", True)
        body["job"].setdefault("requestMethod", 0)
        return call("PUT", f"{CRONJOB_API}/jobs", h, body)
    if action == "cronjob-update":
        jid = _need_id(args)
        return call("PATCH", f"{CRONJOB_API}/jobs/{jid}", h, cronjob_body(args))
    if action == "cronjob-delete":
        return call("DELETE", f"{CRONJOB_API}/jobs/{_need_id(args)}", h)
    raise OpsError(f"unknown cronjob action {action}")


# --------------------------------------------------------------------------
# Cloudflare Pages
# --------------------------------------------------------------------------

def _cf(env):
    tok = (env.get("CLOUDFLARE_API_TOKEN") or "").strip()
    acct = (env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not tok:
        raise OpsError("CLOUDFLARE_API_TOKEN is not set (GitHub Actions secret)")
    if not acct:
        raise OpsError("CLOUDFLARE_ACCOUNT_ID is not set (GitHub Actions secret)")
    base = f"{CF_API}/accounts/{acct}/pages/projects/{CF_PAGES_PROJECT}"
    return {"Authorization": f"Bearer {tok}"}, base


def cf_vars_summary(project_json):
    """Names + types only. NEVER values -- see the module docstring."""
    try:
        env_vars = project_json["result"]["deployment_configs"]["production"]["env_vars"] or {}
    except (KeyError, TypeError):
        return {}
    return {name: (spec or {}).get("type", "?") for name, spec in env_vars.items()}


def do_cloudflare(action, args, env):
    h, base = _cf(env)
    if action == "cf-list-vars":
        status, js = call("GET", base, h)
        if status == 200 and isinstance(js, dict):
            return status, {"env_vars": cf_vars_summary(js)}
        return status, js
    if action == "cf-set-var":
        name, value = args.get("name"), args.get("value")
        if not name or value is None:
            raise OpsError('cf-set-var needs "name" and "value"')
        vtype = args.get("type", "secret_text")
        if vtype not in ("secret_text", "plain_text"):
            raise OpsError('type must be secret_text or plain_text')
        body = {"deployment_configs": {"production": {"env_vars": {name: {"type": vtype, "value": value}}}}}
        status, js = call("PATCH", base, h, body)
        if status == 200 and isinstance(js, dict):
            return status, {"set": name, "type": vtype, "env_vars": cf_vars_summary(js)}
        return status, js
    if action == "cf-delete-var":
        name = args.get("name")
        if not name:
            raise OpsError('cf-delete-var needs "name"')
        body = {"deployment_configs": {"production": {"env_vars": {name: None}}}}
        status, js = call("PATCH", base, h, body)
        if status == 200 and isinstance(js, dict):
            return status, {"deleted": name, "env_vars": cf_vars_summary(js)}
        return status, js
    if action == "cf-redeploy":
        boundary = "----vivek5ops"
        raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"branch\"\r\n\r\nmain\r\n"
               f"--{boundary}--\r\n").encode()
        hdrs = dict(h)
        hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        status, js = call("POST", f"{base}/deployments", hdrs, raw_body=raw)
        if status in (200, 201) and isinstance(js, dict):
            r = js.get("result") or {}
            return status, {"deployment_id": r.get("id"), "url": r.get("url"),
                            "stage": (r.get("latest_stage") or {}).get("name")}
        return status, js
    raise OpsError(f"unknown cloudflare action {action}")


# --------------------------------------------------------------------------
# the VPS's /api/dispatch (deploy/DESIGN.md D4 / 3.5 / 5)
# --------------------------------------------------------------------------

def _vps_target(env):
    """(url, token), both through config.clean_secret; https only.

    Refusing a non-https URL is the whole of the transport's security: the
    bearer token travels in a header, and over plain http it would cross the
    Internet in clear. A loopback http URL is meaningless from a GitHub
    runner, so there is no loopback exemption here (D4's is for the adapter
    talking to itself)."""
    url = _config.clean_secret(env.get("VPS_DISPATCH_URL"))
    token = _config.clean_secret(env.get("VPS_DISPATCH_TOKEN"))
    if not url:
        raise OpsError("VPS_DISPATCH_URL is not set (GitHub Actions secret)")
    if not token:
        raise OpsError("VPS_DISPATCH_TOKEN is not set (GitHub Actions secret)")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise OpsError(f"VPS_DISPATCH_URL must be an https:// URL (got scheme "
                       f"{parts.scheme or 'none'!r}); the bearer token is refused over anything else")
    return url, token


def do_vps(action, args, env):
    if action != "vps-dispatch":
        raise OpsError(f"unknown vps action {action}")
    workflow = args.get("workflow")
    if not isinstance(workflow, str) or not workflow.strip():
        raise OpsError('vps-dispatch needs a "workflow" (e.g. "scan.yml")')
    inputs = args.get("inputs", {})
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise OpsError('vps-dispatch "inputs" must be a JSON object')
    url, token = _vps_target(env)
    # Exactly the body _dispatch.js sends (DESIGN 5): the adapter is the
    # validator -- an unknown workflow or key comes back as a 400 that main()
    # prints, redacted, which beats a second copy of its table here.
    body = {"workflow": workflow.strip(), "inputs": inputs}
    return call("POST", url, {"Authorization": f"Bearer {token}"}, body, follow_redirects=False)


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

def run(action, args, env=None):
    env = os.environ if env is None else env
    if action not in ACTIONS:
        raise OpsError(f"unknown action {action!r}; one of {', '.join(ACTIONS)}")
    if action.startswith("cronjob-"):
        return do_cronjob(action, args, env)
    if action.startswith("vps-"):
        return do_vps(action, args, env)
    return do_cloudflare(action, args, env)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: ops.py <action> [json-args]")
        return 2
    action = argv[0]
    try:
        args = json.loads(argv[1]) if len(argv) > 1 and argv[1].strip() else {}
    except ValueError as e:
        print(f"ops: args is not valid JSON: {e}")
        return 2
    if not isinstance(args, dict):
        print("ops: args must be a JSON object")
        return 2
    # Values the caller passed in (a var value, a job URL with a key) are
    # secrets too, whatever the env says.
    extra = [str(v) for v in args.values() if isinstance(v, str)]
    try:
        status, result = run(action, args)
    except OpsError as e:
        print(f"ops: {redact(e, extra=extra)}")
        return 2
    except urllib.error.URLError as e:
        print(f"ops: network error: {redact(e, extra=extra)}")
        return 3
    text = json.dumps(result, indent=2, sort_keys=True) if not isinstance(result, str) else result
    print(f"ops: {action} -> HTTP {status}")
    print(redact(text, extra=extra))
    return 0 if 200 <= int(status) < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
