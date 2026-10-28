import { createContext, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";

import type { AuthSession, AuthSnapshot } from "./session";

const AuthContext = createContext<AuthSession | null>(null);

export function AuthProvider({ session, children }: { session: AuthSession; children: ReactNode }) {
  useEffect(() => {
    void session.init(window.location.href);
  }, [session]);
  return <AuthContext value={session}>{children}</AuthContext>;
}

export interface UseAuth extends AuthSnapshot {
  signIn: () => void;
  signOut: () => void;
  /** The current access token for an API call, or null (signed out, expired). */
  getAccessToken: () => string | null;
}

export function useAuth(): UseAuth {
  const session = useContext(AuthContext);
  if (session === null) throw new Error("useAuth must be used inside <AuthProvider>");
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);
  return {
    ...snapshot,
    signIn: () => {
      void session.signIn(window.location.pathname + window.location.search);
    },
    signOut: () => {
      void session.signOut();
    },
    getAccessToken: () => session.getAccessToken(),
  };
}
