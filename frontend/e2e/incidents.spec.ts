import { test, expect } from "@playwright/test";

const BASE = process.env.UI_BASE ?? "http://localhost:3000";

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
    "Extracting timeline candidates",
    "Generating RCA hypotheses",
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

  // The included evidence is now locked: it shows the lock badge and the
  // delete control is disabled.
  await page.getByRole("button", { name: /api-errors\.log/ }).click();
  await expect(page.getByText("Locked · in analysis")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete" })).toBeDisabled();

  await page.getByRole("link", { name: "Back to all incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  await expect(page.getByText(title)).toBeVisible();
});

test("home page links into the incident list", async ({ page }) => {
  await page.goto(BASE);
  await page.getByRole("link", { name: "View incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
});
