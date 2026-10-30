import { CircleAlert, LoaderCircle, LogIn } from "lucide-react";

import { Logo } from "@/components/Logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuth, type AuthErrorCode } from "@/lib/auth";

import { SignedInView } from "./SignedInView";

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

function SignInButton({ onClick }: { onClick: () => void }) {
  return (
    <Button type="button" size="lg" className="w-full" onClick={onClick}>
      <LogIn />
      Sign in
    </Button>
  );
}

export function App({ apiUrl, maxChars }: AppProps) {
  const auth = useAuth();
  if (auth.status === "signed_in") {
    return <SignedInView auth={auth} apiUrl={apiUrl} maxChars={maxChars} />;
  }
  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden p-4">
      {/* A soft brand glow behind the card. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[28rem] bg-[radial-gradient(ellipse_at_top,var(--color-brand)_0%,transparent_65%)] opacity-15"
      />
      <div className="w-full max-w-sm animate-in fade-in-0 slide-in-from-bottom-2 duration-500">
        <div className="flex flex-col items-center text-center">
          <Logo className="size-12 rounded-xl" />
          <h1 className="mt-5 text-3xl font-semibold tracking-tight">neuron</h1>
          <p className="mt-2 text-sm text-balance text-muted-foreground">
            Your AI assistant. Sign in to pick up your conversations where you left off.
          </p>
        </div>
        <div className="mt-8 space-y-4">
          {auth.status === "loading" && (
            <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              Loading…
            </p>
          )}
          {auth.status === "signed_out" && <SignInButton onClick={auth.signIn} />}
          {auth.status === "expired" && (
            <div role="alert" className="space-y-4">
              <Alert>
                <CircleAlert />
                <AlertDescription>
                  <p>Your session ended. Please sign in again.</p>
                </AlertDescription>
              </Alert>
              <SignInButton onClick={auth.signIn} />
            </div>
          )}
          {auth.status === "error" && auth.error !== null && (
            <div role="alert" className="space-y-4">
              <Alert variant="destructive">
                <CircleAlert />
                <AlertDescription>
                  <p>{ERROR_TEXT[auth.error]}</p>
                </AlertDescription>
              </Alert>
              <SignInButton onClick={auth.signIn} />
            </div>
          )}
        </div>
        <p className="mt-10 text-center text-xs text-muted-foreground">
          Sign-in is handled by your organisation&apos;s identity provider.
        </p>
      </div>
    </main>
  );
}
