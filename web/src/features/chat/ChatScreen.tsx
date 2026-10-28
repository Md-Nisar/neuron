import { useState, type KeyboardEvent, type SubmitEvent } from "react";

import { characterCount, checkDraft, type DraftProblem } from "./limits";
import { Markdown } from "./Markdown";
import { APPROVAL_NOTICE, draftProblemText, failureText } from "./messages";
import type { ChatMessage } from "./chatState";
import { useChat, type ChatDeps } from "./useChat";

function MessageView({ message }: { message: ChatMessage }) {
  const mine = message.role === "user";
  return (
    <li className={mine ? "ml-8 rounded border p-3" : "mr-8 rounded p-3"}>
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
          {message.status === "needs_approval" && (
            <p role="status" className="mt-1">
              {APPROVAL_NOTICE}
            </p>
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

export function ChatScreen(deps: ChatDeps) {
  const chat = useChat(deps);
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<DraftProblem | null>(null);
  const count = characterCount(draft.trim());
  const blocked = chat.running || draft.trim() === "";

  async function submit(): Promise<void> {
    const found = checkDraft(draft, deps.maxChars).problem;
    setProblem(found);
    if (found !== null || chat.running) return;
    setDraft("");
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
        <button type="button" className="rounded border px-3 py-1" onClick={chat.newConversation}>
          New conversation
        </button>
      </div>
      <ul role="log" aria-label="Messages" aria-live="polite" className="mt-4 space-y-3">
        {chat.messages.map((message) => (
          <MessageView key={message.id} message={message} />
        ))}
      </ul>
      <form onSubmit={onSubmit} className="mt-4">
        <label htmlFor="message" className="sr-only">
          Message
        </label>
        <textarea
          id="message"
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
          {count} / {deps.maxChars}
        </p>
        {problem !== null && (
          <p role="alert" className="mt-1">
            {draftProblemText(problem, deps.maxChars)}
          </p>
        )}
        <div className="mt-2 flex gap-2">
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
