import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { expect, test, type Page } from "@playwright/test";

// Run with `playwright.knowledge.config.ts`: needs Postgres, `setup` and `neuron-worker`.

const AXE = createRequire(import.meta.url).resolve("axe-core/axe.min.js");

async function signIn(page: Page, user: string, roles = ""): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.locator("#username").fill(user);
  await page.locator("#roles").fill(roles);
  await page.locator("#login").click();
  await expect(page.getByText(`Signed in as ${user}`)).toBeVisible();
}

/** axe on the page's main area, in a real browser, so colour contrast is checked too. */
async function violations(page: Page): Promise<string[]> {
  // Controls fade to new colours (`transition-all`) and the source sheet fades in
  // (`fade-in-0`): measure contrast after every fade, not halfway through one.
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every((a) => a.playState !== "running" || a.effect?.getTiming().iterations === Infinity),
  );
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
  "a user uploads a file, sees it become ready, asks about it and opens the citation",
  { tag: ["@knowledge"] },
  async ({ page }) => {
    const user = `kb${Date.now().toString(36)}`;
    await signIn(page, user);
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();

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

    // RAG-06.02: ask, then open the passage the answer cites. Without a provider key the API's
    // fake model answers `search: ...` by searching knowledge and citing what it found.
    await page.getByRole("button", { name: "Chat" }).click();
    const composer = page.getByRole("textbox", { name: "Message" });
    await composer.fill("search: paid leave");
    await composer.press("Enter");
    // The scripted answer; on any other outcome, say what the chat shows instead.
    const log = page.getByRole("log", { name: "Messages" });
    await expect(log.getByText("From your documents."))
      .toBeVisible({ timeout: 30_000 })
      .catch(async (error: unknown) => {
        throw new Error(`chat shows: ${await log.innerText()}`, { cause: error });
      });
    const sources = page.getByRole("list", { name: "Sources" });
    const chip = sources.getByRole("button").first();
    await expect(chip).toContainText("1");
    await expect(chip).toContainText("leave-policy.txt");
    await chip.click();
    const sheet = page.getByRole("region", { name: /^1\. leave-policy\.txt/ });
    await expect(sheet.getByText("Everyone gets 25 days of paid leave a year.")).toBeVisible();
    expect(await violations(page), "chat with an open source").toEqual([]);
  },
);

/** Make a base and put one text file in it, then wait for the worker to make it ready. */
async function addBase(page: Page, name: string, file: string, text: string): Promise<void> {
  await page.getByLabel("New knowledge base").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  const panel = page.getByRole("region", { name: `Documents in ${name}` });
  await panel
    .getByLabel(/Drop files here/)
    .setInputFiles({ name: file, mimeType: "text/plain", buffer: Buffer.from(text) });
  const row = panel.getByRole("listitem").filter({ hasText: file });
  await expect(row.getByText("Ready")).toBeVisible({ timeout: 60_000 });
}

/** Send a turn and wait until one more scripted answer shows. */
async function ask(page: Page, text: string): Promise<void> {
  const answers = page
    .getByRole("log", { name: "Messages" })
    .getByText(/^(From your documents\.|Your documents do not say\.)$/);
  const before = await answers.count();
  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill(text);
  await composer.press("Enter");
  await expect(answers).toHaveCount(before + 1, { timeout: 30_000 });
}

