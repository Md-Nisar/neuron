import { useEffect, useRef, useState } from "react";

import { ChatView } from "@/features/chat/ChatScreen";
import { useChat } from "@/features/chat/useChat";
import { DataScreen } from "@/features/data/DataScreen";
import { ThreadList } from "@/features/threads/ThreadList";
import type { UseAuth } from "@/lib/auth";

export interface SignedInViewProps {
  auth: Pick<UseAuth, "displayName" | "getAccessToken" | "sessionEnded" | "signOut">;
  apiUrl: string;
  maxChars: number;
}

/**
 * Everything that exists only while someone is signed in. It is unmounted on sign-out, so one
 * person's messages and conversation list never survive into the next person's session.
 */
export function SignedInView({ auth, apiUrl, maxChars }: SignedInViewProps) {
  const [view, setView] = useState<"chat" | "data">("chat");
  const [refresh, setRefresh] = useState(0);
  const chat = useChat({
    apiUrl,
    maxChars,
    getAccessToken: auth.getAccessToken,
    onSessionEnded: auth.sessionEnded,
  });
  const wasRunning = useRef(false);

  // A finished reply may have created or touched a conversation: reload the list.
  useEffect(() => {
    if (wasRunning.current && !chat.running) setRefresh((n) => n + 1);
    wasRunning.current = chat.running;
  }, [chat.running]);

  const dataDeps = {
    apiUrl,
    getAccessToken: auth.getAccessToken,
    onSessionEnded: auth.sessionEnded,
  };

  return (
    <div className="mt-4">
      <p>Signed in{auth.displayName === null ? "" : ` as ${auth.displayName}`}.</p>
      <button type="button" className="mt-2 rounded border px-3 py-1" onClick={auth.signOut}>
        Sign out
      </button>
      <nav aria-label="Sections" className="mt-4 flex gap-2">
        <button
          type="button"
          className="rounded border px-3 py-1"
          aria-pressed={view === "chat"}
          onClick={() => {
            setView("chat");
          }}
        >
          Chat
        </button>
        <button
          type="button"
          className="rounded border px-3 py-1"
          aria-pressed={view === "data"}
          onClick={() => {
            setView("data");
          }}
        >
          Your data
        </button>
      </nav>
      {/* The chat stays mounted (hidden) so a conversation in progress survives a visit to "Your data". */}
      <div hidden={view !== "chat"}>
        <ChatView chat={chat} maxChars={maxChars} feedback={dataDeps} />
        <ThreadList
          deps={dataDeps}
          refresh={refresh}
          activeThreadId={chat.threadId}
          openDisabled={chat.running || chat.opening}
          onOpen={(threadId) => {
            setView("chat");
            void chat.open(threadId);
          }}
          onDeleted={(threadId) => {
            if (chat.threadId === threadId) chat.newConversation();
          }}
        />
      </div>
      {view === "data" && <DataScreen deps={dataDeps} onErased={auth.signOut} />}
    </div>
  );
}
