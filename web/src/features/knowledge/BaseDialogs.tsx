import { useRef, useState, type ReactNode, type SubmitEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { characterCount } from "@/features/chat/limits";
import { cn } from "@/lib/utils";

import { languageLabel, NAME_MAX_CHARS, PROCESSING_TEXT } from "./messages";
import { LANGUAGES, type Language, type Processing } from "./parse";

export const SELECT =
  "h-9 rounded-md border border-input bg-background px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30";

export const nameProblem = (name: string): string | null =>
  name === "" || characterCount(name) > NAME_MAX_CHARS
    ? `Use 1 to ${String(NAME_MAX_CHARS)} characters.`
    : null;

/** Resolves with why the change was refused, or null once it is made. */
export type Attempt = Promise<string | null>;

function FormError({ id, error }: { id: string; error: string | null }) {
  return error === null ? null : (
    <p id={id} role="alert" className="text-sm text-destructive">
      {error}
    </p>
  );
}

function useAttempt(onDone: () => void) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function attempt(action: () => Attempt): Promise<void> {
    if (busy) return;
    setBusy(true);
    const refused = await action();
    setBusy(false);
    setError(refused);
    if (refused === null) onDone();
  }
  return { error, setError, busy, attempt };
}

/** A new knowledge base: its name, where its text is processed and its language. */
export function CreateBaseDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string, processing: Processing, language: Language) => Attempt;
}) {
  const [name, setName] = useState("");
  const [processing, setProcessing] = useState<Processing>("hosted");
  const [language, setLanguage] = useState<Language>("simple");
  // The new base's page takes focus; the button that opened this dialog is gone by then.
  const made = useRef(false);
  const { error, setError, busy, attempt } = useAttempt(() => {
    made.current = true;
    setName("");
    setProcessing("hosted");
    setLanguage("simple");
    onOpenChange(false);
  });

  function submit(event: SubmitEvent<HTMLFormElement>): void {
    event.preventDefault();
    const wanted = name.trim();
    const problem = nameProblem(wanted);
    if (problem !== null) {
      setError(problem);
      return;
    }
    void attempt(() => onCreate(wanted, processing, language));
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent
        onCloseAutoFocus={(event) => {
          if (made.current) event.preventDefault();
          made.current = false;
        }}
      >
        <DialogHeader>
          <DialogTitle>New knowledge base</DialogTitle>
          <DialogDescription>
            Group documents by topic. The assistant can answer from any of them.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5" noValidate>
          <div className="space-y-1.5">
            <label className="block text-sm font-medium" htmlFor="kb-name">
              Name
            </label>
            <Input
              id="kb-name"
              autoFocus
              value={name}
              aria-invalid={error !== null}
              aria-describedby={error === null ? undefined : "kb-create-error"}
              placeholder="For example Policies"
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </div>
          <fieldset className="space-y-2">
            <legend className="mb-1.5 text-sm font-medium">Where its text is processed</legend>
            {(Object.keys(PROCESSING_TEXT) as Processing[]).map((option) => (
              <label
                key={option}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50",
                  processing === option
                    ? "border-foreground/40 bg-accent/60"
                    : "hover:bg-accent/40",
                )}
              >
                <input
                  type="radio"
                  name="kb-processing"
                  className="mt-0.5 accent-foreground"
                  checked={processing === option}
                  onChange={() => {
                    setProcessing(option);
                  }}
                />
                <span>
                  <span className="block font-medium">{PROCESSING_TEXT[option].label}</span>
                  <span className="text-muted-foreground">{PROCESSING_TEXT[option].detail}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="space-y-1.5">
            <label className="block text-sm font-medium" htmlFor="kb-language">
              Language of its documents
            </label>
            <select
              id="kb-language"
              aria-describedby="kb-language-help"
              className={cn(SELECT, "w-full")}
              value={language}
              onChange={(event) => {
                setLanguage(event.target.value as Language);
              }}
            >
              {LANGUAGES.map((option) => (
                <option key={option} value={option}>
                  {languageLabel(option)}
                </option>
              ))}
            </select>
            <p id="kb-language-help" className="text-xs text-muted-foreground">
              Word search matches other forms of a word in that language. It can&apos;t be changed
              later.
            </p>
          </div>
          <FormError id="kb-create-error" error={error} />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A new name for a base; opens with the current one selected. */
export function RenameBaseDialog({
  name,
  open,
  onOpenChange,
  onRename,
}: {
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRename: (name: string) => Attempt;
}) {
  const [draft, setDraft] = useState(name);
  const { error, setError, busy, attempt } = useAttempt(() => {
    onOpenChange(false);
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setDraft(name);
        else setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename knowledge base</DialogTitle>
          <DialogDescription>People it is shared with see the new name too.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            const wanted = draft.trim();
            const problem = nameProblem(wanted);
            if (problem !== null) setError(problem);
            else void attempt(() => onRename(wanted));
          }}
        >
          <div className="space-y-1.5">
            <label className="block text-sm font-medium" htmlFor="kb-rename">
              Name
            </label>
            <Input
              id="kb-rename"
              autoFocus
              onFocus={(event) => {
                event.currentTarget.select();
              }}
              value={draft}
              aria-invalid={error !== null}
              aria-describedby={error === null ? undefined : "kb-rename-error"}
              onChange={(event) => {
                setDraft(event.target.value);
              }}
            />
          </div>
          <FormError id="kb-rename-error" error={error} />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A destructive step that needs a second, explicit click. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  onConfirm,
  onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => Attempt;
  /** Where focus goes once it closes, when the control that opened it is gone. */
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const { error, setError, busy, attempt } = useAttempt(() => {
    onOpenChange(false);
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent role="alertdialog" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div>{children}</div>
          </DialogDescription>
        </DialogHeader>
        <FormError id="confirm-error" error={error} />
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            autoFocus
            onClick={() => {
              onOpenChange(false);
            }}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={busy}
            onClick={() => {
              void attempt(onConfirm);
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
