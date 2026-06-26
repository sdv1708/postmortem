import { test, expect } from "@playwright/test";
import type { Readable } from "node:stream";

const BASE = process.env.UI_BASE ?? "http://localhost:3000";

async function streamToString(stream: Readable | null): Promise<string> {
  if (!stream) return "";
  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf-8");
}

test("create incident and view it in the workflow hub", async ({ page }) => {
  await page.goto(`${BASE}/incidents`);
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();

  await page.getByRole("link", { name: "New incident" }).click();
  await expect(page).toHaveURL(/\/incidents\/new$/);

  const title = `Deploy spike ${Date.now()}`;
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Severity").selectOption("sev2");
  await page.getByLabel("Summary").fill("API 500s climbing after the 14:28 deploy.");
  await page.getByRole("button", { name: "Create incident" }).click();

  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("sev2")).toBeVisible();
  await expect(page.getByText("API 500s climbing after the 14:28 deploy.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();

  await page.getByLabel("Source type").selectOption("logs");
  await page.getByLabel("Source name").fill("api-errors.log");
  await page.getByLabel("Artifact text").fill("14:28 deploy started\n14:32 api 500s spike");
  await page.getByRole("button", { name: "Add evidence" }).click();
  await expect(page.getByRole("button", { name: /api-errors\.log/ })).toBeVisible();
  await expect(page.getByRole("rowheader", { name: "1" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "14:28 deploy started" })).toBeVisible();
  await expect(page.getByRole("rowheader", { name: "2" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "14:32 api 500s spike" })).toBeVisible();

  await page.getByLabel("Upload text file").setInputFiles({
    name: "deploy-notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("deploy v184 released\nrollback prepared"),
  });
  await expect(page.getByLabel("Source name")).toHaveValue("deploy-notes.txt");
  await expect(page.getByLabel("Artifact text")).toHaveValue("deploy v184 released\nrollback prepared");

  await expect(page.getByRole("heading", { name: "Analysis runs", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Postmortem" })).toBeVisible();

  // Start an async analysis run and watch the six-stage status page. The UI
  // polls run status (no streaming) until the run reaches a terminal state.
  await expect(page.getByRole("heading", { name: "No analysis runs yet" })).toBeVisible();
  await page.getByRole("button", { name: "Start analysis run" }).click();
  await expect(page.getByRole("heading", { name: "No analysis runs yet" })).toBeHidden();

  // All six MVP stages render in order.
  for (const stage of [
    "Normalizing evidence",
    "Extracting incident facts",
    "Analyzing causal hypotheses",
    "Verifying citations",
    "Drafting postmortem",
    "Flagging unsupported claims",
  ]) {
    await expect(page.getByText(stage, { exact: true })).toBeVisible();
  }

  // The run reaches succeeded via polling.
  await expect(page.getByText("succeeded", { exact: true })).toBeVisible();

  // Timeline candidates appear after the run, citing exact artifact lines and
  // labeling the time-only timestamps as inferred (ADR 0019).
  await expect(page.getByText(/Timeline candidates/)).toBeVisible();
  await expect(page.getByText("api-errors.log:2")).toBeVisible();
  await expect(page.getByText("inferred").first()).toBeVisible();
  // The verifying_citations stage stamped each citation, so its integrity badge
  // shows verified next to the citation (ADR 0014).
  await expect(page.getByRole("img", { name: /Citation verified/ }).first()).toBeVisible();
  const citedSnippet = "14:32 api 500s spike";
  const citation = page.getByRole("button", { name: /api-errors\.log:2/ });
  await expect(citation).toContainText(citedSnippet);
  await citation.click();
  await expect(page.getByRole("rowheader", { name: "2" })).toHaveClass(/bg-amber-100/);
  await expect(page.getByRole("cell", { name: citedSnippet })).toHaveClass(/bg-amber-50/);

  // The drafting stage composed a structured postmortem; its summary and the
  // clean/audit Markdown export controls render under the succeeded run.
  await expect(page.getByRole("button", { name: "Export clean" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export audit" })).toBeVisible();

  // The included evidence is now locked: it shows the lock badge and the
  // delete control is disabled.
  await page.getByRole("button", { name: "api-errors.log Logs 2 lines" }).click();
  await expect(page.getByText("Locked · in analysis")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete" })).toBeDisabled();

  await page.getByRole("link", { name: "Back to all incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  await expect(page.getByText(title)).toBeVisible();
});

test("seed the canonical demo scenario and review its multi-hypothesis postmortem", async ({
  page,
}) => {
  await page.goto(`${BASE}/incidents`);

  // The demo-seed affordance lists the file-based scenario fixtures (ADR 0007).
  await expect(
    page.getByRole("heading", { name: "Seed a synthetic incident" }),
  ).toBeVisible();
  // Several scenario families are listed; seed the canonical deploy one.
  const deployCard = page
    .getByRole("listitem")
    .filter({ hasText: "Ambiguous deploy-related API error spike" });
  await deployCard.getByRole("button", { name: "Seed demo scenario" }).click();

  // Seeding creates the incident, runs the pipeline on the bundled replay, and
  // lands on the populated Review Surface.
  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(
    page.getByRole("heading", { name: "Ambiguous deploy-related API error spike" }),
  ).toBeVisible();
  await expect(page.getByText("succeeded", { exact: true })).toBeVisible();

  // Multiple ranked hypotheses with verified citations and contradicting
  // evidence — the founder-demo trust path (ADR 0032). Two builder hypotheses
  // plus the falsifier's proposed alternative are evidence-backed (ADR 0036).
  await expect(page.getByText(/RCA hypotheses · 3/)).toBeVisible();
  await expect(
    page.getByText("Deploy v184 connection-pool refactor regressed connection handling"),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: /Citation verified/ }).first()).toBeVisible();

  // The bounded expansion round surfaced a missed alternative, labeled distinctly
  // and travelling the full citation/challenge/review path (ADR 0036, #30). It is
  // shown as a proposed alternative, never as a root cause.
  await expect(
    page.getByText("Cache-node eviction shifted read load onto the primary database"),
  ).toBeVisible();
  await expect(page.getByText("proposed alternative").first()).toBeVisible();

  // The unevidenced suspicion is separated into auditable Review Findings rather
  // than presented as fact (ADR 0015).
  await expect(page.getByText(/Review findings · unsupported · 1/)).toBeVisible();

  // The bounded falsifier challenged every hypothesis (ADR 0034 / #28): the
  // Review Surface shows the challenge, its severity, a cited counterclaim that
  // navigates to exact evidence, and the procedural gaps/tests — visible without
  // opening any debug log (PRD user stories 88-89).
  await expect(page.getByText("Falsification challenge").first()).toBeVisible();
  await expect(page.getByText("material challenge").first()).toBeVisible();
  await expect(page.getByText("critical challenge").first()).toBeVisible();
  await expect(
    page.getByText(/max_connections unchanged at 40/),
  ).toBeVisible();
  await expect(page.getByText("Evidence gaps").first()).toBeVisible();
  await expect(page.getByText("Falsification tests").first()).toBeVisible();
  // A counterclaim citation resolves to its exact immutable artifact line.
  await expect(
    page.getByRole("button", { name: /deploy-notes\.md:4/ }).first(),
  ).toBeVisible();

  // The post-challenge Advisory Hypothesis Ranking shows its work: each
  // hypothesis carries a "Why this rank" rationale and an advisory-rank badge, so
  // a reviewer can see why one candidate ranks above another (ADR 0037, PRD #26
  // user stories 17-19, 88). Ranking is a review aid, never a Root Cause Conclusion.
  await expect(page.getByText("Why this rank").first()).toBeVisible();
  await expect(page.getByText("advisory rank 1").first()).toBeVisible();

  // The structured postmortem and its clean/audit exports rendered.
  await expect(page.getByRole("button", { name: "Export clean" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export audit" })).toBeVisible();

  // Restricted run diagnostics expose the reasoning/retrieval provenance (ADR
  // 0038, PRD #26 user stories 69-73, 88-89): collapsed by default so the normal
  // review workflow is unchanged, it shows one record per reasoning-role call and
  // the evidence each role retrieved — versions and counts, never prompts or
  // artifact text.
  await page.getByRole("button", { name: /Run diagnostics/ }).click();
  await expect(page.getByText(/Model calls ·/)).toBeVisible();
  await expect(page.getByText(/Retrieval traces ·/)).toBeVisible();
  await expect(page.getByText("Builder").first()).toBeVisible();
  await expect(page.getByText("Falsifier").first()).toBeVisible();
  await expect(page.getByText(/cited/).first()).toBeVisible();
  // Each model call exposes its sanitized structured outcome (references and
  // counts only — never artifact text) so a reviewer can inspect what each role
  // produced (issue #32).
  await expect(page.getByText("Structured outcome").first()).toBeVisible();

  // The automated draft is labeled provisional: no human Root Cause Conclusion
  // has been finalized, so it cannot be mistaken for one (ADR 0035, #29).
  await expect(
    page.getByRole("heading", { name: "Draft: Root cause not finalized" }),
  ).toBeVisible();
  await expect(
    page.getByText(/This is an automated provisional postmortem/),
  ).toBeVisible();

  // Provisional labeling survives into the exported Markdown (AC #2/#5).
  const download = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export clean" }).click(),
  ]).then(([d]) => d);
  const stream = await download.createReadStream();
  const exported = await streamToString(stream);
  expect(exported).toContain("Draft: Root cause not finalized");
  expect(exported).toContain("**Status:** provisional");

  // Human-in-the-loop finalization (ADR 0039, #33): accepting a hypothesis is a
  // separate decision from concluding a root cause. The reviewer accepts the
  // leading evidence-backed hypothesis, assigns it as the failure mechanism, and
  // finalizes a Root Cause Conclusion — rendered distinctly from the advisory
  // ranking, with the provisional draft label gone.
  await page.getByRole("button", { name: "Accept" }).first().click();
  const roleSelect = page.getByLabel(/Causal role for Deploy v184/);
  await expect(roleSelect).toBeVisible();
  await roleSelect.selectOption("failure_mechanism");
  await page
    .getByPlaceholder(/Summarize the causal account/)
    .fill("The v184 connection-pool refactor regressed connection handling.");
  // Human Assumptions (ADR 0042, #36): an unevidenced reviewer belief recorded
  // separately from the evidence-backed factors so it never reads as established
  // fact (PRD #26 story 38).
  await page
    .getByLabel("Human assumptions")
    .fill("The on-call likely restarted the service manually before the rollback.");
  await page.getByRole("button", { name: "Finalize root cause conclusion" }).click();

  await expect(page.getByText("finalized by human")).toBeVisible();
  await expect(
    page.getByText("The v184 connection-pool refactor regressed connection handling."),
  ).toBeVisible();
  // The human assumption renders in its own labeled section, never as a causal factor.
  await expect(page.getByText("not evidence-backed")).toBeVisible();
  await expect(
    page.getByText("The on-call likely restarted the service manually before the rollback."),
  ).toBeVisible();
  // The failure mechanism is shown as the human conclusion, separate from the
  // advisory ranking above.
  await expect(page.getByText("Failure mechanism").first()).toBeVisible();
  // The provisional draft banner drops once a human conclusion exists.
  await expect(
    page.getByRole("heading", { name: "Draft: Root cause not finalized" }),
  ).toBeHidden();

  // Finalization is immutable: the export now reflects the finalized conclusion.
  const finalizedDownload = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export clean" }).click(),
  ]).then(([d]) => d);
  const finalizedMarkdown = await streamToString(await finalizedDownload.createReadStream());
  expect(finalizedMarkdown).toContain("## Root Cause Conclusion");
  expect(finalizedMarkdown).toContain("**Status:** finalized");
  expect(finalizedMarkdown).not.toContain("Draft: Root cause not finalized");
  // The labeled human assumption is preserved in the export (ADR 0042, #36).
  expect(finalizedMarkdown).toContain("Human assumptions (not evidence-backed):");
  expect(finalizedMarkdown).toContain(
    "The on-call likely restarted the service manually before the rollback.",
  );

  // Remediation review (ADR 0041, #35): generated remediation is a proposal, not
  // committed work. The reviewer accepts one — linking it to the finalized causal
  // factor — and the four states are distinguished in the panel and in exports.
  await expect(page.getByText(/Remediation review ·/)).toBeVisible();
  const remediationLink = page.getByLabel(/Accept link target/).first();
  await expect(remediationLink).toBeVisible();
  // Option index 1 is the first real link target; the finalized causal factor
  // sorts ahead of evidence gaps in the option list.
  await remediationLink.selectOption({ index: 1 });
  await page.getByRole("button", { name: "Accept proposal" }).first().click();
  // The decision is recorded with provenance and never edits the generated text.
  await expect(page.getByText(/Decided by human/).first()).toBeVisible();

  // A clean export now lists the accepted remediation as committed follow-up; an
  // audit export groups every proposal by state (AC #4).
  const remediationClean = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export clean" }).click(),
  ]).then(([d]) => d);
  const remediationCleanMarkdown = await streamToString(await remediationClean.createReadStream());
  expect(remediationCleanMarkdown).toContain("## Remediation");

  const remediationAudit = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export audit" }).click(),
  ]).then(([d]) => d);
  const remediationAuditMarkdown = await streamToString(
    await remediationAudit.createReadStream(),
  );
  expect(remediationAuditMarkdown).toContain("**Accepted:**");

  // Flagging an immutable conclusion as disputed (ADR 0040, #34): a reviewer records
  // an append-only Conclusion Discrepancy without editing the conclusion. The
  // conclusion is preserved but returns to unresolved, no longer authoritative.
  await page
    .getByPlaceholder(/Explain what is wrong with this conclusion/)
    .fill("The cited deploy postdates the error spike by several minutes.");
  await page.getByRole("button", { name: "Flag discrepancy" }).click();

  await expect(
    page.getByRole("heading", { name: "Disputed — returned to unresolved review" }),
  ).toBeVisible();
  await expect(
    page.getByText("The cited deploy postdates the error spike by several minutes."),
  ).toBeVisible();
  // The immutable conclusion's causal account is still preserved for audit.
  await expect(
    page.getByText("The v184 connection-pool refactor regressed connection handling."),
  ).toBeVisible();

  // A clean export withholds the disputed conclusion as current fact; an audit
  // export preserves the conclusion and the discrepancy (AC #4).
  const disputedClean = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export clean" }).click(),
  ]).then(([d]) => d);
  const disputedCleanMarkdown = await streamToString(await disputedClean.createReadStream());
  expect(disputedCleanMarkdown).toContain("**Status:** disputed");
  expect(disputedCleanMarkdown).toContain("Disputed conclusion.");
  expect(disputedCleanMarkdown).toContain("withheld from this clean export");
  expect(disputedCleanMarkdown).not.toContain(
    "The v184 connection-pool refactor regressed connection handling.",
  );

  const disputedAudit = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export audit" }).click(),
  ]).then(([d]) => d);
  const disputedAuditMarkdown = await streamToString(await disputedAudit.createReadStream());
  expect(disputedAuditMarkdown).toContain("**Recorded discrepancies:**");
  expect(disputedAuditMarkdown).toContain(
    "The cited deploy postdates the error spike by several minutes.",
  );
  expect(disputedAuditMarkdown).toContain(
    "The v184 connection-pool refactor regressed connection handling.",
  );
});

