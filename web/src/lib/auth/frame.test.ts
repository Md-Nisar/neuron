import { afterEach, describe, expect, it, vi } from "vitest";

import { reportFrameCallback, runAuthFrame } from "./frame";

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

function framedWindow(href: string, framed: boolean) {
  const parent = { postMessage: vi.fn() };
  const win = {
    self: {},
    top: framed ? {} : undefined,
    parent,
    location: new URL(href),
  };
  if (!framed) win.top = win.self;
  return { win: win as unknown as Window, parent };
}

describe("reportFrameCallback", () => {
  it("does nothing in a top-level page", () => {
    const { win, parent } = framedWindow("http://localhost:3000/?code=c&state=s", false);

    expect(reportFrameCallback(win)).toBe(false);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("does nothing in a frame that is not a sign-in callback", () => {
    const { win, parent } = framedWindow("http://localhost:3000/", true);

    expect(reportFrameCallback(win)).toBe(false);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("hands a callback to the parent, addressed to its own origin only", () => {
    const href = "http://localhost:3000/?code=c&state=s";
    const { win, parent } = framedWindow(href, true);

    expect(reportFrameCallback(win)).toBe(true);
    expect(parent.postMessage).toHaveBeenCalledWith(
      { type: "neuron-auth-callback", href },
      "http://localhost:3000",
    );
  });
});

describe("runAuthFrame", () => {
  const origin = window.location.origin;
  const message = (
    frame: HTMLIFrameElement,
    data: unknown,
    from = origin,
    source = frame.contentWindow,
  ) => window.dispatchEvent(new MessageEvent("message", { data, origin: from, source }));

  it("resolves with the callback the frame reports, then removes the frame", async () => {
    const result = runAuthFrame("http://localhost:8180/auth?prompt=none");
    const frame = document.querySelector("iframe");
    expect(frame).not.toBeNull();
    expect(frame?.getAttribute("aria-hidden")).toBe("true");
    if (frame === null) return;
    message(frame, { type: "neuron-auth-callback", href: `${origin}/?code=c&state=s` });

    expect(await result).toBe(`${origin}/?code=c&state=s`);
    expect(document.querySelector("iframe")).toBeNull();
  });

  it.each([
    [
      "another origin",
      { type: "neuron-auth-callback", href: "x" },
      "https://evil.example",
      "frame",
    ],
    ["another window", { type: "neuron-auth-callback", href: "x" }, undefined, "other"],
    ["the wrong type", { type: "something-else", href: "x" }, undefined, "frame"],
    ["a non-string href", { type: "neuron-auth-callback", href: 5 }, undefined, "frame"],
    ["no data", null, undefined, "frame"],
  ])("ignores a message from %s", async (_name, data, from, who) => {
    vi.useFakeTimers();
    const result = runAuthFrame("http://localhost:8180/auth", document, 1000);
    const caught = result.catch((error: unknown) => error);
    const frame = document.querySelector("iframe");
    if (frame === null) throw new Error("no frame");
    message(frame, data, from ?? origin, who === "frame" ? frame.contentWindow : window);
    await vi.advanceTimersByTimeAsync(1000);

    expect(await caught).toBeInstanceOf(Error);
  });

  it("rejects on timeout and still removes the frame", async () => {
    vi.useFakeTimers();
    const caught = runAuthFrame("http://localhost:8180/auth", document, 500).catch(
      (e: unknown) => e,
    );
    await vi.advanceTimersByTimeAsync(500);

    expect(await caught).toBeInstanceOf(Error);
    expect(document.querySelector("iframe")).toBeNull();
  });
});
