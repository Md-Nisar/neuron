import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi, memory, thread, type FakeData } from "@/test/dataApi";
import { jsonResponse } from "@/test/sse";

import { DataScreen } from "./DataScreen";

afterEach(() => {
  vi.restoreAllMocks();
});

const urlOf = (input: Parameters<typeof fetch>[0]): string =>
  input instanceof URL ? input.href : typeof input === "string" ? input : input.url;

function setup(data: FakeData, options: { token?: string | null; fetch?: typeof fetch } = {}) {
  const api = fakeApi(data);
  const onSessionEnded = vi.fn();
  const onErased = vi.fn();
  const user = userEvent.setup();
  const view = render(
    <DataScreen
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => (options.token === undefined ? "tok-1" : options.token),
        onSessionEnded,
        fetch: options.fetch ?? api.fetch,
      }}
      onErased={onErased}
    />,
  );
  return { api, onSessionEnded, onErased, user, view };
}

describe("memories", () => {
  it("lists them, as text, with a date", async () => {
    const hostile =
      '<img src=x onerror="alert(1)"><script>alert(2)</script> [x](javascript:alert(3))';
    const { view } = setup({ memories: [memory(1, "likes tea"), memory(2, hostile)], threads: [] });

    expect(await screen.findByText("likes tea")).toBeInTheDocument();
    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(view.container.querySelector("img, script, a")).toBeNull();
  });

  it("says so when there are none", async () => {
    setup({ memories: [], threads: [] });

    expect(await screen.findByText("No memories.")).toBeInTheDocument();
  });

  it("pages with Load more", async () => {
    const memories = Array.from({ length: 60 }, (_, i) => memory(i + 1));
    const { user } = setup({ memories, threads: [] });
    await screen.findByText("memory 1");

    expect(screen.queryByText("memory 51")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("memory 60")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("deletes in two steps and sends the id in the path", async () => {
    const { api, user } = setup({ memories: [memory(1, "keep"), memory(2, "drop")], threads: [] });
    const item = (await screen.findByText("drop")).closest("li");
    if (item === null) throw new Error("no item");
    await user.click(within(item).getByRole("button", { name: "Delete" }));
    expect(api.calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
    await user.click(within(item).getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => {
      expect(screen.queryByText("drop")).toBeNull();
    });
    expect(screen.getByText("keep")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "DELETE")?.url.pathname).toBe(
      "/v1/me/memories/mem-2",
    );
  });

  it("keeps the memory when the user cancels", async () => {
    const { api, user } = setup({ memories: [memory(1, "keep")], threads: [] });
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("keep")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  });

  it("keeps the memory and says so when the delete fails", async () => {
    const data = { memories: [memory(1, "keep")], threads: [] };
    const api = fakeApi(data);
    const failingDelete: typeof fetch = (input, init) =>
      init?.method === "DELETE"
        ? Promise.resolve(jsonResponse(500, { detail: "internal_server_error" }))
        : api.fetch(input, init);
    const { user } = setup(data, { fetch: failingDelete });
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong on the server.",
    );
    expect(screen.getByText("keep")).toBeInTheDocument();
  });

  it("explains when memory is turned off", async () => {
    setup({ memories: [], threads: [], memoryEnabled: false });

    expect(await screen.findByText("Memory is turned off for this service.")).toBeInTheDocument();
  });

  it("ends the session on 401", async () => {
    const { onSessionEnded } = setup(
      { memories: [], threads: [] },
      { fetch: () => Promise.resolve(jsonResponse(401, { detail: "authentication_error" })) },
    );

    await waitFor(() => {
      expect(onSessionEnded).toHaveBeenCalled();
    });
  });

  it("refuses a page whose ids could escape a URL path", async () => {
    const bad = {
      memories: [{ id: "..", text: "x", created_at: "2026-10-01T10:00:00Z" }],
      total: 1,
      limit: 50,
      offset: 0,
    };
    setup({ memories: [], threads: [] }, { fetch: () => Promise.resolve(jsonResponse(200, bad)) });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong. Please try again.",
    );
    expect(screen.queryByText("x")).toBeNull();
  });
});

describe("export", () => {
  function captureDownloads() {
    const blobs: Blob[] = [];
    const revoked: string[] = [];
    const clicks: { download: string; href: string }[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: (blob: Blob) => {
        blobs.push(blob);
        return `blob:test-${String(blobs.length)}`;
      },
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: (url: string) => {
        revoked.push(url);
      },
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push({ download: this.download, href: this.getAttribute("href") ?? "" });
    });
    return { blobs, revoked, clicks };
  }

  const exportData = (): FakeData => ({
    memories: [memory(1, "likes tea")],
    threads: [thread(1, 3), thread(2, 25)],
  });

  it("downloads one dated JSON file with everything in it, then revokes the URL", async () => {
    const downloads = captureDownloads();
    const { user } = setup(exportData());
    await screen.findByText("likes tea");
    await user.click(screen.getByRole("button", { name: "Download my data" }));

    expect(await screen.findByText("Your file was downloaded.")).toBeInTheDocument();
    expect(downloads.clicks).toHaveLength(1);
    expect(downloads.clicks[0]?.download).toMatch(/^neuron-export-\d{4}-\d{2}-\d{2}\.json$/);
    const file = JSON.parse((await downloads.blobs[0]?.text()) ?? "{}") as {
      threads: { messages: unknown[] }[];
      memories: { text: string }[];
    };
    expect(file.threads.map((t) => t.messages.length)).toEqual([3, 25]);
    expect(file.memories[0]?.text).toBe("likes tea");
    await waitFor(() => {
      expect(downloads.revoked).toEqual(["blob:test-1"]);
    });
  });

  it("keeps none of it afterwards: not on the page, not in storage, not in cookies", async () => {
    captureDownloads();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { user } = setup(exportData());
    await screen.findByText("likes tea");
    await user.click(screen.getByRole("button", { name: "Download my data" }));
    await screen.findByText("Your file was downloaded.");

    expect(document.body.textContent).not.toContain("t1 message 0");
    expect(document.body.textContent).not.toContain("t2 message 24");
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("asks the server without caching", async () => {
    captureDownloads();
    const { api, user } = setup(exportData());
    await screen.findByText("likes tea");
    await user.click(screen.getByRole("button", { name: "Download my data" }));
    await screen.findByText("Your file was downloaded.");
    const exportCall = api.fetch.mock.calls.find(([input]) =>
      urlOf(input).includes("/v1/me/export"),
    );

    expect(exportCall?.[1]).toMatchObject({ cache: "no-store", credentials: "omit" });
  });

  it("makes one export while one is running, however many times it is clicked", async () => {
    const downloads = captureDownloads();
    const api = fakeApi(exportData());
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const slow: typeof fetch = async (input, init) => {
      if (urlOf(input).includes("/v1/me/export")) await gate;
      return api.fetch(input, init);
    };
    const { user } = setup(exportData(), { fetch: slow });
    await screen.findByText("likes tea");
    const button = screen.getByRole("button", { name: "Download my data" });
    await user.click(button);
    await user.click(screen.getByRole("button", { name: "Preparing…" }));
    await user.click(screen.getByRole("button", { name: "Preparing…" }));
    release();
    await screen.findByText("Your file was downloaded.");

    expect(downloads.clicks).toHaveLength(1);
    const starts = api.calls.filter(
      (c) =>
        c.url.pathname === "/v1/me/export" &&
        c.url.searchParams.get("offset") === "0" &&
        c.url.searchParams.get("message_offset") === "0",
    );
    expect(starts).toHaveLength(1);
  });

  it("offers no file when the export fails, and says why", async () => {
    const downloads = captureDownloads();
    const api = fakeApi(exportData());
    const failing: typeof fetch = (input, init) =>
      urlOf(input).includes("/v1/me/export")
        ? Promise.resolve(jsonResponse(500, { detail: "internal_server_error" }))
        : api.fetch(input, init);
    const { user } = setup(exportData(), { fetch: failing });
    await screen.findByText("likes tea");
    await user.click(screen.getByRole("button", { name: "Download my data" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong on the server.",
    );
    expect(downloads.clicks).toHaveLength(0);
    expect(downloads.blobs).toHaveLength(0);
  });

  it("tells the user when their data is too large to export here", async () => {
    const downloads = captureDownloads();
    const { user } = setup({ ...exportData(), maxItemsPerPage: 0 });
    await screen.findByText("likes tea");
    await user.click(screen.getByRole("button", { name: "Download my data" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("too large to export");
    expect(downloads.clicks).toHaveLength(0);
  });
});

describe("erase", () => {
  const phrase = "erase my data";

  it("needs the typed phrase before the button works", async () => {
    const { user } = setup({ memories: [], threads: [] });
    const button = screen.getByRole("button", { name: "Erase all my data" });
    const field = screen.getByLabelText(/Type erase my data to confirm/);
    expect(button).toBeDisabled();

    await user.type(field, "erase my dat");
    expect(button).toBeDisabled();
    await user.clear(field);
    await user.type(field, "delete");
    expect(button).toBeDisabled();
    await user.clear(field);
    await user.type(field, `  ${phrase.toUpperCase()} `);
    expect(button).toBeEnabled();
  });

  it("erases, reports the counts, and signs the user out when everything was erased", async () => {
    const { api, user, onErased } = setup({
      memories: [memory(1), memory(2)],
      threads: [thread(1, 2), thread(2, 2), thread(3, 2)],
    });
    await user.type(screen.getByLabelText(/Type erase my data to confirm/), phrase);
    await user.click(screen.getByRole("button", { name: "Erase all my data" }));

    expect(
      await screen.findByText(/Erased 3 conversations and 2 memories\. Signing you out/),
    ).toBeInTheDocument();
    expect(onErased).toHaveBeenCalledOnce();
    expect(
      api.calls.filter((c) => c.method === "DELETE" && c.url.pathname === "/v1/me/threads"),
    ).toHaveLength(1);
    expect(screen.getByLabelText(/Type erase my data to confirm/)).toHaveValue("");
  });

  it("stays signed in and says what is left when a conversation was busy", async () => {
    const { user, onErased } = setup({
      memories: [],
      threads: [thread(1, 2), thread(2, 2)],
      eraseSkipsBusy: 1,
    });
    await user.type(screen.getByLabelText(/Type erase my data to confirm/), phrase);
    await user.click(screen.getByRole("button", { name: "Erase all my data" }));

    const erase = within(screen.getByRole("region", { name: "Erase your data" }));
    expect(await erase.findByRole("status")).toHaveTextContent(
      "1 could not be erased because a reply was still running",
    );
    expect(onErased).not.toHaveBeenCalled();
  });

  it("makes one request on a double-click", async () => {
    const { api, user } = setup({ memories: [], threads: [thread(1, 1)] });
    await user.type(screen.getByLabelText(/Type erase my data to confirm/), phrase);
    await user.dblClick(screen.getByRole("button", { name: "Erase all my data" }));
    await screen.findByText(/Erased 1 conversations/);

    expect(
      api.calls.filter((c) => c.method === "DELETE" && c.url.pathname === "/v1/me/threads"),
    ).toHaveLength(1);
  });

  it.each([
    [403, { detail: "authorization_error" }, "You do not have permission to do that."],
    [429, { detail: "rate_limited" }, "Too many requests."],
    [500, { detail: "internal_server_error" }, "Something went wrong on the server."],
  ])("shows fixed wording for HTTP %i and does not sign out", async (status, body, text) => {
    const { user, onErased } = setup(
      { memories: [], threads: [] },
      {
        fetch: (_input, init) =>
          Promise.resolve(
            init?.method === "DELETE"
              ? jsonResponse(status, body)
              : jsonResponse(200, { memories: [], total: 0, limit: 50, offset: 0 }),
          ),
      },
    );
    await user.type(screen.getByLabelText(/Type erase my data to confirm/), phrase);
    await user.click(screen.getByRole("button", { name: "Erase all my data" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(onErased).not.toHaveBeenCalled();
  });

  it("ends the session on 401", async () => {
    const { user, onSessionEnded, onErased } = setup(
      { memories: [], threads: [] },
      {
        fetch: (_input, init) =>
          Promise.resolve(
            init?.method === "DELETE"
              ? jsonResponse(401, { detail: "authentication_error" })
              : jsonResponse(200, { memories: [], total: 0, limit: 50, offset: 0 }),
          ),
      },
    );
    await user.type(screen.getByLabelText(/Type erase my data to confirm/), phrase);
    await user.click(screen.getByRole("button", { name: "Erase all my data" }));

    await waitFor(() => {
      expect(onSessionEnded).toHaveBeenCalled();
    });
    expect(onErased).not.toHaveBeenCalled();
  });
});
