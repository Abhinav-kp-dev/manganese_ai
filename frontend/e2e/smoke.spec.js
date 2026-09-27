import { expect, test } from "@playwright/test";

async function signIn(page, role = "Administrator") {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(role) }).click();
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign in — choose your role")).toBeHidden();
}

function watchErrors(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/tile\.openstreetmap|Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`); });
  return errors;
}

const PAGES = [
  ["/", "kpis"],
  ["/reserves", "reserve-map"],
  ["/forecast", "fan-chart"],
  ["/actions", "action-plan"],
  ["/scenarios", "scenario-panel"],
  ["/integrity", "checklist"],
];

test("sign-in is required and works", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Sign in — choose your role")).toBeVisible();
  await signIn(page);
});

for (const [path, id] of PAGES) {
  test(`page ${path} renders without errors`, async ({ page }) => {
    const errors = watchErrors(page);
    await signIn(page);
    await page.goto(path);
    await expect(page.locator(`#${id}`)).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("reserves: real Sentinel-2 imagery, real-data check and tonnage", async ({ page }) => {
  const errors = watchErrors(page);
  await signIn(page);
  await page.goto("/reserves");
  await expect(page.locator("#real-data")).toBeVisible();
  await expect(page.locator("#real-data")).toContainText("not yet shown skill on real data");
  await page.getByLabel("Satellite image").selectOption("false_colour");
  const img = page.locator('img[src*="/api/imagery/s2_false_colour_swir.png"]');
  await expect(img).toHaveCount(1);
  await expect.poll(() => img.evaluate((el) => el.complete && el.naturalWidth)).toBeGreaterThan(100);
  await page.getByLabel("Map layer").selectOption("surface_prob_real");
  await expect(page.locator("#drill-targets")).toContainText("Ore, Mt");
  await expect(page.locator("#drill-targets")).toContainText("not a Mineral Resource");
  expect(errors).toEqual([]);
});

test("integrity: real vs synthetic table and all checks green", async ({ page }) => {
  await signIn(page);
  await page.goto("/integrity");
  await expect(page.locator("#real-vs-synthetic")).toContainText("Synthetic demo");
  await expect(page.locator("#checklist")).toContainText("all checks pass");
});

test("viewer role cannot see upload controls", async ({ page }) => {
  await signIn(page, "Viewer");
  await page.goto("/integrity");
  await expect(page.getByText("Uploading MOIL data needs")).toBeVisible();
});
