import { Library } from "lucide-react";
import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { displaySafe } from "@/features/chat/displaySafe";
import { characterCount } from "@/features/chat/limits";
import type { DataDeps } from "@/features/data/api";

import { createBase, listBases } from "./api";
import { knowledgeErrorText, NAME_MAX_CHARS, PROCESSING_TEXT } from "./messages";
import type { KnowledgeBase, Processing } from "./parse";

const nameProblem = (name: string): string | null =>
  name === "" || characterCount(name) > NAME_MAX_CHARS
    ? `Use 1 to ${String(NAME_MAX_CHARS)} characters.`
    : null;

/** The user's knowledge bases (RAG-06.01). */
export function KnowledgeScreen({ deps }: { deps: DataDeps }) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [processing, setProcessing] = useState<Processing>("hosted");
  const busy = useRef(false);

  useEffect(() => {
    let mounted = true;
    listBases(deps).then(
      (found) => {
        if (!mounted) return;
        setBases(found);
        setLoaded(true);
      },
      (failure: unknown) => {
        if (!mounted) return;
        setError(knowledgeErrorText(failure));
        setLoaded(true);
      },
    );
    return () => {
      mounted = false;
    };
    // Load once when the screen appears; `deps` is stable for the life of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** One change at a time: a second click while the first is in flight does nothing. */
  async function run(action: () => Promise<void>): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    try {
      await action();
      setError(null);
    } catch (failure) {
      setError(knowledgeErrorText(failure));
    } finally {
      busy.current = false;
    }
  }

  function create(event: SubmitEvent<HTMLFormElement>): void {
    event.preventDefault();
    const wanted = name.trim();
    const problem = nameProblem(wanted);
    if (problem !== null) {
      setError(problem);
      return;
    }
    void run(async () => {
      const made = await createBase(deps, wanted, processing);
      setBases((current) => [...current, made]);
      setName("");
    });
  }

  return (
    <section
      aria-label="Knowledge"
      className="mx-auto w-full max-w-3xl animate-in space-y-6 px-4 py-8 duration-300 fade-in-0"
    >
      <div>
        <p className="text-2xl font-semibold tracking-tight">Knowledge</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload your own documents so the assistant can answer from them. Only you can see them.
        </p>
      </div>
      <Card asSection aria-labelledby="bases-heading" className="gap-4">
        <CardHeader>
          <h2 id="bases-heading" className="flex items-center gap-2 font-semibold">
            <Library aria-hidden="true" className="size-4 text-muted-foreground" />
            Knowledge bases
          </h2>
          <CardDescription>
            Group documents by topic. Questions can use any of them.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error !== null && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <form onSubmit={create} className="space-y-3 rounded-lg border p-4">
            <label className="block text-sm font-medium" htmlFor="kb-name">
              New knowledge base
            </label>
            <Input
              id="kb-name"
              value={name}
              placeholder="Name, for example Policies"
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Where its text is processed</legend>
              {(Object.keys(PROCESSING_TEXT) as Processing[]).map((option) => (
                <label key={option} className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="kb-processing"
                    className="mt-1"
                    checked={processing === option}
                    onChange={() => {
                      setProcessing(option);
                    }}
                  />
                  <span>
                    <span className="font-medium">{PROCESSING_TEXT[option].label}.</span>{" "}
                    <span className="text-muted-foreground">{PROCESSING_TEXT[option].detail}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            <Button type="submit" size="sm">
              Create
            </Button>
          </form>
          {!loaded && (
            <div className="space-y-2">
              <p className="sr-only">Loading…</p>
              <Skeleton className="h-14 w-full" />
            </div>
          )}
          {loaded && error === null && bases.length === 0 && (
            <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
              No knowledge bases yet.
            </p>
          )}
          <ul aria-label="Your knowledge bases" className="divide-y rounded-lg border empty:hidden">
            {bases.map((base) => (
              <li key={base.kb_id} className="flex items-center gap-3 px-4 py-3">
                <p className="min-w-0 flex-1 truncate text-sm font-medium">
                  {displaySafe(base.name)}
                </p>
                <Badge variant="secondary">{PROCESSING_TEXT[base.processing].label}</Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}