// What only the whole stack shows: citations read back from Postgres history, a second user
// against the first one's passage, the picker's choice reaching the run, and a deleted document.
test(
  "citations last a reload, stay with their owner, follow the picker and a delete",
  { tag: ["@knowledge"] },
  async ({ page, browser }) => {
    const user = `kc${Date.now().toString(36)}`;
    await signIn(page, user);
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await addBase(page, "Policies", "leave-policy.txt", "Leave policy\n\n25 days of paid leave.\n");
    await addBase(page, "Travel", "travel.txt", "Travel\n\nTrains are booked in second class.\n");

    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await ask(page, "search: paid leave");
    const firstChip = () =>
      page.getByRole("list", { name: "Sources" }).first().getByRole("button").first();
    await expect(firstChip()).toContainText("leave-policy.txt");
    const chipText = (await firstChip().textContent()) ?? "";
    const [opened] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/chunks/")),
      firstChip().click(),
    ]);
    const chunkUrl = opened.url();
    await page.getByRole("button", { name: "Close source" }).click();

    // The token is kept in memory (ADR 0010), so a reload signs in again; the thread's history
    // comes back from the Postgres checkpointer with the same chips.
    await signIn(page, user);
    await page
      .getByRole("button", { name: /^Open / })
      .first()
      .click();
    await expect(firstChip()).toHaveText(chipText);

    // A second user sees no base, and the first user's passage is the same 404 as one that
    // never existed.
    const other = await (await browser.newContext()).newPage();
    const sent = other.waitForRequest((r) => r.headers()["authorization"] !== undefined);
    await signIn(other, `${user}b`);
    const headers = { authorization: (await sent).headers()["authorization"] ?? "" };
    await other.getByRole("button", { name: "Knowledge", exact: true }).click();
    await expect(other.getByText("No knowledge bases yet.")).toBeVisible();
    const none = "00000000-0000-4000-8000-000000000000";
    const theirs = await other.request.get(chunkUrl, { headers });
    const missing = await other.request.get(
      `${new URL(chunkUrl).origin}/v1/knowledge/documents/${none}/chunks/${none}`,
      { headers },
    );
    expect(theirs.status()).toBe(404);
    expect([theirs.status(), await theirs.text()]).toEqual([
      missing.status(),
      await missing.text(),
    ]);
    await other.context().close();

    // Only Travel chosen: a question about leave cites nothing from Policies.
    const toggle = page.getByRole("button", { name: /Knowledge to search/ });
    await toggle.click();
    await page.getByRole("checkbox", { name: "Travel" }).check();
    await expect(toggle).toContainText("1 of 2 bases");
    await toggle.click();
    await ask(page, "search: paid leave");
    await expect(
      page.getByRole("log", { name: "Messages" }).getByText("leave-policy.txt"),
    ).toHaveCount(1);

    // Delete the cited document: its old citation opens as unavailable, with no passage.
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("button", { name: "Policies", exact: true }).click();
    await page.getByRole("button", { name: "Delete leave-policy.txt" }).click();
    await page.getByRole("button", { name: "Confirm delete leave-policy.txt" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "leave-policy.txt" })).toHaveCount(0);
    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await firstChip().click();
    const sheet = page.getByRole("region", { name: /^1\. / });
    await expect(sheet.getByText(/Source not available/)).toBeVisible();
    await expect(sheet.locator("blockquote")).toHaveCount(0);
  },
);

