import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// RAG-03.04: an uploaded file holding markup, downloaded from the API, runs no script. The
// browser gets the headers the download route sends for a text upload, which
// tests/integration/test_postgres_knowledge_download.py checks against the real route; the API
// in this stack has no Postgres, so the response itself is served here.
const API = "http://127.0.0.1:8000";
const FILE = `${API}/v1/knowledge/documents/d/file`;
const HEADERS = JSON.parse(
  readFileSync(new URL("./download_headers.json", import.meta.url), "utf8"),
) as Record<string, string>;
// Each script, if it runs, calls back to the API's origin, where the test counts the calls.
const BODIES = {
  SVG: `<svg xmlns="http://www.w3.org/2000/svg" onload="fetch('/ran?1')"><script>fetch('/ran?2')</script></svg>`,
  HTML: `<!doctype html><script>fetch('/ran?3')</script><img src=x onerror="fetch('/ran?4')">`,
};

/** Serve `body` with `headers` as the file, open it every way a page can, and count the runs. */
async function scriptsRun(page: Page, body: string, headers: Record<string, string>) {
  let runs = 0;
  await page.route(`${API}/ran*`, (route) => {
    runs += 1;
    return route.fulfill({ status: 204 });
  });
  await page.route(FILE, (route) => route.fulfill({ status: 200, headers, body }));
  await page.goto("/");
  await page.evaluate((url) => {
    const embeds: [string, string][] = [
      ["iframe", "src"],
      ["object", "data"],
      ["embed", "src"],
      ["img", "src"],
    ];
    for (const [tag, attr] of embeds) {
      const element = document.createElement(tag);
      element.setAttribute(attr, url);
      document.body.append(element);
    }
  }, FILE);
  await page.waitForTimeout(1_000);
  return runs;
}

for (const [kind, body] of Object.entries(BODIES)) {
  test(
    `a downloaded ${kind} file is saved, never run`,
    { tag: ["@knowledge"] },
    async ({ page }) => {
      const headers = { ...HEADERS, "content-disposition": 'attachment; filename="notes.md"' };
      expect(await scriptsRun(page, body, headers)).toBe(0);
      // Followed as a link, it is a download, not a page.
      const download = page.waitForEvent("download");
      await page.evaluate((url) => {
        const link = Object.assign(document.createElement("a"), { href: url });
        document.body.append(link);
        link.click();
      }, FILE);
      expect((await download).suggestedFilename()).toBe("notes.md");
    },
  );

  test(`the check sees a ${kind} file's script run when served as a page`, async ({ page }) => {
    const type = kind === "SVG" ? "image/svg+xml" : "text/html";
    expect(await scriptsRun(page, body, { "content-type": type })).toBeGreaterThan(0);
  });
}
