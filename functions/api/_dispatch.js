/* The GitHub workflow_dispatch transport, shared by every endpoint that kicks a
 * workflow: scan.js, close.js, heartbeat.js, morning_plays.js.
 *
 * WHY IT IS SHARED (2026-09-17). Those four carried a byte-identical copy of the
 * dispatch URL, the five request headers, the 10-second abort -- and, the part
 * that actually matters, the COOLDOWN REFUND RULE. That rule is the subtle one:
 * a DEFINITE failure (GitHub answered non-204, or the network failed outright)
 * dispatched nothing, so the caller's KV cooldown is refunded and the retry is
 * free; a TIMEOUT may still have landed server-side, so the cooldown is
 * deliberately KEPT, because a duplicate run costs more than a five-minute wait.
 * Four hand-written copies of a rule with that shape is three chances to get the
 * fifth endpoint subtly wrong, in a direction nobody notices until a workflow
 * fires twice.
 *
 * WHAT IS DELIBERATELY NOT HERE: the response bodies and the friendly error
 * wording. Each endpoint answers a different caller -- a browser button, a cron
 * pinger, a human closing a position -- with its own status codes, its own field
 * names and its own strings, and each of those is asserted by that endpoint's
 * own tests. Unifying them would be a user-visible change dressed as a cleanup.
 *
 * THE SECOND TRANSPORT (2026-09-27, deploy/DESIGN.md D4 / section 5). When the
 * caller passes `dispatchUrl` (from env.DISPATCH_URL) the same call POSTs
 * `{workflow, inputs}` to the VPS adapter's /api/dispatch with
 * `Authorization: Bearer <DISPATCH_TOKEN>` instead of to GitHub. Same timer,
 * same four return shapes, same refund rule; the adapter answers 202 for
 * "queued" (GitHub answers 204). The URL must be https: or loopback -- a plain
 * http URL to a remote host would carry the bearer token in clear, so it is
 * refused up front as a DEFINITE failure ({ ok:false, status:0 }, refunded),
 * and neither transport ever returns the upstream body. With `dispatchUrl`
 * absent this file behaves exactly as before, byte for byte on the wire.
 *
 * Workers runtime: no Node builtins, no require. `fetch`, `AbortController`,
 * `setTimeout` and `URL` are ambient. Keep the export surface to
 * `export const` / `export async function` only -- the test suites prepend this
 * file into a vm sandbox with exactly those two forms stripped.
 */

export const DISPATCH_TIMEOUT_MS = 10_000;

/* Dispatch `workflow` with `inputs`. Never throws, and never returns the
 * upstream body (it can carry token/repo details). Exactly one of:
 *   { ok: true }                     -- accepted (GitHub 204 / adapter 202)
 *   { ok: false, status }            -- refused; cooldown refunded
 *   { ok: false, aborted: true }     -- timed out; cooldown deliberately KEPT
 *   { ok: false, aborted: false }    -- network error; cooldown refunded
 * `refund` is optional and awaited only on the refunding paths.
 * `dispatchUrl` / `dispatchToken` select the VPS transport (D4); when
 * `dispatchUrl` is falsy the GitHub path runs unchanged. */
export async function dispatchWorkflow({ token, repo, workflow, ref, inputs, refund,
                                         dispatchUrl, dispatchToken,
                                         timeoutMs = DISPATCH_TIMEOUT_MS }) {
  let url, init, okStatus;
  if (dispatchUrl) {
    // D4: the VPS adapter. Refuse anything that would put the bearer token on
    // the wire in clear -- https anywhere, or plain http only to loopback
    // (Phase 2, where the adapter posts to itself on 127.0.0.1).
    let target = null;
    try {
      const u = new URL(String(dispatchUrl));
      const host = u.hostname.replace(/^\[|\]$/g, "");
      const loopback = host === "127.0.0.1" || host === "localhost" || host === "::1"
        || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host);
      if (u.protocol === "https:" || (u.protocol === "http:" && loopback)) target = u.href;
    } catch (_) { /* unparseable -> refused below */ }
    if (!target) {
      if (refund) await refund();   // nothing was sent -- a definite failure
      return { ok: false, status: 0 };
    }
    url = target;
    okStatus = 202;
    init = {
      method: "POST",
      headers: {
        Authorization: `Bearer ${dispatchToken || ""}`,
        Accept: "application/json",
        "User-Agent": "googy-boys-scanner",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ workflow, inputs }),
    };
  } else {
    url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
    okStatus = 204;
    init = {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "googy-boys-scanner",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref, inputs }),
    };
  }

  // Abort if the far end is slow so the caller never hangs on this request.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal });

    if (res.status === okStatus) return { ok: true };

    if (refund) await refund();   // nothing was dispatched — free the retry
    return { ok: false, status: res.status };
  } catch (err) {
    const aborted = err?.name === "AbortError";
    // On timeout the dispatch MAY still have landed, so do NOT refund.
    if (!aborted && refund) await refund();
    return { ok: false, aborted };
  } finally {
    clearTimeout(timer);
  }
}