// Superseding a disputed conclusion (ADR 0045, #39): a disputed Root Cause
// Conclusion is resolved not by editing it but by finalizing a new immutable
// Superseding Conclusion. This drives the same-run reinterpretation path end to
// end — finalize, dispute, supersede — and checks that authority moves to the
// successor while the disputed predecessor is preserved in the superseding chain.
test("supersede a disputed conclusion with a reinterpretation", async ({ page }) => {
  await page.goto(`${BASE}/incidents`);
  const deployCard = page
    .getByRole("listitem")
    .filter({ hasText: "Ambiguous deploy-related API error spike" });
  await deployCard.getByRole("button", { name: "Seed demo scenario" }).click();

  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByText("succeeded", { exact: true })).toBeVisible();

  // Finalize an original Root Cause Conclusion from the leading evidence-backed
  // hypothesis (accepting is a separate decision from concluding).
  await page.getByRole("button", { name: "Accept" }).first().click();
  await page.getByLabel(/Causal role for Deploy v184/).selectOption("failure_mechanism");
  await page
    .getByPlaceholder(/Summarize the causal account/)
    .fill("The v184 connection-pool refactor regressed connection handling.");
  await page.getByRole("button", { name: "Finalize root cause conclusion" }).click();
  await expect(page.getByText("finalized by human")).toBeVisible();

  // Dispute it (append-only Conclusion Discrepancy, ADR 0040): it returns to
  // unresolved review and is no longer authoritative.
  await page
    .getByPlaceholder(/Explain what is wrong with this conclusion/)
    .fill("The cited deploy postdates the error spike by several minutes.");
  await page.getByRole("button", { name: "Flag discrepancy" }).click();
  await expect(
    page.getByRole("heading", { name: "Disputed — returned to unresolved review" }),
  ).toBeVisible();

  // Resolve the dispute by superseding it (reinterpretation, same run): authority
  // moves to the new conclusion and the disputed predecessor enters the chain.
  await expect(page.getByText("Supersede this conclusion")).toBeVisible();
  await page.getByLabel(/Causal role for Deploy v184/).selectOption("failure_mechanism");
  await page
    .getByPlaceholder(/Summarize the causal account/)
    .fill("On review, the deploy is the trigger; pool exhaustion is the mechanism.");
  await page.getByRole("button", { name: "Finalize superseding conclusion" }).click();

  await expect(page.getByText("superseding conclusion")).toBeVisible();
  await expect(
    page.getByText("On review, the deploy is the trigger; pool exhaustion is the mechanism."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Disputed — returned to unresolved review" }),
  ).toBeHidden();
  await expect(page.getByText(/Superseding chain ·/)).toBeVisible();

  // A clean export presents the authoritative successor and notes the provenance.
  const supersededClean = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export clean" }).click(),
  ]).then(([d]) => d);
  const supersededCleanMarkdown = await streamToString(await supersededClean.createReadStream());
  expect(supersededCleanMarkdown).toContain("**Status:** finalized");
  expect(supersededCleanMarkdown).toContain(
    "On review, the deploy is the trigger; pool exhaustion is the mechanism.",
  );
  expect(supersededCleanMarkdown).toContain("Supersedes an earlier disputed conclusion");
});

