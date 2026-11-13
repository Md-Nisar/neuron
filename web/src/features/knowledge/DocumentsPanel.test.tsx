import { act, render, screen } from "@testing-library/react";
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
});

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
    />,
  );
  return { fetch, user, view };
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

  it("shows an uploaded PDF as queued, then as ready, without a reload", async () => {
    // Real time still passes (for the queries' own waits); the polls are driven by hand.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch, user } = setup([[], [doc("queued")], [doc("ready")]]);
    const pdf = new File(["%PDF-1.7"], "Handbook.pdf", { type: "application/pdf" });

    await user.upload(screen.getByLabelText(/Drop files here/), pdf);

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    const post = fetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect((post?.[1]?.body as FormData).get("file")).toBeInstanceOf(File);
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(await screen.findByText("Ready")).toBeInTheDocument();

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

    await user.upload(screen.getByLabelText(/Drop files here/), new File(["x"], "notes.txt"));

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

    await user.upload(screen.getByLabelText(/Drop files here/), [
      new File(["x"], "a.md"),
      new File(["x"], "b.txt"),
      new File(["x"], "c.pdf"),
    ]);

    const alert = await screen.findByRole("alert");
    await vi.waitFor(() => {
      expect(alert).toHaveTextContent(/c\.pdf: The file is too large/);
    });
    expect(alert).toHaveTextContent(/a\.md: This file type isn't supported/);
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(gets(fetch)).toBeGreaterThanOrEqual(2);
  });

  it("waits longer between polls while a document is still processing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch } = setup([[doc("embedding")]]);
    expect(await screen.findByText("Indexing")).toBeInTheDocument();

    // Twenty seconds of polling make six requests, not the eleven a fixed 2 s would.
    for (let second = 0; second < 20; second++) await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(gets(fetch)).toBeLessThanOrEqual(6);
    expect(pollDelay(0)).toBe(POLL_MS);
    expect(pollDelay(20)).toBe(15_000);
  });

  it("keeps polling after a failed refresh", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch } = setup([[doc("queued")], new Error(), [doc("ready")]]);
    expect(await screen.findByText("Queued")).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(pollDelay(0)));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(pollDelay(1)));

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(gets(fetch)).toBe(3);
  });

  it("deletes a document after a confirm step, and keeps focus in the panel", async () => {
    const { fetch, user } = setup([[doc("ready")]]);
    await user.click(await screen.findByRole("button", { name: "Delete Handbook.pdf" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Delete Handbook.pdf" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Delete Handbook.pdf" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete Handbook.pdf" }));

    await vi.waitFor(() => {
      expect(screen.queryByText("Handbook.pdf")).toBeNull();
    });
    const [url, init] = fetch.mock.calls.find(([, i]) => i?.method === "DELETE") ?? [];
    expect((url as URL).href).toBe(
      `http://127.0.0.1:8000/v1/knowledge/documents/${doc("ready").doc_id}`,
    );
    expect(init?.method).toBe("DELETE");
    expect(screen.getByRole("heading", { name: /Documents in/ })).toHaveFocus();
  });

  it("drops a document another tab already deleted, and says so", async () => {
    const { user } = setup([[doc("ready")]], {
      remove: jsonResponse(404, { detail: "knowledge_document_not_found" }),
    });
    await user.click(await screen.findByRole("button", { name: "Delete Handbook.pdf" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete Handbook.pdf" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That document no longer exists.");
    expect(screen.queryByText("Handbook.pdf")).toBeNull();
  });

  it("has no accessibility violations", async () => {
    const { view } = setup([
      [
        doc("ready"),
        { ...doc("failed", "no_text"), doc_id: "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c7" },
      ],
    ]);
    await screen.findByText("Ready");

    expect(await accessibilityViolations(view.container)).toEqual([]);
  });
});
