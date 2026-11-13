import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/request";
import { jsonResponse } from "@/test/sse";

import {
  createBase,
  deleteBase,
  listBases,
  listDocuments,
  renameBase,
  uploadDocument,
} from "./api";

const KB = "0b6f1c1e-6c8e-4c36-9d2b-6a1f2f3e4d5c";
const DOC = "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c6";
const base = {
  kb_id: KB,
  name: "Policies",
  processing: "hosted",
  language: "simple",
  created_at: "2026-11-01",
  access: "owner",
};
const doc = { doc_id: DOC, kb_id: KB, title: "a.pdf", size_bytes: 1, page_count: null };
const queued = { ...doc, status: "queued", error_code: null };

function deps(response: Response) {
  const fetch = vi.fn<typeof globalThis.fetch>(() => Promise.resolve(response));
  return {
    deps: {
      apiUrl: "http://127.0.0.1:8000",
      getAccessToken: () => "tok-1",
      onSessionEnded: vi.fn(),
      fetch,
    },
    fetch,
  };
}

function sent(fetch: ReturnType<typeof deps>["fetch"]) {
  const [url, init] = fetch.mock.calls[0] ?? [];
  return { url: url instanceof URL ? url.pathname + url.search : "", init };
}

describe("knowledge API", () => {
  it("calls each route with its method", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((input, init) => {
      const path = input instanceof URL ? input.pathname : "";
      if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 202 }));
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(200, { documents: [queued], total: 1 }));
      return Promise.resolve(jsonResponse(200, init?.method === "GET" ? { bases: [base] } : base));
    });
    const d = { ...deps(new Response()).deps, fetch };

    await listBases(d);
    await createBase(d, "Policies", "self_hosted");
    await renameBase(d, KB, "New");
    await deleteBase(d, KB);
    await listDocuments(d, KB, 50);

    const sentCalls = fetch.mock.calls.map(([url, init]) =>
      url instanceof URL ? `${init?.method ?? ""} ${url.pathname}${url.search}` : "",
    );
    expect(JSON.parse(fetch.mock.calls[1]?.[1]?.body as string)).toEqual({
      name: "Policies",
      processing: "self_hosted",
      language: "simple",
    });
    expect(sentCalls).toEqual([
      "GET /v1/knowledge/bases",
      "POST /v1/knowledge/bases",
      `PATCH /v1/knowledge/bases/${KB}`,
      `DELETE /v1/knowledge/bases/${KB}`,
      `GET /v1/knowledge/bases/${KB}/documents?limit=50&offset=50`,
    ]);
  });

  it("uploads the file as multipart with its idempotency key and the token in a header", async () => {
    const { deps: d, fetch } = deps(
      jsonResponse(202, { doc_id: DOC, kb_id: KB, status: "queued", status_url: "/x" }),
    );
    const file = new File(["%PDF-1.7"], "Handbook.pdf", { type: "application/pdf" });

    const accepted = await uploadDocument(d, KB, file, "key-1");

    const { url, init } = sent(fetch);
    expect(url).toBe(`/v1/knowledge/bases/${KB}/documents`);
    expect(accepted).toEqual({ doc_id: DOC, kb_id: KB, status: "queued" });
    const form = init?.body;
    expect(form).toBeInstanceOf(FormData);
    expect((form as FormData).get("file")).toBeInstanceOf(File);
    expect(init?.headers).toMatchObject({
      Authorization: "Bearer tok-1",
      "Idempotency-Key": "key-1",
    });
    // The browser writes the multipart boundary; a JSON content type would break the upload.
    expect(init?.headers).not.toHaveProperty("Content-Type");
  });

  it("keeps the server's quota code", async () => {
    const quota = deps(jsonResponse(413, { detail: "byte_quota_exceeded" }));
    const error = await uploadDocument(quota.deps, KB, new File(["x"], "a.txt"), "k").catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("byte_quota_exceeded");
  });
});
