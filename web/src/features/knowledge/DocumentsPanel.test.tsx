import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { DocumentsPanel, POLL_MS, pollDelay } from "./DocumentsPanel";
import { documentFailureText } from "./messages";
import type { BaseAccess, Processing } from "./parse";

const KB = "0b6f1c1e-6c8e-4c36-9d2b-6a1f2f3e4d5c";
const doc = (status: string, error_code: string | null = null) => ({
  doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c6",
  kb_id: KB,
  title: "Handbook.pdf",
  size_bytes: 2048,
  page_count: null,
  status,
  error_code,
  mime_type: "application/pdf",
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-01T10:00:00Z",
  source_url: null as string | null,
});

/** A status as its badge shows it (the status filter has options with the same words). */
const badge = (text: string) => screen.findByText(text, { selector: "[data-slot=badge]" });

afterEach(() => {
  vi.useRealTimers();
});

/**
 * Each `GET` answers with the next list (the last one repeats; an `Error` entry is a 500);
 * each `POST` with the next of `uploads` (the last one repeats); `DELETE` with `remove`.
 */
function setup(
  lists: (unknown[] | Error)[],
  options: {
    processing?: Processing;
    uploads?: Response[];
    remove?: Response;
    access?: BaseAccess;
  } = {},
) {
  let call = 0;
  let posted = 0;
  const onTotal = vi.fn();
  const fetch = vi.fn<typeof globalThis.fetch>((_input, init) => {
    if (init?.method === "POST") {
      const uploads = options.uploads ?? [];
      return Promise.resolve(
        uploads[Math.min(posted++, uploads.length - 1)]?.clone() ??
          jsonResponse(202, { doc_id: doc("queued").doc_id, kb_id: KB, status: "queued" }),
      );
    }
    if (init?.method === "DELETE")
      return Promise.resolve(options.remove ?? new Response(null, { status: 202 }));
    const documents = lists[Math.min(call++, lists.length - 1)] ?? [];
    if (documents instanceof Error) return Promise.resolve(jsonResponse(500, {}));
    return Promise.resolve(jsonResponse(200, { documents, total: documents.length }));
  });
  const base = {
    kb_id: KB,
    name: "Policies",
    processing: options.processing ?? "hosted",
    language: "simple" as const,
    created_at: "",
    access: options.access ?? "owner",
    document_count: null,
  };
  const user = userEvent.setup(vi.isFakeTimers() ? { advanceTimers: vi.advanceTimersByTime } : {});
  const view = render(
    <DocumentsPanel
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "t",
        onSessionEnded: vi.fn(),
        fetch,
      }}
      base={base}
      onTotal={onTotal}
    />,
  );
  return { fetch, user, view, onTotal };
}

const gets = (fetch: ReturnType<typeof setup>["fetch"]) =>
  fetch.mock.calls.filter(([, init]) => init?.method === "GET").length;

