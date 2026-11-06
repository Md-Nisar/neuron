import { createRequire } from "node:module";

import { expect, test, type Page } from "@playwright/test";

// Run with `playwright.knowledge.config.ts`: needs Postgres, `setup` and `neuron-worker`.

const AXE = createRequire(import.meta.url).resolve("axe-core/axe.min.js");

async function signIn(page: Page, user: string): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.locator("#username").fill(user);
  await page.locator("#login").click();
  await expect(page.getByText(`Signed in as ${user}`)).toBeVisible();
}

/** axe on the page's main area, in a real browser, so colour contrast is checked too. */
async function violations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async () => {
    const axe = (window as unknown as { axe: typeof import("axe-core") }).axe;
    const main = document.querySelector("main");
    if (main === null) return ["no main element"];
    const result = await axe.run(main, { resultTypes: ["violations"] });
    return result.violations.map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    );
  });
}

test(
  "a user creates a knowledge base, uploads a file and sees it become ready",
  { tag: ["@knowledge"] },
  async ({ page }) => {
    const user = `kb${Date.now().toString(36)}`;
    await signIn(page, user);
    await page.getByRole("button", { name: "Knowledge" }).click();

    await page.getByLabel("New knowledge base").fill("Handbook");
    await page.getByRole("button", { name: "Create" }).click();
    const panel = page.getByRole("region", { name: "Documents in Handbook" });
    await expect(panel.getByText(/sent to the configured embedding provider/)).toBeVisible();

    await panel.getByLabel(/Drop files here/).setInputFiles({
      name: "leave-policy.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Leave policy\n\nEveryone gets 25 days of paid leave a year.\n"),
    });
    const row = panel.getByRole("listitem").filter({ hasText: "leave-policy.txt" });
    await expect(row).toBeVisible();
    // The worker parses and embeds it; the page polls, so no reload is needed.
    await expect(row.getByText("Ready")).toBeVisible({ timeout: 60_000 });

    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${scheme}\\b`));
      expect(await violations(page), `${scheme} theme`).toEqual([]);
    }
  },
);
