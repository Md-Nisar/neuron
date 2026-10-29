import { Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** The row under a finished answer: copy its text, plus whatever else the page adds (ratings). */
export function MessageActions({ text, children }: { text: string; children?: ReactNode }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => {
      setCopied(false);
    }, 2000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [copied]);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Clipboard blocked (permissions, insecure context): nothing to undo.
    }
  }

  return (
    <div className="-ml-1.5 flex flex-wrap items-center gap-0.5 text-muted-foreground">
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        aria-label={copied ? "Copied" : "Copy answer"}
        title={copied ? "Copied" : "Copy answer"}
        onClick={() => void copy()}
      >
        {copied ? <Check /> : <Copy />}
      </Button>
      {children}
    </div>
  );
}
