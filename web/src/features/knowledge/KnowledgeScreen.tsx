import { Library } from "lucide-react";
import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { characterCount } from "@/features/chat/limits";
import type { DataDeps } from "@/features/data/api";
import { ApiError } from "@/lib/request";

import { createBase, deleteBase, listBases, renameBase } from "./api";
import { BaseRow } from "./BaseRow";
import { DocumentsPanel } from "./DocumentsPanel";
import { GrantsPanel } from "./GrantsPanel";
import { knowledgeErrorText, NAME_MAX_CHARS, PROCESSING_TEXT } from "./messages";
import type { KnowledgeBase, Processing } from "./parse";

const nameProblem = (name: string): string | null =>
  name === "" || characterCount(name) > NAME_MAX_CHARS
    ? `Use 1 to ${String(NAME_MAX_CHARS)} characters.`
    : null;

/** Without a Retry-After, a passing refusal of the list is tried again after this, this often. */
const RETRY_SECONDS = 5;
const RETRIES = 3;

/** The user's knowledge bases (RAG-06.01). */
export function KnowledgeScreen({ deps }: { deps: DataDeps }) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [processing, setProcessing] = useState<Processing>("hosted");
  const [openId, setOpenId] = useState<string | null>(null);
  const [retries, setRetries] = useState(0);
  const busy = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    let mounted = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    listBases(deps).then(
      (found) => {
        if (!mounted) return;
        setBases(found);
        if (retries > 0) setError(null);
        setLoaded(true);
      },
      (failure: unknown) => {
        if (!mounted) return;
        setError(knowledgeErrorText(failure));
        setLoaded(true);
        // A passing refusal (rate limit, a restart) is tried again after the server's
        // Retry-After, or the list would stay empty until the page is reloaded (UX-01).
        if (
          failure instanceof ApiError &&
          (failure.kind === "rate_limited" || failure.kind === "unavailable") &&
          retries < RETRIES
        )
          retry = setTimeout(
            () => {
              setRetries((n) => n + 1);
            },
            Math.max(1, failure.retryAfterSeconds ?? RETRY_SECONDS) * 1000,
          );
      },
    );
    return () => {
      mounted = false;
      clearTimeout(retry);
    };
    // Load when the screen appears, and again for each retry; `deps` is stable for the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retries]);

  /**
   * One change at a time: a second click while the first is in flight does nothing. Resolves
   * true when the change was made. A base that is already gone (another tab) leaves the list.
   */
  async function run(action: () => Promise<void>, kbId?: string): Promise<boolean> {
    if (busy.current) return false;
    busy.current = true;
    try {
      await action();
      setError(null);
      return true;
    } catch (failure) {
      setError(knowledgeErrorText(failure));
      if (failure instanceof ApiError && failure.code === "knowledge_base_not_found")
        setBases((current) => current.filter((b) => b.kb_id !== kbId));
      return false;
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
      setOpenId(made.kb_id);
      setName("");
    });
  }

  function rename(kbId: string, draft: string): Promise<boolean> {
    const wanted = draft.trim();
    const problem = nameProblem(wanted);
    if (problem !== null) {
      setError(problem);
      return Promise.resolve(false);
    }
    return run(async () => {
      const stored = await renameBase(deps, kbId, wanted);
      setBases((current) => current.map((b) => (b.kb_id === kbId ? stored : b)));
    }, kbId);
  }

  function remove(kbId: string): void {
    void run(async () => {
      await deleteBase(deps, kbId);
      // The row (and its buttons) are about to disappear: keep focus in the section.
      heading.current?.focus();
      setBases((current) => current.filter((b) => b.kb_id !== kbId));
    }, kbId);
  }

  return (
    <section
      aria-label="Knowledge"
      className="mx-auto w-full max-w-3xl animate-in space-y-6 px-4 py-8 duration-300 fade-in-0"
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload your own documents so the assistant can answer from them. Only you can see them,
          unless you share a knowledge base with a role.
        </p>
      </div>
      <Card asSection aria-labelledby="bases-heading" className="gap-4">
        <CardHeader>
          <h2
            id="bases-heading"
            ref={heading}
            tabIndex={-1}
            className="flex items-center gap-2 font-semibold outline-none"
          >
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
              <li key={base.kb_id} className="flex flex-wrap items-center gap-2 px-4 py-3">
                <BaseRow
                  base={base}
                  open={openId === base.kb_id}
                  onOpen={() => {
                    setOpenId(base.kb_id);
                  }}
                  onRename={(draft) => rename(base.kb_id, draft)}
                  onDelete={() => {
                    remove(base.kb_id);
                  }}
                />
              </li>
            ))}
          </ul>
          {bases
            .filter((base) => base.kb_id === openId)
            .map((base) => (
              <DocumentsPanel key={base.kb_id} deps={deps} base={base} />
            ))}
          {bases
            .filter((base) => base.kb_id === openId)
            .filter((base) => base.access === "owner" || base.access === "admin")
            .map((base) => (
              <GrantsPanel key={base.kb_id} deps={deps} base={base} />
            ))}
        </CardContent>
      </Card>
    </section>
  );
}
