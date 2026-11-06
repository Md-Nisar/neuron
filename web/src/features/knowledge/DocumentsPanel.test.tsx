import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { DocumentsPanel, POLL_MS } from "./DocumentsPanel";
import { documentFailureText } from "./messages";
import type { Processing } from "./parse";

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

/** Each `GET` answers with the next list (the last one repeats); `POST` with `upload`. */
function setup(lists: unknown[][], options: { processing?: Processing; upload?: Response } = {}) {
  let call = 0;
  const fetch = vi.fn<typeof globalThis.fetch>((_input, init) => {
    if (init?.method === "POST")
      return Promise.resolve(
        options.upload ??
          jsonResponse(202, { doc_id: doc("queued").doc_id, kb_id: KB, status: "queued" }),
      );
    const documents = lists[Math.min(call++, lists.length - 1)] ?? [];
    return Promise.resolve(jsonResponse(200, { documents, total: documents.length }));
  });
  const base = {
    kb_id: KB,
    name: "Policies",
    processing: options.processing ?? "hosted",
    created_at: "",
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
    const { user } = setup([[]], { upload: jsonResponse(413, { detail: "byte_quota_exceeded" }) });

    await user.upload(screen.getByLabelText(/Drop files here/), new File(["x"], "notes.txt"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "notes.txt: You have used all your document storage. Delete documents to upload more.",
    );
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