// New-evidence supersession across runs (ADR 0045, #39): when new evidence is
// needed, the reviewer starts a new analysis run and supersedes the disputed
// predecessor from there. The new run's conclusion form offers the disputed
// predecessor as a supersede target (it is not reachable any other way in the UI).
test("supersede a disputed conclusion from a new analysis run", async ({ page }) => {
  await page.goto(`${BASE}/incidents`);
  const deployCard = page
    .getByRole("listitem")
    .filter({ hasText: "Ambiguous deploy-related API error spike" });
  await deployCard.getByRole("button", { name: "Seed demo scenario" }).click();
  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByText("succeeded", { exact: true })).toBeVisible();

  // Finalize then dispute an original conclusion on the first run.
  await page.getByRole("button", { name: "Accept" }).first().click();
  await page.getByLabel(/Causal role for Deploy v184/).selectOption("failure_mechanism");
  await page
    .getByPlaceholder(/Summarize the causal account/)
    .fill("The v184 connection-pool refactor regressed connection handling.");
  await page.getByRole("button", { name: "Finalize root cause conclusion" }).click();
  await expect(page.getByText("finalized by human")).toBeVisible();
  await page
    .getByPlaceholder(/Explain what is wrong with this conclusion/)
    .fill("Need new evidence: the deploy timing does not line up.");
  await page.getByRole("button", { name: "Flag discrepancy" }).click();
  await expect(
    page.getByRole("heading", { name: "Disputed — returned to unresolved review" }),
  ).toBeVisible();

  // Start a second analysis run (the new-evidence path) and wait for both runs to
  // finish (the new run polls through the six stages; offline runs can take a while).
  await page.getByRole("button", { name: "Start analysis run" }).click();
  await expect(page.getByText("succeeded", { exact: true })).toHaveCount(2, {
    timeout: 90_000,
  });

  // Reachability is the crux of the finding: the new run's conclusion form exposes a
  // supersede target selector that offers the disputed predecessor, so the new-evidence
  // path is driveable from the UI (not API-only). The full cross-run supersede
  // submission and its export behavior are covered by the backend API tests.
  const targetSelect = page.getByLabel("Conclusion target");
  await expect(targetSelect).toBeVisible();
  await expect(
    targetSelect.getByRole("option", { name: /Supersede disputed conclusion/ }),
  ).toHaveCount(1);

  // Choosing it switches the form into superseding mode (resolves the dispute by
  // appending a successor rather than finalizing another original conclusion).
  await targetSelect.selectOption({ index: 1 });
  const newRunCard = page
    .locator("li")
    .filter({ has: page.getByLabel("Conclusion target") })
    .first();
  await expect(
    newRunCard.getByRole("button", { name: "Finalize superseding conclusion" }),
  ).toBeVisible();
});

