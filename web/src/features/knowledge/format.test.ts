import { describe, expect, it } from "vitest";

import { documentKind, downloadName, formatDate, formatSize, plural } from "./format";

describe("knowledge formatting", () => {
  it("says sizes in B, KB and MB", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(2048)).toBe("2 KB");
    expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });

  it("says Today and Yesterday, a date otherwise, and nothing for an unreadable time", () => {
    const now = new Date(2026, 10, 19, 15, 0);
    expect(formatDate(new Date(2026, 10, 19, 1, 0).toISOString(), now)).toBe("Today");
    expect(formatDate(new Date(2026, 10, 18, 23, 0).toISOString(), now)).toBe("Yesterday");
    expect(formatDate(new Date(2026, 10, 2, 9, 0).toISOString(), now)).toMatch(/2026/);
    expect(formatDate("not a time", now)).toBe("");
  });

  it("names a document's kind from its file name, or as a web page", () => {
    expect(documentKind({ title: "Plan.PDF", source_url: null })).toBe("PDF");
    expect(documentKind({ title: "notes.md", source_url: null })).toBe("Markdown");
    expect(documentKind({ title: "data", source_url: null })).toBe("File");
    expect(documentKind({ title: "Leave policy", source_url: "https://x.example/" })).toBe(
      "Web page",
    );
  });

  it("counts in the singular and the plural", () => {
    expect(plural(1, "document")).toBe("1 document");
    expect(plural(3, "document")).toBe("3 documents");
  });

  it("saves a download under a name with no control, bidi or path characters", () => {
    expect(downloadName("Leave policy.pdf")).toBe("Leave policy.pdf");
    expect(downloadName("Résumé 2026.docx")).toBe("Résumé 2026.docx");
    expect(downloadName("invoice\u202Efdp.exe")).toBe("invoice_fdp.exe");
    expect(downloadName("../../etc/passwd")).toBe("_.._etc_passwd");
    expect(downloadName("a\u0000b\nc")).toBe("a_b_c");
    expect(downloadName(" ... ")).toBe("download");
  });
});
