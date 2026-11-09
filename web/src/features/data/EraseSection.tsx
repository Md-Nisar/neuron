import { LoaderCircle, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { eraseAllData, type DataDeps } from "./api";
import { dataErrorText, ERASE_PHRASE } from "./messages";
import type { Erasure } from "./parse";

/** What an erase did, and what is left to do when it is not complete. */
function resultText(result: Erasure): string {
  const { knowledge } = result;
  const erased =
    knowledge === null
      ? `Erased ${String(result.erased_count)} conversations and ${String(result.erased_memory_count)} memories.`
      : `Erased ${String(result.erased_count)} conversations, ${String(result.erased_memory_count)} memories and ${String(knowledge.erased_base_count)} knowledge bases.`;
  if (result.complete) return `${erased} Signing you out…`;
  const left: string[] = [];
  if (result.skipped_busy_count > 0)
    left.push(
      `${String(result.skipped_busy_count)} could not be erased because a reply was still running.`,
    );
  if (knowledge?.purge_pending === true) left.push("Your knowledge files are still being deleted.");
  return `${erased} ${left.join(" ")} Try again in a moment to finish.`;
}

/**
 * Erase all of the caller's conversations, memories and knowledge. Needs the typed phrase. Signs
 * the user out only when the server reports the erase complete; if a conversation was busy, or
 * knowledge files are still being deleted, the user stays signed in to repeat it.
 */
export function EraseSection({ deps, onErased }: { deps: DataDeps; onErased: () => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Erasure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const armed = typed.trim().toLowerCase() === ERASE_PHRASE;

  async function erase(): Promise<void> {
    if (!armed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await eraseAllData(deps);
      setResult(outcome);
      setTyped("");
      if (outcome.complete) onErased();
    } catch (failure) {
      setError(dataErrorText(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card asSection aria-labelledby="erase-heading" className="gap-4 border-destructive/40">
      <CardHeader>
        <h2 id="erase-heading" className="flex items-center gap-2 font-semibold text-destructive">
          <TriangleAlert aria-hidden="true" className="size-4" />
          Erase your data
        </h2>
        <CardDescription>
          This permanently deletes all of your conversations, memories and knowledge bases with
          their files. It cannot be undone, and you will be signed out.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <label htmlFor="erase-confirm" className="block text-sm">
          Type <strong className="font-mono">{ERASE_PHRASE}</strong> to confirm
        </label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <Input
            id="erase-confirm"
            type="text"
            autoComplete="off"
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
          />
          <Button
            type="button"
            variant="destructive"
            className="shrink-0"
            disabled={!armed || busy}
            onClick={() => void erase()}
          >
            {busy ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
            {busy ? "Erasing…" : "Erase all my data"}
          </Button>
        </div>
        {error !== null && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        )}
        {result !== null && (
          <p role="status" aria-live="polite" className="mt-2 text-sm">
            {resultText(result)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