test("run the evaluation suite and review the deterministic dashboard", async ({ page }) => {
  await page.goto(`${BASE}/evaluations`);
  await expect(page.getByRole("heading", { name: "Evaluations" })).toBeVisible();

  await page.getByRole("button", { name: "Run all evaluations" }).click();

  // Each scenario family is scored (ADR 0006): deploy, dependency, config drift.
  await expect(
    page.getByRole("heading", { name: "Ambiguous deploy-related API error spike" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Checkout failures from a degraded payments provider" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Latency spike from a drifted cache configuration" }),
  ).toBeVisible();

  // The deterministic floor passes and citation validity is reported mechanically.
  await expect(page.getByText("passing").first()).toBeVisible();
  await expect(page.getByText(/\d+\/\d+ verified/).first()).toBeVisible();
  await expect(page.getByText("✓ citation_integrity").first()).toBeVisible();
  // No model configured in e2e, so the judge is honestly not scored — but the
  // deterministic floor still stands (ADR 0010).
  await expect(page.getByText("not scored (no model)").first()).toBeVisible();
});

test("seed the insufficient-evidence scenario and see a refusal, not a confident postmortem", async ({
  page,
}) => {
  await page.goto(`${BASE}/incidents`);
  await expect(
    page.getByRole("heading", { name: "Seed a synthetic incident" }),
  ).toBeVisible();

  const refusalCard = page
    .getByRole("listitem")
    .filter({ hasText: "Insufficient evidence for confident postmortem" });
  await refusalCard.getByRole("button", { name: "Seed demo scenario" }).click();

  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByText("succeeded", { exact: true })).toBeVisible();

  // The system refuses rather than asserting a confident root cause (ADR 0032).
  await expect(
    page.getByText("Insufficient evidence — no confident root cause asserted"),
  ).toBeVisible();
  // Refusal and provisional labeling coexist: a refused run is still a draft
  // pending a human conclusion (ADR 0035, #29 AC #4).
  await expect(
    page.getByRole("heading", { name: "Draft: Root cause not finalized" }),
  ).toBeVisible();
  // It stays useful: it says what to collect next (AC #5).
  await expect(page.getByText("Suggested next evidence")).toBeVisible();
  await expect(
    page.getByText(/Collect timestamped logs spanning the incident window/),
  ).toBeVisible();
  // No confident hypotheses are presented.
  await expect(page.getByText(/RCA hypotheses ·/)).toBeHidden();
  // The source evidence remains available for review.
  await expect(page.getByRole("button", { name: /sparse-notes\.md/ })).toBeVisible();
});

test("home page links into the incident list", async ({ page }) => {
  await page.goto(BASE);
  await page.getByRole("link", { name: "View incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
});