// The chat stays mounted behind the Knowledge screen: its picker must still see a base made
// there (it used to stay hidden until a reload) and drop one deleted there (it used to send the
// deleted id, so the question searched nothing).
test(
  "the picker follows bases made and deleted on the Knowledge screen",
  { tag: ["@knowledge"] },
  async ({ page }) => {
    await signIn(page, `kp${Date.now().toString(36)}`);
    const toggle = page.getByRole("button", { name: /Knowledge to search/ });
    await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
    await expect(toggle).toHaveCount(0);

    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await addBase(page, "Policies", "leave-policy.txt", "Leave policy\n\n25 days of paid leave.\n");
    await addBase(page, "Travel", "travel.txt", "Travel\n\nTrains are booked in second class.\n");
    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await expect(toggle).toContainText("All knowledge");

    await toggle.click();
    await page.getByRole("checkbox", { name: "Travel" }).check();
    await expect(toggle).toContainText("1 of 2 bases");
    await toggle.click();

    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("button", { name: "Delete Travel" }).click();
    await page.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByRole("button", { name: "Travel", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await expect(toggle).toContainText("All knowledge");

    await ask(page, "search: paid leave");
    const log = page.getByRole("log", { name: "Messages" });
    await expect(log.getByText("From your documents.")).toBeVisible();
    await expect(log.getByText("leave-policy.txt")).toBeVisible();
  },
);

test(
  "a user's knowledge is in their export and goes when they erase their data",
  { tag: ["@knowledge", "@data-rights"] },
  async ({ page }) => {
    const user = `kd${Date.now().toString(36)}`;
    await signIn(page, user);
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await addBase(page, "Handbook", "leave-policy.txt", "Leave policy\n\n25 days of paid leave.\n");

    await page.getByRole("button", { name: "Your data" }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download my data" }).click();
    const exported = JSON.parse(readFileSync(await (await download).path(), "utf8")) as {
      knowledge_bases: { name: string; documents: { title: string; status: string }[] }[];
    };
    expect(exported.knowledge_bases).toEqual([
      expect.objectContaining({
        name: "Handbook",
        documents: [expect.objectContaining({ title: "leave-policy.txt", status: "ready" })],
      }),
    ]);

    // The worker purges files after the request, so the first erase may ask to be repeated;
    // the user is signed out only once everything is gone.
    const signInButton = page.getByRole("button", { name: /sign in/i });
    // Sign-out shows the signed-out page (already at `/`) first, then goes to the provider's
    // logout, which redirects back to `/`: signing in again before that page loads collides with
    // its navigation. The redirected page is the only main-frame navigation sign-out makes.
    const backHome = page.waitForEvent("framenavigated", {
      predicate: (frame) => frame === page.mainFrame(),
      timeout: 60_000,
    });
    await expect(async () => {
      if (await signInButton.isVisible()) return;
      await page.getByRole("textbox", { name: /erase my data/ }).fill("erase my data");
      await page.getByRole("button", { name: "Erase all my data" }).click();
      await expect(signInButton).toBeVisible({ timeout: 3_000 });
    }).toPass({ timeout: 60_000 });
    await backHome;
    await page.waitForLoadState("load");

    await signIn(page, user);
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await expect(page.getByText("No knowledge bases yet.")).toBeVisible();
  },
);

test(
  "markup in a document is shown as text in its source, and never runs",
  { tag: ["@knowledge", "@security"] },
  async ({ page }) => {
    await signIn(page, `ks${Date.now().toString(36)}`);
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    const hostile =
      "# Pumps\n\nPump 7 is serviced monthly." +
      ' <img src="x" onerror="window.__ran=1"> <script>window.__ran=1</script>\n';
    await addBase(page, "Plant", "pumps.txt", hostile);

    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await ask(page, "search: serviced monthly");
    await page.getByRole("list", { name: "Sources" }).first().getByRole("button").first().click();
    const sheet = page.getByRole("region", { name: /^1\. pumps\.txt/ });
    await expect(sheet.getByText(/onerror="window\.__ran=1"/)).toBeVisible();
    await expect(sheet.locator("img, script")).toHaveCount(0);
    expect(await page.evaluate(() => (window as { __ran?: number }).__ran)).toBeUndefined();
  },
);

// RAG-09.03: the owner shares a base with a role, a member of it sees it read-only, and a revoke
// takes it away on the member's next request.
test(
  "an owner shares a base with a role and stops sharing it",
  { tag: ["@knowledge"] },
  async ({ page, browser }) => {
    const user = `ks${Date.now().toString(36)}`;
    const role = `team-${user}`;
    await signIn(page, user);
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByLabel("New knowledge base").fill("Team handbook");
    await page.getByRole("button", { name: "Create" }).click();

    const sharing = page.getByRole("region", { name: "Sharing Team handbook" });
    await expect(sharing.getByText("Not shared with any role.")).toBeVisible();
    await sharing.getByLabel("Role", { exact: true }).fill(role);
    await sharing.getByRole("button", { name: "Share" }).click();
    const access = sharing.getByRole("combobox", { name: `Access for ${role}` });
    await expect(access).toHaveValue("read");
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${scheme}\\b`));
      expect(await violations(page), `${scheme} theme`).toEqual([]);
    }

    const member = await (await browser.newContext()).newPage();
    await signIn(member, `${user}m`, role);
    await member.getByRole("button", { name: "Knowledge", exact: true }).click();
    await member.getByRole("button", { name: "Team handbook", exact: true }).click();
    await expect(member.getByText("Shared with you · Read")).toBeVisible();
    await expect(member.getByText(/shared with you to read/)).toBeVisible();
    await expect(member.getByLabel(/Drop files here/)).toHaveCount(0);
    await expect(member.getByRole("button", { name: "Delete Team handbook" })).toHaveCount(0);
    await expect(member.getByRole("region", { name: /^Sharing/ })).toHaveCount(0);

    // A role with `admin` access may manage the sharing too.
    await access.selectOption("admin");
    // The list shows the stored grant once the server has it.
    await expect(access).toHaveValue("admin");
    await member.getByRole("button", { name: "Chat" }).click();
    await member.getByRole("button", { name: "Knowledge", exact: true }).click();
    await member.getByRole("button", { name: "Team handbook", exact: true }).click();
    await expect(member.getByText("Shared with you · Manage")).toBeVisible();
    await expect(member.getByRole("region", { name: "Sharing Team handbook" })).toBeVisible();

    await sharing.getByRole("button", { name: `Stop sharing with ${role}` }).click();
    await expect(sharing.getByText("Not shared with any role.")).toBeVisible();
    await member.getByRole("button", { name: "Chat" }).click();
    await member.getByRole("button", { name: "Knowledge", exact: true }).click();
    await expect(member.getByText("No knowledge bases yet.")).toBeVisible();
  },
);
