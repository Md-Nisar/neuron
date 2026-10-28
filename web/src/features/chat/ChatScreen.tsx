import { useEffect, useRef, useState, type KeyboardEvent, type SubmitEvent } from "react";

import type { Decision } from "@/lib/stream";

import { characterCount, checkDraft, type DraftProblem } from "./limits";
import { ApprovalCard } from "./ApprovalCard";
import { Markdown } from "./Markdown";
import { draftProblemText, failureText } from "./messages";
import type { ChatMessage } from "./chatState";
import { useChat, type ChatDeps } from "./useChat";

function MessageView({
  message,
  onDecide,
}: {
  message: ChatMessage;
  onDecide: (decision: Decision) => void;
}) {
  const mine = message.role === "user";
  return (
    <li className={mine ? "ml-4 rounded border p-3 sm:ml-8" : "mr-4 rounded p-3 sm:mr-8"}>
      <p className="mb-1 text-xs font-medium opacity-70">{mine ? "You" : "neuron"}</p>
      {mine ? (
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
      ) : (
        <>
          {message.text !== "" && <Markdown text={message.text} />}
          {message.toolCalls.length > 0 && (
            <p className="mt-1 text-xs opacity-70">Used: {message.toolCalls.join(", ")}</p>
          )}
          {message.status === "streaming" && message.text === "" && (
            <p className="opacity-70">Thinking…</p>
          )}
          {message.status === "stopped" && <p className="mt-1 text-xs opacity-70">Stopped.</p>}
          {message.approval !== null && (
            <ApprovalCard approval={message.approval} onDecide={onDecide} />
          )}
          {message.status === "failed" && message.failure !== null && (
            <p role="alert" className="mt-1">
              {failureText(message.failure)}
            </p>
          )}
        </>
      )}
    </li>
  );
}

export type Chat = ReturnType<typeof useChat>;

/** The conversation with its own chat state (the page owns it when other panels need it). */
export function ChatScreen(deps: ChatDeps) {
  return <ChatView chat={useChat(deps)} maxChars={deps.maxChars} />;
}

export function ChatView({ chat, maxChars }: { chat: Chat; maxChars: number }) {
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<DraftProblem | null>(null);
  const count = characterCount(draft.trim());
  const blocked = chat.running || draft.trim() === "";
  const composer = useRef<HTMLTextAreaElement>(null);
  const wasRunning = useRef(false);

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

  async function submit(): Promise<void> {
    const found = checkDraft(draft, maxChars).problem;
    setProblem(found);
    if (found !== null || chat.running) return;
    setDraft("");
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
    <section aria-label="Conversation" className="mt-6">
      <div className="flex justify-end">
        <button
          type="button"
          className="rounded border px-3 py-1"
          onClick={() => {
            chat.newConversation();
            composer.current?.focus();
          }}
        >
          New conversation
        </button>
      </div>
      <div role="log" aria-label="Messages" aria-live="polite" className="mt-4">
        <ul className="space-y-3">
          {chat.messages.map((message) => (
            <MessageView
              key={message.id}
              message={message}
              onDecide={(decision) => void chat.decide(message.id, decision)}
            />
          ))}
        </ul>
      </div>
      <form onSubmit={onSubmit} className="mt-4">
        <label htmlFor="message" className="sr-only">
          Message
        </label>
        <textarea
          id="message"
          ref={composer}
          value={draft}
          rows={3}
          className="w-full rounded border p-2"
          aria-describedby="message-count"
          onChange={(event) => {
            setDraft(event.target.value);
            setProblem(null);
          }}
          onKeyDown={onKeyDown}
        />
        <p id="message-count" className="text-xs opacity-70">
          {count} / {maxChars}
        </p>
        {problem !== null && (
          <p role="alert" className="mt-1">
            {draftProblemText(problem, maxChars)}
          </p>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="submit" className="rounded border px-3 py-1" disabled={blocked}>
            Send
          </button>
          {chat.running && (
            <button type="button" className="rounded border px-3 py-1" onClick={chat.stop}>
              Stop
            </button>
          )}
          {chat.canRetry && (
            <button
              type="button"
              className="rounded border px-3 py-1"
              onClick={() => void chat.retry()}
            >
              Retry
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
