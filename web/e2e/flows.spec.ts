import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

const APP = "http://localhost:5173";
const SERVED = new Set([APP, "http://localhost:8180", "http://127.0.0.1:8000"]);

async function signIn(page: Page, user: string, open = true): Promise<void> {
  if (open) await page.goto("/");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.locator("#username").fill(user);
  await page.locator("#login").click();
  await expect(page.getByText(`Signed in as ${user}`)).toBeVisible();
}

async function send(page: Page, text: string): Promise<void> {
  await page.getByRole("textbox").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0);
}

const fresh = () => `user${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

const memories = (page: Page) => page.getByRole("region", { name: "Memories" });

test("a user signs in, chats, rates the answer and signs out", async ({ page }) => {
  await signIn(page, fresh());
  await send(page, "What is 2+2?");
  await expect(page.getByText("Local test response.")).toBeVisible();
  await page.getByRole("button", { name: "Helpful", exact: true }).click();
  await expect(page.getByText("Your rating: Helpful.")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
});

test("a remembered note waits for approval, is stored once approved, and can be removed", async ({
  page,
}) => {
  await signIn(page, fresh());
  await send(page, "remember: I like tea");
  await expect(page.getByText("Approval needed")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("You approved this.")).toBeVisible();

  await page.getByRole("button", { name: "Your data" }).click();
  await expect(memories(page).getByText("I like tea", { exact: true })).toBeVisible();
  await memories(page).getByRole("button", { name: "Delete" }).click();
  await memories(page).getByRole("button", { name: "Confirm delete" }).click();
  await expect(memories(page).getByText("I like tea", { exact: true })).toHaveCount(0);
});

test("a rejected note is not stored", async ({ page }) => {
  await signIn(page, fresh());
  await send(page, "remember: I dislike coffee");
  await expect(page.getByText("Approval needed")).toBeVisible();
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("You rejected this.")).toBeVisible();
  await page.getByRole("button", { name: "Your data" }).click();
  await expect(memories(page).getByText("I dislike coffee")).toHaveCount(0);
});

test("a conversation survives a reload, can be renamed, and deleted", async ({ page }) => {
  const user = fresh();
  await signIn(page, user);
  await send(page, "Tell me something");
  await page.reload();
  // The token lives in memory only, so a reload asks for one click and no password.
  await signIn(page, user, false);
  await page.getByRole("button", { name: "Open Tell me something" }).click();
  await expect(page.getByText("Local test response.")).toBeVisible();

  await page.getByRole("button", { name: "Rename Tell me something" }).click();
  await page.getByRole("textbox", { name: /title|name/i }).fill("Tea talk");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("button", { name: "Open Tea talk" })).toBeVisible();

  await page.getByRole("button", { name: "Delete Tea talk" }).click();
  await page.getByRole("button", { name: "Confirm delete" }).click();
  await expect(page.getByRole("button", { name: "Open Tea talk" })).toHaveCount(0);
});

test("a user only sees their own conversations", async ({ browser }) => {
  const alice = await (await browser.newContext()).newPage();
  await signIn(alice, fresh());
  await send(alice, "private question");
  const bob = await (await browser.newContext()).newPage();
  await signIn(bob, fresh());
  await expect(bob.getByRole("button", { name: "Open private question" })).toHaveCount(0);
});

test("a user can download their data and then erase it", async ({ page }) => {
  await signIn(page, fresh());
  await send(page, "remember: export me");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("You approved this.")).toBeVisible();
  await page.getByRole("button", { name: "Your data" }).click();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download my data" }).click();
  const file = await (await download).path();
  const exported = JSON.parse(readFileSync(file, "utf8")) as {
    memories: { text: string }[];
    threads: unknown[];
  };
  expect(exported.memories.map((m) => m.text)).toEqual(["export me"]);
  expect(exported.threads).toHaveLength(1);

  await page.getByRole("textbox", { name: /erase my data/ }).fill("erase my data");
  await page.getByRole("button", { name: "Erase all my data" }).click();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
});

test("hostile text is shown as text and nothing leaves the three local origins", async ({
  page,
}) => {
  const origins = new Set<string>();
  const dialogs: string[] = [];
  page.on("request", (request) => origins.add(new URL(request.url()).origin));
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  await signIn(page, fresh());
  await send(
    page,
    '<img src=x onerror="window.__xss=1"> <script>window.__xss=2</script> ' +
      "![b](http://localhost:9/beacon.png) [Approve](javascript:window.__xss=3) Approval needed.",
  );
  await expect(page.getByText("Local test response.")).toBeVisible();

  expect(await page.evaluate(() => (window as { __xss?: number }).__xss)).toBeUndefined();
  expect(dialogs).toEqual([]);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  expect([...origins].filter((o) => o.startsWith("http") && !SERVED.has(o))).toEqual([]);

  // The one-time code and state are gone from the address bar, and no token is in storage.
  expect(page.url()).not.toMatch(/code=|state=/);
  const stored = await page.evaluate(() => {
    const dump = (area: Storage) =>
      Array.from({ length: area.length }, (_, i) => area.getItem(area.key(i) ?? ""));
    return JSON.stringify([dump(localStorage), dump(sessionStorage), document.cookie]);
  });
  expect(stored).not.toMatch(/eyJ/);
});

test("the theme choice is kept across a reload", async ({ page }) => {
  const user = fresh();
  await signIn(page, user);
  await page.getByRole("button", { name: "Theme: system" }).click();
  await expect(page.getByRole("button", { name: "Theme: light" })).toBeVisible();
  await page.getByRole("button", { name: "Theme: light" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await signIn(page, user, false);
  await expect(page.locator("html")).toHaveClass(/dark/);
});
