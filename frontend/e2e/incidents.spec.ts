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
  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Analysis runs" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Postmortem" })).toBeVisible();

  await page.getByRole("link", { name: "All incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  await expect(page.getByText(title)).toBeVisible();
});

test("home page links into the incident list", async ({ page }) => {
  await page.goto(BASE);
  await page.getByRole("link", { name: "View incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
});
