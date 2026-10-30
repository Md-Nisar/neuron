import { describe, expect, it } from "vitest";

import { bytes, collect, controlledStream, streamOf } from "@/test/sse";

import { parseSse, SseLimitError } from "./sse";

const wire =
  ": heartbeat\r\n\r\n" +
  'event: token\r\ndata: {"text":"héllo 😀"}\r\n\r\n' +
  "event: final\r\ndata: line one\r\ndata: line two\r\n\r\n";

const expected = [
  { event: "token", data: '{"text":"héllo 😀"}' },
  { event: "final", data: "line one\nline two" },
];

describe("parseSse", () => {
  it("parses events, joins multi-line data and skips comment heartbeats", async () => {
    expect(await collect(parseSse(streamOf([wire])))).toEqual(expected);
  });

  it("gives the same result when the bytes are split at every possible point", async () => {
    const all = bytes(wire);
    for (let cut = 1; cut < all.length; cut += 1) {
      const chunks = [all.slice(0, cut), all.slice(cut)];
      expect(await collect(parseSse(streamOf(chunks)))).toEqual(expected);
    }
  });

  it("decodes characters split across chunks, one byte at a time", async () => {
    const oneByte = Array.from(bytes(wire), (byte) => new Uint8Array([byte]));
    expect(await collect(parseSse(streamOf(oneByte)))).toEqual(expected);
  });

  it.each([
    ["LF", "\n"],
    ["CRLF", "\r\n"],
    ["CR", "\r"],
  ])("accepts %s line endings", async (_name, eol) => {
    const text = `event: token${eol}data: x${eol}${eol}`;
    expect(await collect(parseSse(streamOf([text])))).toEqual([{ event: "token", data: "x" }]);
  });

  it("treats a CRLF split between chunks as one line ending", async () => {
    const chunks = ["event: token\r", "\ndata: x\r", "\n\r", "\n"];
    expect(await collect(parseSse(streamOf(chunks)))).toEqual([{ event: "token", data: "x" }]);
  });

  it("defaults the event name, ignores id and retry, and accepts fields without a space", async () => {
    const text = "id: 7\nretry: 1000\ndata:no-space\n\n";
    expect(await collect(parseSse(streamOf([text])))).toEqual([
      { event: "message", data: "no-space" },
    ]);
  });

  it("does not dispatch an event with no data lines", async () => {
    expect(await collect(parseSse(streamOf(["event: token\n\n"])))).toEqual([]);
  });

  it("drops an event that never got its terminating blank line", async () => {
    const text = "event: a\ndata: 1\n\nevent: b\ndata: 2\n";
    expect(await collect(parseSse(streamOf([text])))).toEqual([{ event: "a", data: "1" }]);
  });

  it("refuses an event larger than the limit", async () => {
    const text = `data: ${"x".repeat(100)}\ndata: ${"y".repeat(100)}\n\n`;
    await expect(collect(parseSse(streamOf([text]), { maxEventChars: 150 }))).rejects.toThrow(
      SseLimitError,
    );
  });

  it("refuses a line that never ends", async () => {
    const chunks = Array.from({ length: 5 }, () => "x".repeat(100));
    await expect(collect(parseSse(streamOf(chunks), { maxEventChars: 250 }))).rejects.toThrow(
      SseLimitError,
    );
  });

  it("ends quietly and cancels the reader when the signal aborts", async () => {
    let cancelled = false;
    const { stream, push } = controlledStream(() => {
      cancelled = true;
    });
    const controller = new AbortController();
    const seen: string[] = [];
    const run = (async () => {
      for await (const message of parseSse(stream, { signal: controller.signal })) {
        seen.push(message.data);
        controller.abort();
      }
    })();
    push("data: first\n\n");
    await run;
    expect(seen).toEqual(["first"]);
    expect(cancelled).toBe(true);
  });

  it("propagates a stream error", async () => {
    const boom = new Error("connection reset");
    await expect(collect(parseSse(streamOf(["data: a\n\n"], boom)))).rejects.toBe(boom);
  });
});
