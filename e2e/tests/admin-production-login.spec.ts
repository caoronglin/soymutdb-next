import { expect, test } from "@playwright/test";

test.describe("admin production artifact — login", () => {
  test("has the expected title and no runtime page errors", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await page.goto("/login", { waitUntil: "load" });

    await expect(page).toHaveTitle("SoyMutDB 管理后台");
    expect(
      pageErrors.map((error) => error.message),
      "the emitted Admin artifact must not throw while loading /login",
    ).toEqual([]);
  });

  test("renders an interactive, non-empty login form", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await page.goto("/login", { waitUntil: "load" });

    await expect(page).toHaveTitle("SoyMutDB 管理后台");
    await expect(page.getByRole("heading", { name: "SoyMutDB 管理后台" })).toBeVisible();

    const username = page.getByLabel("用户名", { exact: true });
    const password = page.getByLabel("密码", { exact: true });
    await expect(username).toBeVisible();
    await expect(password).toBeVisible();
    await expect(page.getByRole("button", { name: "登录" })).toBeVisible();

    await username.fill("production-smoke-user");
    await password.fill("ProductionSmokePassword1!");
    await expect(username).toHaveValue("production-smoke-user");
    await expect(password).toHaveValue("ProductionSmokePassword1!");
    expect(pageErrors.map((error) => error.message)).toEqual([]);
  });
});
