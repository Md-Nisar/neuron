import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

async function signInKeycloak(page: Page, user: string, pass: string): Promise<void> {
  await page.goto("http://localhost:5173/");
  const signInBtn = page.getByRole("button", { name: /sign in/i });
  await expect(signInBtn).toBeVisible({ timeout: 15_000 });
  await signInBtn.click();

  await page.waitForURL(/.*:8180.*/, { timeout: 15_000 });
  await expect(page.locator("#username")).toBeVisible();
  await page.locator("#username").fill(user);
  await page.locator("#password").fill(pass);
  await page.locator("#kc-login").click();

  await page.waitForURL(/.*:5173.*/, { timeout: 15_000 });
  await expect(page.getByText(new RegExp(`Signed in as ${user}`, "i"))).toBeVisible({
    timeout: 15_000,
  });
}

async function signOut(page: Page): Promise<void> {
  const signOutBtn = page.getByRole("button", { name: "Sign out" });
  await expect(signOutBtn).toBeVisible();
  await signOutBtn.click();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible({ timeout: 15_000 });
}

test.describe("Live Stack Comprehensive Verification", () => {
  test("AUTH: Keycloak login, invalid credential rejection, and sign-out", async ({ page }) => {
    // 1. Invalid login attempt
    await page.goto("http://localhost:5173/");
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.waitForURL(/.*:8180.*/);
    await page.locator("#username").fill("alice");
    await page.locator("#password").fill("wrong-password");
    await page.locator("#kc-login").click();
    // Keycloak error message (targeting specific error element to avoid strict mode ambiguity)
    await expect(page.locator("#input-error-password")).toBeVisible();

    // 2. Valid login as Alice
    await page.locator("#password").fill("dev-only-alice");
    await page.locator("#kc-login").click();
    await page.waitForURL(/.*:5173.*/);
    await expect(page.getByText(/Signed in as alice/i)).toBeVisible();

    // 3. Sign out
    await signOut(page);

    // 4. Valid login as Bob (reader)
    await signInKeycloak(page, "bob", "dev-only-bob");
    await expect(page.getByText(/Signed in as bob/i)).toBeVisible();
    await signOut(page);
  });

  test("KB & DOC & RAG: Lifecycle from creation to upload, ingest, chat, citation, and deletion", async ({
    page,
  }) => {
    await signInKeycloak(page, "alice", "dev-only-alice");

    // Navigate to Knowledge
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Knowledge bases" })).toBeVisible();

    // Create KB
    const kbName = `HR-Guide-${Date.now().toString(36)}`;
    await page.getByLabel("New knowledge base").fill(kbName);
    await page.getByRole("button", { name: "Create" }).click();

    // Documents panel for newly created base
    const panel = page.getByRole("region", { name: `Documents in ${kbName}` });
    await expect(panel).toBeVisible({ timeout: 15_000 });

    // Upload document
    const docContent = `# Remote Work Policy\n\nEligible employees may work remotely up to 3 days per week with manager approval.\n`;
    await panel.getByLabel(/Drop files here/).setInputFiles({
      name: "remote-work.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(docContent),
    });

    const docRow = panel.getByRole("listitem").filter({ hasText: "remote-work.md" });
    await expect(docRow).toBeVisible();
    // Wait for ingestion worker to embed and mark ready
    await expect(docRow.getByText("Ready")).toBeVisible({ timeout: 60_000 });

    // Chat and Ask
    await page.getByRole("button", { name: "Chat", exact: true }).click();
    const composer = page.getByRole("textbox", { name: "Message" });
    await composer.fill("search: remote work days");
    await composer.press("Enter");

    // Verify response and citation chip
    const msgLog = page.getByRole("log", { name: "Messages" });
    const sources = msgLog.getByRole("list", { name: "Sources" });
    await expect(sources).toBeVisible({ timeout: 45_000 });

    const chip = sources.getByRole("button").first();
    await expect(chip).toBeVisible();

    // Open SourceSheet
    await chip.click();
    const sheet = page.getByRole("region", { name: /^[0-9]+\.\s+/ });
    await expect(sheet).toBeVisible();
    await expect(page.getByRole("button", { name: "Close source" })).toBeVisible();

    // Close SourceSheet
    await page.getByRole("button", { name: "Close source" }).click();

    // Clean up: delete KB
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("button", { name: `Delete ${kbName}` }).click();
    await page.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByRole("button", { name: kbName })).toHaveCount(0, { timeout: 15_000 });

    await signOut(page);
  });

  test("RBAC: Reader role enforcement for Bob", async ({ page }) => {
    // Bob has role neuron-reader with scope threads:read only
    await signInKeycloak(page, "bob", "dev-only-bob");

    // Attempt to access Knowledge
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();

    // Verify Bob is barred from managing knowledge
    await expect(
      page.getByText("You do not have permission to manage knowledge bases."),
    ).toBeVisible();

    await signOut(page);
  });

  test("DATA: GDPR data export and theme switching", async ({ page }) => {
    await signInKeycloak(page, "alice", "dev-only-alice");

    // Theme switching check
    const themeBtn = page.getByRole("button", { name: /^Theme:/ });
    await expect(themeBtn).toBeVisible();
    await themeBtn.click(); // cycles theme
    await expect(page.locator("html")).toHaveClass(/\b(light|dark)\b/);

    // GDPR Export
    await page.getByRole("button", { name: "Your data" }).click();
    await expect(page.getByRole("heading", { name: "Export your data" })).toBeVisible();

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download my data" }).click();
    const download = await downloadPromise;
    const path = await download.path();
    expect(path).toBeTruthy();
    if (path) {
      const data = JSON.parse(readFileSync(path, "utf-8")) as {
        threads?: unknown[];
        memories?: unknown[];
        knowledge_bases?: unknown[];
      };
      expect(Array.isArray(data.threads)).toBe(true);
      expect(Array.isArray(data.memories)).toBe(true);
      expect(Array.isArray(data.knowledge_bases)).toBe(true);
    }

    await signOut(page);
  });
});
