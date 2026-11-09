import { describe, expect, it } from "vitest";

import { parseErasure, parseExportPage, parseMemories } from "./parse";

const memory = { id: "mem-1", text: "likes tea", created_at: "2026-10-01T10:00:00Z" };

describe("parseMemories", () => {
  it("accepts a page", () => {
    expect(parseMemories({ memories: [memory], total: 1, limit: 50, offset: 0 })).toEqual({
      memories: [memory],
      total: 1,
    });
  });

  it.each([
    ["not an object", []],
    ["no memories list", { total: 1 }],
    ["a text that is not a string", { memories: [{ ...memory, text: 5 }], total: 1 }],
    ["a negative total", { memories: [], total: -1 }],
    ["a fractional total", { memories: [], total: 1.5 }],
    ["an id that could escape a URL path", { memories: [{ ...memory, id: ".." }], total: 1 }],
    ["an id with a slash", { memories: [{ ...memory, id: "a/b" }], total: 1 }],
  ])("rejects %s", (_name, body) => {
    expect(() => parseMemories(body)).toThrow(TypeError);
  });
});

describe("parseExportPage", () => {
  const thread = {
    thread_id: "t1",
    created_at: "a",
    updated_at: "b",
    message_total: 1,
    messages: [{ role: "user", content: "hi" }],
  };

  it("accepts a page, with or without memories and tool calls", () => {
    const page = parseExportPage({ threads: [thread], total_threads: 1, has_more_messages: false });
    expect(page.memories).toEqual([]);
    const withTools = parseExportPage({
      threads: [
        { ...thread, messages: [{ role: "assistant", content: "", tool_calls: [{ name: "x" }] }] },
      ],
      total_threads: 1,
      has_more_messages: true,
      memories: [memory],
    });
    expect(withTools.threads[0]?.messages[0]?.tool_calls).toEqual([{ name: "x" }]);
    expect(withTools.has_more_messages).toBe(true);
  });

  const base = {
    kb_id: "kb-1",
    name: "Taxes",
    processing: "hosted",
    created_at: "a",
    documents: [
      {
        doc_id: "d-1",
        kb_id: "kb-1",
        title: "Return 2025",
        mime_type: "application/pdf",
        size_bytes: 2048,
        page_count: null,
        status: "failed",
        error_code: "parser_failed",
        created_at: "a",
        updated_at: "b",
      },
    ],
  };

  it("accepts the knowledge listing, and a page without one from an older server", () => {
    const page = parseExportPage({
      threads: [],
      total_threads: 0,
      has_more_messages: false,
      knowledge_bases: [base],
    });
    expect(page.knowledge_bases[0]?.documents[0]).toEqual({
      doc_id: "d-1",
      title: "Return 2025",
      mime_type: "application/pdf",
      size_bytes: 2048,
      page_count: null,
      status: "failed",
      error_code: "parser_failed",
      created_at: "a",
      updated_at: "b",
    });
    expect(
      parseExportPage({ threads: [], total_threads: 0, has_more_messages: false }).knowledge_bases,
    ).toEqual([]);
  });

  it.each([
    ["knowledge that is not a list", { knowledge_bases: {} }],
    ["a base without documents", { knowledge_bases: [{ ...base, documents: undefined }] }],
    [
      "a document with a negative size",
      { knowledge_bases: [{ ...base, documents: [{ ...base.documents[0], size_bytes: -1 }] }] },
    ],
  ])("rejects %s", (_name, extra) => {
    expect(() =>
      parseExportPage({ threads: [], total_threads: 0, has_more_messages: false, ...extra }),
    ).toThrow(TypeError);
  });

  it.each([
    ["no has_more_messages", { threads: [thread], total_threads: 1 }],
    [
      "a message without content",
      {
        threads: [{ ...thread, messages: [{ role: "user" }] }],
        total_threads: 1,
        has_more_messages: false,
      },
    ],
    ["a bad total", { threads: [], total_threads: "1", has_more_messages: false }],
  ])("rejects %s", (_name, body) => {
    expect(() => parseExportPage(body)).toThrow(TypeError);
  });
});

describe("parseErasure", () => {
  it("accepts a result", () => {
    expect(
      parseErasure({
        erased_count: 2,
        skipped_busy_count: 0,
        erased_memory_count: 3,
        complete: true,
      }),
    ).toEqual({
      erased_count: 2,
      skipped_busy_count: 0,
      erased_memory_count: 3,
      knowledge: null,
      complete: true,
    });
  });

  it("reads the knowledge part, pending while its files are being deleted", () => {
    const knowledge = { erased_base_count: 2, erased_document_count: 5, purge_pending: true };
    const result = parseErasure({
      erased_count: 0,
      skipped_busy_count: 0,
      erased_memory_count: 0,
      knowledge: { ...knowledge, complete: false },
      complete: false,
    });
    expect(result.knowledge).toEqual(knowledge);
    expect(() =>
      parseErasure({
        erased_count: 0,
        skipped_busy_count: 0,
        erased_memory_count: 0,
        knowledge: { erased_base_count: 2, erased_document_count: 5 },
        complete: false,
      }),
    ).toThrow(TypeError);
  });

  it("rejects a result that does not say whether it is complete", () => {
    expect(() =>
      parseErasure({ erased_count: 2, skipped_busy_count: 0, erased_memory_count: 0 }),
    ).toThrow(TypeError);
  });
});
