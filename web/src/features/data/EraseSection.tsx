import { useState } from "react";

import { eraseAllData, type DataDeps } from "./api";
import { dataErrorText, ERASE_PHRASE } from "./messages";
import type { Erasure } from "./parse";

/**
 * Erase all of the caller's conversations and memories. Needs the typed phrase. Signs the user
 * out only when the server reports the erase complete; if a conversation was busy and skipped,
 * the user stays signed in to repeat it.
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
    <section aria-labelledby="erase-heading" className="mt-6 rounded border-2 p-3">
      <h2 id="erase-heading" className="text-lg font-semibold">
        Erase your data
      </h2>
      <p className="text-sm">
        This permanently deletes all of your conversations and memories. It cannot be undone, and
        you will be signed out.
      </p>
      <label htmlFor="erase-confirm" className="mt-2 block text-sm">
        Type <strong>{ERASE_PHRASE}</strong> to confirm
      </label>
      <input
        id="erase-confirm"
        type="text"
        autoComplete="off"
        value={typed}
        className="mt-1 w-full rounded border p-2"
        onChange={(event) => {
          setTyped(event.target.value);
        }}
      />
      <button
        type="button"
        className="mt-2 rounded border px-3 py-1"
        disabled={!armed || busy}
        onClick={() => void erase()}
      >
        {busy ? "Erasing…" : "Erase all my data"}
      </button>
      {error !== null && (
        <p role="alert" className="mt-2">
          {error}
        </p>
      )}
      {result !== null && (
        <p role="status" aria-live="polite" className="mt-2">
          {result.complete
            ? `Erased ${String(result.erased_count)} conversations and ${String(result.erased_memory_count)} memories. Signing you out…`
            : `Erased ${String(result.erased_count)} conversations. ${String(result.skipped_busy_count)} could not be erased because a reply was still running. Try again in a moment.`}
        </p>
      )}
    </section>
  );
}
