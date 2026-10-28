import { ChatScreen } from "@/features/chat/ChatScreen";
import { DataScreen } from "@/features/data/DataScreen";
import { useState } from "react";

import { useAuth, type AuthErrorCode } from "@/lib/auth";

/** Fixed wording per reason. Text from the identity provider is never shown. */
const ERROR_TEXT: Record<AuthErrorCode, string> = {
  no_transaction: "That sign-in link has expired. Please sign in again.",
  state_mismatch: "That sign-in could not be verified. Please sign in again.",
  issuer_mismatch: "That sign-in could not be verified. Please sign in again.",
  provider_error: "Sign-in was cancelled or refused. Please try again.",
  token_exchange_failed: "Sign-in could not be completed. Please try again.",
  invalid_token_response: "Sign-in could not be completed. Please try again.",
  invalid_id_token: "That sign-in could not be verified. Please sign in again.",
  discovery_failed: "The sign-in service is unavailable. Please try again later.",
  network: "The sign-in service could not be reached. Please try again.",
};

export interface AppProps {
  apiUrl: string;
  maxChars: number;
}

export function App({ apiUrl, maxChars }: AppProps) {
  const auth = useAuth();
  const [view, setView] = useState<"chat" | "data">("chat");
  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="text-2xl font-semibold">neuron</h1>
      {auth.status === "loading" && <p className="mt-2 opacity-80">Loading…</p>}
      {auth.status === "signed_out" && (
        <button type="button" className="mt-4 rounded border px-3 py-1" onClick={auth.signIn}>
          Sign in
        </button>
      )}
      {auth.status === "expired" && (
        <div role="alert" className="mt-4">
          <p>Your session ended. Please sign in again.</p>
          <button type="button" className="mt-2 rounded border px-3 py-1" onClick={auth.signIn}>
            Sign in
          </button>
        </div>
      )}
      {auth.status === "error" && auth.error !== null && (
        <div role="alert" className="mt-4">
          <p>{ERROR_TEXT[auth.error]}</p>
          <button type="button" className="mt-2 rounded border px-3 py-1" onClick={auth.signIn}>
            Sign in
          </button>
        </div>
      )}
      {auth.status === "signed_in" && (
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
            <ChatScreen
              apiUrl={apiUrl}
              maxChars={maxChars}
              getAccessToken={auth.getAccessToken}
              onSessionEnded={auth.sessionEnded}
            />
          </div>
          {view === "data" && (
            <DataScreen
              deps={{
                apiUrl,
                getAccessToken: auth.getAccessToken,
                onSessionEnded: auth.sessionEnded,
              }}
              onErased={auth.signOut}
            />
          )}
        </div>
      )}
    </main>
  );
}
