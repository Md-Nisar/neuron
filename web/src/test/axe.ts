import axe from "axe-core";

import indexHtml from "../../index.html?raw";

/**
 * The test document is not the real page: it has no <title> and no `lang`. Take both from the
 * real `index.html`, so the page-level rules check what ships (and fail if either is removed).
 */
function applyPageMetadata(): void {
  const page = new DOMParser().parseFromString(indexHtml, "text/html");
  document.documentElement.lang = page.documentElement.lang;
  document.title = page.title;
}

/**
 * Accessibility violations in the current document, as readable lines. Colour contrast needs
 * real layout and styles, which jsdom does not have, so it is checked by hand (web/README.md).
 */
export async function accessibilityViolations(
  context: Element | Document = document,
): Promise<string[]> {
  applyPageMetadata();
  const results = await axe.run(context, {
    rules: { "color-contrast": { enabled: false } },
    resultTypes: ["violations"],
  });
  return results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? "n/a"}): ${violation.nodes.map((node) => node.target.join(" ")).join(", ")}`,
  );
}