describe("documents", () => {
  it("says where a hosted base's text goes before anything is uploaded", () => {
    setup([[]]);
    expect(screen.getByText(/sent to the configured embedding provider/)).toBeInTheDocument();
  });

  it("says a self-hosted base's text stays on this service's own models", () => {
    setup([[]], { processing: "self_hosted" });
    expect(screen.getByText(/indexed only by models this service runs itself/)).toBeInTheDocument();
  });

  it("adds a web page by its address, listed as queued with no size until it is fetched", async () => {
    const page = {
      ...doc("queued"),
      title: "https://docs.example.com/leave",
      size_bytes: 0,
      source_url: "https://docs.example.com/leave",
    };
    const { fetch, user } = setup([[], [page]]);

    await user.click(screen.getByRole("button", { name: "Add web page" }));
    await user.type(screen.getByLabelText("Web page address"), "https://docs.example.com/leave");
    await user.click(screen.getByRole("button", { name: "Add page" }));

    expect(await badge("Queued")).toBeInTheDocument();
    expect(screen.getByText("Web page")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    const [url, init] = fetch.mock.calls.find(([, i]) => i?.method === "POST") ?? [];
    expect((url as URL).pathname).toBe(`/v1/knowledge/bases/${KB}/web-pages`);
    expect(JSON.parse(init?.body as string)).toEqual({ url: "https://docs.example.com/leave" });
    expect(new Headers(init?.headers).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.queryByText("0 B")).toBeNull();
    // A web page has nothing to download until it is fetched.
    await user.click(screen.getByRole("button", { name: /^Actions for https/ }));
    expect(screen.getByRole("menuitem", { name: "Download" })).toHaveAttribute("data-disabled");
  });

  it("keeps a refused address in the field and says why", async () => {
    const { user } = setup([[]], {
      uploads: [jsonResponse(422, { detail: "url_not_allowed" })],
    });

    await user.click(screen.getByRole("button", { name: "Add web page" }));
    await user.type(screen.getByLabelText("Web page address"), "https://127.0.0.1/");
    await user.click(screen.getByRole("button", { name: "Add page" }));

    const dialog = screen.getByRole("dialog", { name: "Add a web page" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "https://127.0.0.1/: Only public https web pages can be added.",
    );
    expect(screen.getByLabelText("Web page address")).toHaveValue("https://127.0.0.1/");
  });

  it("explains a page that failed to load", () => {
    expect(documentFailureText("fetch_timeout")).toMatch(/did not answer/);
    expect(documentFailureText("duplicate_content")).toMatch(/already in the knowledge base/);
  });

  it("shows an uploaded PDF as queued, then as ready, without a reload", async () => {
    // Real time still passes (for the queries' own waits); the polls are driven by hand.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch, user } = setup([[], [doc("queued")], [doc("ready")]]);
    const pdf = new File(["%PDF-1.7"], "Handbook.pdf", { type: "application/pdf" });

    await user.upload(screen.getByLabelText("Upload files"), pdf);

    expect(await badge("Queued")).toBeInTheDocument();
    const post = fetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect((post?.[1]?.body as FormData).get("file")).toBeInstanceOf(File);
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(await badge("Ready")).toBeInTheDocument();

    // Every document is settled: polling stops.
    const before = gets(fetch);
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 3));
    expect(gets(fetch)).toBe(before);
  });

  it("explains a failed document from its code, with no server text", async () => {
    setup([
      [
        doc("failed", "encrypted_pdf"),
        {
          ...doc("failed", "Traceback: /srv/x.py"),
          doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c7",
        },
      ],
    ]);

    expect(
      await screen.findByText(
        "The PDF is password-protected. Remove the password and upload it again.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Processing failed. Upload the file again.")).toBeInTheDocument();
    expect(screen.queryByText(/Traceback|srv/)).toBeNull();
  });

  it("maps every kind of failure code to fixed wording", () => {
    expect(documentFailureText("embedding_rate_limited")).toBe(
      "Indexing failed. Upload the file again later.",
    );
    expect(documentFailureText("blob_not_found")).toMatch(/stored file/);
    expect(documentFailureText("toString")).toBe("Processing failed. Upload the file again.");
    expect(documentFailureText(null)).toBe("Processing failed. Upload the file again.");
  });

  it("says clearly when an upload is over a quota", async () => {
    const { user } = setup([[]], {
      uploads: [jsonResponse(413, { detail: "byte_quota_exceeded" })],
    });

    await user.upload(screen.getByLabelText("Upload files"), new File(["x"], "notes.txt"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "notes.txt: You have used all your document storage. Delete documents to upload more.",
    );
  });

  it("keeps every refusal of a batch in view, and lists each upload once accepted", async () => {
    const { fetch, user } = setup([[], [doc("ready")]], {
      uploads: [
        jsonResponse(415, { detail: "unsupported_media_type" }),
        jsonResponse(202, { doc_id: doc("queued").doc_id, kb_id: KB, status: "queued" }),
        jsonResponse(413, { detail: "file_too_large" }),
      ],
    });

    await user.upload(screen.getByLabelText("Upload files"), [
      new File(["x"], "a.md"),
      new File(["x"], "b.txt"),
      new File(["x"], "c.pdf"),
    ]);

    const alert = await screen.findByRole("alert");
    await vi.waitFor(() => {
      expect(alert).toHaveTextContent(/c\.pdf: The file is too large/);
    });
    expect(alert).toHaveTextContent(/a\.md: This file type isn't supported/);
    expect(await badge("Ready")).toBeInTheDocument();
    expect(gets(fetch)).toBeGreaterThanOrEqual(2);
  });

  it("waits out a 'too many in processing' refusal and retries the file with the same key", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch, user } = setup([[], [doc("ready")]], {
      uploads: [
        jsonResponse(429, { detail: "ingestion_concurrency_exceeded" }, { "Retry-After": "2" }),
        jsonResponse(202, { doc_id: doc("queued").doc_id, kb_id: KB, status: "queued" }),
      ],
    });

    await user.upload(screen.getByLabelText("Upload files"), [new File(["x"], "a.md")]);
    // A busy server is not a failure the user must act on: no alert while it waits.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    expect(await badge("Ready")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const keys = fetch.mock.calls
      .filter(([, init]) => init?.method === "POST")
      .map(([, init]) => new Headers(init?.headers).get("Idempotency-Key"));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("gives up on a file that stays busy and says so", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setup([[]], {
      uploads: [
        jsonResponse(429, { detail: "ingestion_concurrency_exceeded" }, { "Retry-After": "1" }),
      ],
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    await user.upload(screen.getByLabelText("Upload files"), [new File(["x"], "a.md")]);
    for (let second = 0; second < 40; second++) await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /a\.md: Too many of your documents are still being processed/,
    );
  });

  it("waits longer between polls while a document is still processing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch } = setup([[doc("embedding")]]);
    expect(await badge("Indexing")).toBeInTheDocument();

    // Twenty seconds of polling make six requests, not the eleven a fixed 2 s would.
    for (let second = 0; second < 20; second++) await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(gets(fetch)).toBeLessThanOrEqual(6);
    expect(pollDelay(0)).toBe(POLL_MS);
    expect(pollDelay(20)).toBe(15_000);
  });

  it("keeps polling after a failed refresh", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch } = setup([[doc("queued")], new Error(), [doc("ready")]]);
    expect(await badge("Queued")).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(pollDelay(0)));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(pollDelay(1)));

    expect(await badge("Ready")).toBeInTheDocument();
    expect(gets(fetch)).toBe(3);
  });

  it("deletes a document after a confirm step, and keeps focus in the panel", async () => {
    const { fetch, user, onTotal } = setup([[doc("ready")]]);
    await user.click(await screen.findByRole("button", { name: "Actions for Handbook.pdf" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetch.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Actions for Handbook.pdf" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete Handbook.pdf?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await vi.waitFor(() => {
      expect(screen.queryByText("Handbook.pdf")).toBeNull();
    });
    const [url, init] = fetch.mock.calls.find(([, i]) => i?.method === "DELETE") ?? [];
    expect((url as URL).href).toBe(
      `http://127.0.0.1:8000/v1/knowledge/documents/${doc("ready").doc_id}`,
    );
    expect(init?.method).toBe("DELETE");
    await vi.waitFor(() => {
      expect(screen.getByRole("heading", { name: /Documents in/ })).toHaveFocus();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Deleted 1 document.");
    expect(onTotal).toHaveBeenLastCalledWith(0);
  });

  it("deletes several selected documents at once", async () => {
    const second = {
      ...doc("ready"),
      doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c7",
      title: "b.md",
    };
    const third = {
      ...doc("failed", "no_text"),
      doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c8",
      title: "c.txt",
    };
    const { fetch, user } = setup([[doc("ready"), second, third]]);
    await user.click(await screen.findByRole("checkbox", { name: "Select Handbook.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select c.txt" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select all shown documents" })).toHaveProperty(
      "indeterminate",
      true,
    );

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete 2 documents?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await vi.waitFor(() => {
      expect(screen.queryByText("Handbook.pdf")).toBeNull();
    });
    expect(screen.queryByText("c.txt")).toBeNull();
    expect(screen.getByText("b.md")).toBeInTheDocument();
    const deleted = fetch.mock.calls
      .filter(([, i]) => i?.method === "DELETE")
      .map(([u]) => (u as URL).pathname.split("/").pop());
    expect(deleted).toEqual([doc("ready").doc_id, third.doc_id]);
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("selects every shown document, and clears the selection", async () => {
    const second = {
      ...doc("ready"),
      doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c7",
      title: "b.md",
    };
    const { user } = setup([[doc("ready"), second]]);
    await user.click(await screen.findByRole("checkbox", { name: "Select all shown documents" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear selection" }));

    expect(screen.queryByText("2 selected")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Select Handbook.pdf" })).not.toBeChecked();
  });

  it("drops a document another tab already deleted, and says so", async () => {
    const { user } = setup([[doc("ready")]], {
      remove: jsonResponse(404, { detail: "knowledge_document_not_found" }),
    });
    await user.click(await screen.findByRole("button", { name: "Actions for Handbook.pdf" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That document no longer exists.");
    expect(screen.queryByText("Handbook.pdf")).toBeNull();
  });

  it("keeps the confirm step open and says why when nothing could be deleted", async () => {
    const { user } = setup([[doc("ready")]], {
      remove: jsonResponse(403, { detail: "knowledge_access_denied" }),
    });
    await user.click(await screen.findByRole("button", { name: "Actions for Handbook.pdf" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    const confirm = screen.getByRole("alertdialog");
    expect(await within(confirm).findByRole("alert")).toHaveTextContent(
      "Your access to this knowledge base doesn't allow that.",
    );
    expect(screen.getByText("Handbook.pdf")).toBeInTheDocument();
  });

  it("asks the server to search, filter and sort, and offers to clear a search with no match", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch, user } = setup([[doc("ready")], [doc("ready")], [], [], [doc("ready")]]);
    await badge("Ready");
    const last = () => {
      const call = fetch.mock.calls.filter(([, i]) => i?.method === "GET").at(-1);
      return (call?.[0] as URL).searchParams;
    };

    await user.selectOptions(screen.getByLabelText("Sort by"), "Name");
    await vi.waitFor(() => {
      expect(last().get("sort")).toBe("name");
    });
    await user.selectOptions(screen.getByLabelText("Status"), "Failed");
    await vi.waitFor(() => {
      expect(last().get("status")).toBe("failed");
    });
    expect(await screen.findByText("No documents match")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search documents"), "hand");
    await act(() => vi.advanceTimersByTimeAsync(400));
    await vi.waitFor(() => {
      expect(last().get("q")).toBe("hand");
    });

    await user.click(screen.getByRole("button", { name: "Clear search and filters" }));
    await vi.waitFor(() => {
      expect(last().get("q")).toBeNull();
    });
    expect(last().get("status")).toBeNull();
    expect(await badge("Ready")).toBeInTheDocument();
  });

  it("shows more documents a page at a time", async () => {
    const many = (n: number, from = 0) =>
      Array.from({ length: n }, (_, i) => ({
        ...doc("ready"),
        doc_id: `7d1e2f3a-4b5c-4d6e-8f70-${String(from + i).padStart(12, "0")}`,
        title: `doc-${String(from + i)}.txt`,
      }));
    const fetch = vi.fn<typeof globalThis.fetch>((input) => {
      const offset = Number((input as URL).searchParams.get("offset"));
      return Promise.resolve(
        jsonResponse(200, { documents: many(offset === 0 ? 100 : 20, offset), total: 120 }),
      );
    });
    const user = userEvent.setup();
    render(
      <DocumentsPanel
        deps={{
          apiUrl: "http://127.0.0.1:8000",
          getAccessToken: () => "t",
          onSessionEnded: vi.fn(),
          fetch,
        }}
        base={{
          kb_id: KB,
          name: "Policies",
          processing: "hosted",
          language: "simple",
          created_at: "",
          access: "owner",
          document_count: null,
        }}
      />,
    );
    expect(await screen.findByText("Showing 100 of 120")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByText("doc-119.txt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("downloads a document's original file under its title", async () => {
    const created = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    const revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(this.download).toBe("Handbook.pdf");
    });
    const { fetch, user } = setup([[doc("ready")]]);
    await user.click(await screen.findByRole("button", { name: "Actions for Handbook.pdf" }));
    await user.click(screen.getByRole("menuitem", { name: "Download" }));

    await vi.waitFor(() => {
      expect(clicked).toHaveBeenCalledOnce();
    });
    const call = fetch.mock.calls.find(([u]) => (u as URL).pathname.endsWith("/file"));
    expect((call?.[0] as URL).pathname).toBe(`/v1/knowledge/documents/${doc("ready").doc_id}/file`);
    expect(created).toHaveBeenCalledOnce();
    await vi.waitFor(() => {
      expect(revoked).toHaveBeenCalledWith("blob:x");
    });
    vi.restoreAllMocks();
  });

  it("offers no upload, selection or delete on a base shared to read", async () => {
    const { user } = setup([[doc("ready")]], { access: "read" });
    await badge("Ready");

    expect(screen.getByText(/shared with you to read/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload files" })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Actions for Handbook.pdf" }));
    expect(screen.getByRole("menuitem", { name: "Download" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Delete" })).toBeNull();
  });

  it("has no accessibility violations", async () => {
    const { view } = setup([
      [
        doc("ready"),
        { ...doc("failed", "no_text"), doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c7" },
      ],
    ]);
    await badge("Ready");

    expect(await accessibilityViolations(view.container)).toEqual([]);
  });
});
