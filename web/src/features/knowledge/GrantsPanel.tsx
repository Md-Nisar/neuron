import { X } from "lucide-react";
import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { displaySafe } from "@/features/chat/displaySafe";
import { characterCount } from "@/features/chat/limits";
import type { DataDeps } from "@/features/data/api";
import { ApiError } from "@/lib/request";

import { getGrants, setGrants } from "./api";
import { ACCESS_TEXT, knowledgeErrorText } from "./messages";
import type { Grant, GrantAccess, KnowledgeBase } from "./parse";

/** The server's bounds (`schemas/knowledge.py`): role length and grants per base. */
export const ROLE_MAX_CHARS = 200;
export const MAX_GRANTS = 50;

const LEVELS = Object.keys(ACCESS_TEXT) as GrantAccess[];
const SELECT =
  "h-8 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

function grantErrorText(error: unknown): string {
  if (error instanceof ApiError && error.kind === "invalid_request")
    return `That role can't be used. Use 1 to ${String(ROLE_MAX_CHARS)} visible characters.`;
  return knowledgeErrorText(error);
}

/**
 * Who a base is shared with (RAG-09.03), for its owner and `admin` roles. Each change is saved
 * at once as the whole list; a removed role loses its access from its next request.
 */
export function GrantsPanel({ deps, base }: { deps: DataDeps; base: KnowledgeBase }) {
  const [grants, setList] = useState<Grant[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [role, setRole] = useState("");
  const [access, setAccess] = useState<GrantAccess>("read");
  const busy = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const name = displaySafe(base.name);

  useEffect(() => {
    let mounted = true;
    getGrants(deps, base.kb_id).then(
      (found) => {
        if (mounted) setList(found);
      },
      (failure: unknown) => {
        if (mounted) setError(knowledgeErrorText(failure));
      },
    );
    return () => {
      mounted = false;
    };
    // `deps` is stable for the page; the panel is keyed by base.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base.kb_id]);

  /** One change at a time. Resolves true once the server stored the new list. */
  async function save(next: Grant[]): Promise<boolean> {
    if (busy.current) return false;
    busy.current = true;
    try {
      setList(await setGrants(deps, base.kb_id, next));
      setError(null);
      return true;
    } catch (failure) {
      setError(grantErrorText(failure));
      return false;
    } finally {
      busy.current = false;
    }
  }

  function add(event: SubmitEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (grants === null) return;
    const wanted = role.trim();
    const problem =
      wanted === "" || characterCount(wanted) > ROLE_MAX_CHARS
        ? `Use 1 to ${String(ROLE_MAX_CHARS)} characters.`
        : grants.some((grant) => grant.role === wanted)
          ? "That role already has access. Change it in the list."
          : grants.length >= MAX_GRANTS
            ? `A knowledge base can be shared with at most ${String(MAX_GRANTS)} roles.`
            : null;
    if (problem !== null) {
      setError(problem);
      return;
    }
    void save([...grants, { role: wanted, access }]).then((stored) => {
      if (stored) setRole("");
    });
  }

  return (
    <section aria-labelledby="sharing-heading" className="space-y-3">
      <h3
        id="sharing-heading"
        ref={heading}
        tabIndex={-1}
        className="truncate text-sm font-semibold outline-none"
      >
        Sharing {name}
      </h3>
      <p className="text-sm text-muted-foreground">
        People whose sign-in carries one of these roles get the access shown. A change counts from
        their next request.
      </p>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {LEVELS.map((level) => (
          <li key={level}>
            <span className="font-medium text-foreground">{ACCESS_TEXT[level].label}:</span>{" "}
            {ACCESS_TEXT[level].detail}
          </li>
        ))}
      </ul>
      {error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {grants === null && error === null && (
        <div>
          <p className="sr-only">Loading…</p>
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {grants?.length === 0 && (
        <p className="text-sm text-muted-foreground">Not shared with any role.</p>
      )}
      <ul
        aria-label={`Roles with access to ${name}`}
        className="divide-y rounded-lg border empty:hidden"
      >
        {grants?.map((grant) => {
          const label = displaySafe(grant.role);
          return (
            <li key={grant.role} className="flex flex-wrap items-center gap-2 px-4 py-2">
              <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
              <select
                aria-label={`Access for ${label}`}
                className={SELECT}
                value={grant.access}
                onChange={(event) => {
                  const level = event.target.value as GrantAccess;
                  void save(
                    grants.map((g) => (g.role === grant.role ? { ...g, access: level } : g)),
                  );
                }}
              >
                {LEVELS.map((level) => (
                  <option key={level} value={level}>
                    {ACCESS_TEXT[level].label}
                  </option>
                ))}
              </select>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                aria-label={`Stop sharing with ${label}`}
                className="hover:text-destructive"
                onClick={() => {
                  void save(grants.filter((g) => g.role !== grant.role)).then((stored) => {
                    // The row and its button are gone: keep focus in the section.
                    if (stored) heading.current?.focus();
                  });
                }}
              >
                <X />
              </Button>
            </li>
          );
        })}
      </ul>
      {grants !== null && (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2">
          <div className="min-w-40 flex-1 space-y-1">
            <label className="block text-sm font-medium" htmlFor="grant-role">
              Role
            </label>
            <Input
              id="grant-role"
              value={role}
              placeholder="For example finance"
              onChange={(event) => {
                setRole(event.target.value);
              }}
            />
          </div>
          <div className="space-y-1">
            <label className="block text-sm font-medium" htmlFor="grant-access">
              Access
            </label>
            <select
              id="grant-access"
              className={SELECT}
              value={access}
              onChange={(event) => {
                setAccess(event.target.value as GrantAccess);
              }}
            >
              {LEVELS.map((level) => (
                <option key={level} value={level}>
                  {ACCESS_TEXT[level].label}
                </option>
              ))}
            </select>
          </div>
          <Button type="submit" size="sm">
            Share
          </Button>
        </form>
      )}
    </section>
  );
}
