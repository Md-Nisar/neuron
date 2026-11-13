import { describe, expect, it } from "vitest";

import { parseAccepted, parseBases, parseDocuments } from "./parse";

const KB = "0b6f1c1e-6c8e-4c36-9d2b-6a1f2f3e4d5c";
const DOC = "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c6";
const base = {
  kb_id: KB,
  name: "Policies",
  processing: "hosted",
  language: "simple",
  created_at: "2026-11-01T10:00:00Z",
  access: "owner",
};
const doc = {
  doc_id: DOC,
  kb_id: KB,
  title: "Handbook.pdf",
  size_bytes: 1024,
  page_count: null,
  status: "queued",
  error_code: null,
};

describe("parseBases", () => {
  it("accepts the list", () => {
    expect(parseBases({ bases: [base] })).toEqual([base]);
  });

  it.each([
    ["not an object", []],
    ["no bases list", {}],
    ["an unknown processing value", { bases: [{ ...base, processing: "cloud" }] }],
    ["an id that is not a UUID", { bases: [{ ...base, kb_id: "../x" }] }],
    ["a name that is not a string", { bases: [{ ...base, name: 5 }] }],
  ])("rejects %s", (_name, body) => {
    expect(() => parseBases(body)).toThrow(TypeError);
  });
});

describe("parseDocuments", () => {
  it("accepts a page", () => {
    const page = { documents: [doc, { ...doc, page_count: 3 }], total: 2, limit: 50, offset: 0 };
    expect(parseDocuments(page)).toEqual({ documents: [doc, { ...doc, page_count: 3 }], total: 2 });
  });

  it("keeps a stable error code and drops anything else", () => {
    const failed = (error_code: unknown) =>
      parseDocuments({ documents: [{ ...doc, status: "failed", error_code }], total: 1 })
        .documents[0]?.error_code;

    expect(failed("encrypted_pdf")).toBe("encrypted_pdf");
    expect(failed("Traceback (most recent call last): /srv/app.py")).toBeNull();
    expect(failed(42)).toBeNull();
  });

  it.each([
    ["an unknown status", { documents: [{ ...doc, status: "deleting" }], total: 1 }],
    ["a negative size", { documents: [{ ...doc, size_bytes: -1 }], total: 1 }],
    ["a fractional page count", { documents: [{ ...doc, page_count: 1.5 }], total: 1 }],
    [
      "a document id that could escape a path",
      { documents: [{ ...doc, doc_id: "a/b" }], total: 1 },
    ],
    ["no total", { documents: [doc] }],
  ])("rejects %s", (_name, body) => {
    expect(() => parseDocuments(body)).toThrow(TypeError);
  });
});

describe("parseAccepted", () => {
  it("accepts an upload response and ignores the status URL", () => {
    expect(
      parseAccepted({ doc_id: DOC, kb_id: KB, status: "queued", status_url: "https://x/y" }),
    ).toEqual({ doc_id: DOC, kb_id: KB, status: "queued" });
  });
});
