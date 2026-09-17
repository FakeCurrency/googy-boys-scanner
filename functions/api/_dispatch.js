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
 * Workers runtime: no Node builtins, no require. `fetch`, `AbortController` and
 * `setTimeout` are ambient.
 */

export const DISPATCH_TIMEOUT_MS = 10_000;

/* Dispatch `workflow` with `inputs`. Never throws, and never returns the
 * upstream body (it can carry token/repo details). Exactly one of:
 *   { ok: true }                     -- GitHub accepted it (204)
 *   { ok: false, status }            -- GitHub refused; cooldown refunded
 *   { ok: false, aborted: true }     -- timed out; cooldown deliberately KEPT
 *   { ok: false, aborted: false }    -- network error; cooldown refunded
 * `refund` is optional and awaited only on the refunding paths. */
export async function dispatchWorkflow({ token, repo, workflow, ref, inputs, refund,
                                         timeoutMs = DISPATCH_TIMEOUT_MS }) {
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

  // Abort if GitHub is slow so the caller never hangs on this request.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "googy-boys-scanner",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref, inputs }),
      signal: ctrl.signal,
    });

    if (res.status === 204) return { ok: true };

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
