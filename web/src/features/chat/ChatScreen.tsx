import {
  ArrowUp,
  Calculator,
  CircleAlert,
  Clock,
  Lightbulb,
  LoaderCircle,
  PenLine,
  RotateCcw,
  ShieldAlert,
  Square,
  SquarePen,
  Wrench,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type SubmitEvent,
} from "react";

import { Logo } from "@/components/Logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { DataDeps } from "@/features/data/api";
import type { Decision } from "@/lib/stream";
import { cn } from "@/lib/utils";

import { ApprovalCard } from "./ApprovalCard";
import type { ChatMessage } from "./chatState";
import { displaySafe } from "./displaySafe";
import { FeedbackBar } from "./FeedbackBar";
import { characterCount, checkDraft, type DraftProblem } from "./limits";
import { Markdown } from "./Markdown";
import { MessageActions } from "./MessageActions";
import { draftProblemText, failureText, openFailureText } from "./messages";
import { useChat, type ChatDeps } from "./useChat";

const SKIPPED_TEXT = {
  pending: "Waiting for approval",
  rejected: "You rejected",
  failed: "Could not run",
} as const;

/** Starting points for an empty conversation. They only fill the composer; nothing is sent. */
const SUGGESTIONS = [
  { icon: Calculator, text: "What is 18% of 2,450?" },
  { icon: Clock, text: "What time is it in Tokyo right now?" },
  { icon: Lightbulb, text: "Explain how a bearer token is verified, in simple terms." },
  { icon: PenLine, text: "Draft a short, polite follow-up email after a meeting." },
] as const;

/** Distance from the bottom (px) within which the view keeps following a streaming answer. */
const FOLLOW_SLACK = 96;

/** What is needed to rate an answer; without it the chat shows no rating buttons. */
export interface FeedbackTarget {
  deps: DataDeps;
  threadId: string | null;
}

function AssistantAvatar() {
  return <Logo className="mt-0.5 size-7 rounded-full" />;
}

function Thinking() {
  return (
    <p className="flex h-7 items-center gap-2 text-sm text-muted-foreground">
      <span aria-hidden="true" className="flex gap-1">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-1.5 animate-bounce rounded-full bg-current"
            style={{ animationDelay: `${String(delay)}ms` }}
          />
        ))}
      </span>
      Thinking…
    </p>
  );
}

function MessageView({
  message,
  onDecide,
  feedback,
}: {
  message: ChatMessage;
  onDecide: (decision: Decision) => void;
  feedback: FeedbackTarget | undefined;
}) {
  if (message.role === "user") {
    return (
      <li className="flex animate-in justify-end duration-300 fade-in-0 slide-in-from-bottom-1">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-secondary-foreground">
          <p className="sr-only">You</p>
          <p className="text-[0.9375rem] leading-7 break-words whitespace-pre-wrap">
            {message.text}
          </p>
        </div>
      </li>
    );
  }
  const finished = message.status === "done" && message.text !== "";
  return (
    <li className="flex animate-in gap-3 duration-300 fade-in-0">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        <p className="sr-only">neuron</p>
        {message.text !== "" && <Markdown text={message.text} />}
        {message.status === "streaming" && message.text === "" && <Thinking />}
        {(message.toolCalls.length > 0 || message.skipped.length > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {message.toolCalls.length > 0 && (
              <Badge variant="outline" className="font-normal text-muted-foreground">
                <Wrench aria-hidden="true" />
                <span>Used: {message.toolCalls.join(", ")}</span>
              </Badge>
            )}
            {message.skipped.map((tool, index) => (
              <Badge
                key={index}
                variant="outline"
                className="font-normal text-muted-foreground whitespace-normal"
              >
                <ShieldAlert aria-hidden="true" />
                <span>
                  {SKIPPED_TEXT[tool.why]}: {displaySafe(tool.name)}
                </span>
              </Badge>
            ))}
          </div>
        )}
        {message.status === "stopped" && <p className="text-xs text-muted-foreground">Stopped.</p>}
        {message.approval !== null && (
          <ApprovalCard approval={message.approval} onDecide={onDecide} />
        )}
        {message.status === "failed" && message.failure !== null && (
          <Alert variant="destructive" role="alert">
            <CircleAlert aria-hidden="true" />
            <AlertDescription>{failureText(message.failure)}</AlertDescription>
          </Alert>
        )}
        {feedback !== undefined && finished && (
          <MessageActions text={message.text}>
            {feedback.threadId !== null && message.runId !== null && (
              <FeedbackBar
                deps={feedback.deps}
                threadId={feedback.threadId}
                runId={message.runId}
              />
            )}
          </MessageActions>
        )}
      </div>
    </li>
  );
}

