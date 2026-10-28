import { useRef, useState } from "react";

import type { DataDeps } from "./api";
import { buildExport, downloadText, exportFilename } from "./exportData";
import { dataErrorText } from "./messages";

type Status = "idle" | "working" | "done" | "failed";

/**
 * Download the caller's data as JSON. The component keeps only a status word: the data itself
 * lives in local variables of one click handler, goes to the browser as a file, and is dropped.
 */
export function ExportSection({ deps }: { deps: DataDeps }) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const working = useRef(false);

  async function download(): Promise<void> {
    if (working.current) return;
    working.current = true;
    setStatus("working");
    setError(null);
    try {
      downloadText(await buildExport(deps), exportFilename());
      setStatus("done");
    } catch (failure) {
      setError(dataErrorText(failure));
      setStatus("failed");
    } finally {
      working.current = false;
    }
  }

  return (
    <section aria-labelledby="export-heading" className="mt-6">
      <h2 id="export-heading" className="text-lg font-semibold">
        Export your data
      </h2>
      <p className="text-sm opacity-80">
        Download your conversations and memories as one JSON file. It is made in this page and is
        not kept after the download.
      </p>
      <button
        type="button"
        className="mt-2 rounded border px-3 py-1"
        disabled={status === "working"}
        onClick={() => void download()}
      >
        {status === "working" ? "Preparing…" : "Download my data"}
      </button>
      <p role="status" aria-live="polite" className="mt-1">
        {status === "done" ? "Your file was downloaded." : null}
      </p>
      {error !== null && (
        <p role="alert" className="mt-1">
          {error}
        </p>
      )}
    </section>
  );
}
