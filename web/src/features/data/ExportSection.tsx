import { Download, LoaderCircle } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

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
    <Card asSection aria-labelledby="export-heading" className="gap-4">
      <CardHeader>
        <h2 id="export-heading" className="flex items-center gap-2 font-semibold">
          <Download aria-hidden="true" className="size-4 text-muted-foreground" />
          Export your data
        </h2>
        <CardDescription>
          Download your conversations and memories as one JSON file. It is made in this page and is
          not kept after the download.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          type="button"
          variant="outline"
          disabled={status === "working"}
          onClick={() => void download()}
        >
          {status === "working" ? <LoaderCircle className="animate-spin" /> : <Download />}
          {status === "working" ? "Preparing…" : "Download my data"}
        </Button>
        <p
          role="status"
          aria-live="polite"
          className="mt-2 text-sm text-muted-foreground empty:mt-0"
        >
          {status === "done" ? "Your file was downloaded." : null}
        </p>
        {error !== null && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