/** Above the composer while the conversation is empty. */
function Greeting() {
  return (
    <div className="flex flex-1 animate-in flex-col items-center justify-end pt-10 pb-8 text-center duration-500 fade-in-0">
      <Logo className="size-11 rounded-xl" />
      <p className="mt-5 text-2xl font-semibold tracking-tight">How can I help today?</p>
      <p className="mt-2 max-w-sm text-sm text-balance text-muted-foreground">
        Ask a question, or start from one of the ideas below.
      </p>
    </div>
  );
}

/**
 * Below the composer while the conversation is empty, so the composer sits in the middle of the
 * page and stays next after "New conversation" in the tab order.
 */
function Suggestions({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex-1 animate-in px-4 pt-2 pb-6 duration-500 fade-in-0">
      <div className="mx-auto grid w-full max-w-3xl gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, text }) => (
          <button
            key={text}
            type="button"
            onClick={() => {
              onPick(text);
            }}
            className="group flex items-start gap-3 rounded-xl border bg-card p-3.5 text-left text-sm shadow-xs transition-all outline-none hover:-translate-y-px hover:border-foreground/15 hover:shadow-sm focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <Icon
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-brand"
            />
            <span>{text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export type Chat = ReturnType<typeof useChat>;

/** The conversation with its own chat state (the page owns it when other panels need it). */
export function ChatScreen(deps: ChatDeps) {
  return <ChatView chat={useChat(deps)} maxChars={deps.maxChars} />;
}

export function ChatView({
  chat,
  maxChars,
  feedback,
  toolbarStart,
}: {
  chat: Chat;
  maxChars: number;
  feedback?: DataDeps;
  /** Shown at the start of the conversation's toolbar (the page's menu button). */
  toolbarStart?: ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<DraftProblem | null>(null);
  const count = characterCount(draft.trim());
  const blocked = chat.running || draft.trim() === "";
  const composer = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const wasRunning = useRef(false);
  const empty = chat.messages.length === 0 && !chat.opening;

  // When a reply ends, the Stop button (or a decided approval's buttons) disappears and keyboard
  // focus would fall to the page. Return it to the composer, unless focus has gone somewhere
  // deliberate (the approval card takes it first when it appears).
  useEffect(() => {
    if (wasRunning.current && !chat.running) {
      const active = document.activeElement;
      if (active === null || active === document.body) composer.current?.focus();
    }
    wasRunning.current = chat.running;
  }, [chat.running]);

  // An opened conversation is ready to continue: put the cursor in the composer. (A pending
  // approval card takes focus itself when it arrives, a moment later.)
  useEffect(() => {
    if (chat.openedAt > 0) composer.current?.focus();
  }, [chat.openedAt]);

  // An opened conversation starts at its newest message, wherever the last one was scrolled to.
  // A layout effect declared before the one below, so it applies in the same commit.
  useLayoutEffect(() => {
    following.current = true;
  }, [chat.openedAt]);

  // Keep the newest text in view while it streams, unless the reader has scrolled up.
  useLayoutEffect(() => {
    const node = scroller.current;
    if (node !== null && following.current) node.scrollTop = node.scrollHeight;
  }, [chat.messages]);

  async function submit(): Promise<void> {
    const found = checkDraft(draft, maxChars).problem;
    setProblem(found);
    if (found !== null || chat.running) return;
    setDraft("");
    following.current = true;
    // Clicking Send disables it while the reply streams: keep the user in the composer.
    composer.current?.focus();
    await chat.send(draft);
  }

  function onSubmit(event: SubmitEvent): void {
    event.preventDefault();
    void submit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <section aria-label="Conversation" className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        {toolbarStart}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto text-muted-foreground"
          onClick={() => {
            chat.newConversation();
            following.current = true;
            composer.current?.focus();
          }}
        >
          <SquarePen />
          New conversation
        </Button>
      </header>
      <div
        ref={scroller}
        className="flex min-h-0 flex-1 flex-col overflow-y-auto [scrollbar-gutter:stable]"
        onScroll={(event) => {
          const node = event.currentTarget;
          following.current = node.scrollHeight - node.scrollTop - node.clientHeight < FOLLOW_SLACK;
        }}
      >
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pb-6">
          {chat.opening && (
            <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              Opening conversation…
            </p>
          )}
          {chat.openFailure !== null && (
            <Alert variant="destructive" role="alert" className="my-4">
              <CircleAlert aria-hidden="true" />
              <AlertDescription>{openFailureText(chat.openFailure)}</AlertDescription>
            </Alert>
          )}
          {chat.earlierHidden && (
            <p className="py-3 text-center text-xs text-muted-foreground">
              Earlier messages are not shown.
            </p>
          )}
          {empty && <Greeting />}
          <div
            role="log"
            aria-label="Messages"
            aria-live="polite"
            className={cn(empty && "sr-only")}
          >
            <ul className="space-y-8 pt-2">
              {chat.messages.map((message) => (
                <MessageView
                  key={message.id}
                  message={message}
                  onDecide={(decision) => void chat.decide(message.id, decision)}
                  feedback={
                    feedback === undefined ? undefined : { deps: feedback, threadId: chat.threadId }
                  }
                />
              ))}
            </ul>
          </div>
        </div>
      </div>
      <div className={cn("shrink-0 px-4", empty ? "pb-2" : "pb-4")}>
        <form onSubmit={onSubmit} className="mx-auto w-full max-w-3xl">
          <div
            className={cn(
              "rounded-2xl border bg-card shadow-sm transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/30",
              problem !== null && "border-destructive",
            )}
          >
            <label htmlFor="message" className="sr-only">
              Message
            </label>
            <Textarea
              id="message"
              ref={composer}
              value={draft}
              rows={1}
              placeholder="Message neuron…"
              className="max-h-52 min-h-14 resize-none border-0 bg-transparent px-4 pt-3.5 pb-1 text-[0.9375rem] shadow-none focus-visible:ring-0 dark:bg-transparent"
              aria-describedby="message-count"
              aria-invalid={problem !== null || undefined}
              onChange={(event) => {
                setDraft(event.target.value);
                setProblem(null);
              }}
              onKeyDown={onKeyDown}
            />
            <div className="flex items-center gap-2 px-3 pb-3">
              <p
                id="message-count"
                className={cn(
                  "text-xs tabular-nums text-muted-foreground",
                  count > maxChars && "text-destructive",
                )}
              >
                {count} / {maxChars}
              </p>
              <div className="ml-auto flex items-center gap-1.5">
                {chat.canRetry && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => void chat.retry()}>
                    <RotateCcw />
                    Retry
                  </Button>
                )}
                {chat.running && (
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    className="rounded-full"
                    aria-label="Stop"
                    title="Stop"
                    onClick={chat.stop}
                  >
                    <Square className="size-3 fill-current" />
                  </Button>
                )}
                <Button
                  type="submit"
                  size="icon-sm"
                  className="rounded-full"
                  aria-label="Send"
                  title="Send (Enter)"
                  disabled={blocked}
                >
                  <ArrowUp />
                </Button>
              </div>
            </div>
          </div>
          {problem !== null && (
            <p role="alert" className="mt-2 px-1 text-sm text-destructive">
              {draftProblemText(problem, maxChars)}
            </p>
          )}
          <p className="mt-2 hidden text-center text-xs text-muted-foreground sm:block">
            Enter to send, Shift + Enter for a new line. neuron can make mistakes; check important
            answers.
          </p>
        </form>
      </div>
      {empty && (
        <Suggestions
          onPick={(text) => {
            setDraft(text);
            setProblem(null);
            composer.current?.focus();
          }}
        />
      )}
    </section>
  );
}
