import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { AuthProvider } from "@/lib/auth";
import { AuthSession, type AuthErrorCode, type AuthSnapshot } from "@/lib/auth/session";
import { cn } from "@/lib/utils";
import { fakeApi, memory, thread } from "@/test/dataApi";

const config = {
  issuer: "http://localhost:8180/realms/neuron",
  clientId: "neuron-web",
  redirectUri: "http://localhost:3000/",
  postLogoutRedirectUri: "http://localhost:3000/",
  scope: "openid profile",
};

/** A session pinned to a snapshot, with the actions spied on. */
function fakeSession(snapshot: AuthSnapshot) {
  const session = new AuthSession({ config });
  vi.spyOn(session, "getSnapshot").mockReturnValue(snapshot);
  vi.spyOn(session, "init").mockResolvedValue();
  vi.spyOn(session, "getAccessToken").mockReturnValue("tok-1");
  const signIn = vi.spyOn(session, "signIn").mockResolvedValue();
  const signOut = vi.spyOn(session, "signOut").mockResolvedValue();
  return { session, signIn, signOut };
}

function view(snapshot: AuthSnapshot) {
  const fake = fakeSession(snapshot);
  render(
    <AuthProvider session={fake.session}>
      <App apiUrl="http://127.0.0.1:8000" maxChars={12000} />
    </AuthProvider>,
  );
  return fake;
}

const base = { displayName: null, error: null } as const;

describe("scaffold", () => {
  it("drops falsy classes and lets the last conflicting Tailwind class win", () => {
    expect(cn("p-2", { hidden: false, block: true }, "p-4")).toBe("block p-4");
  });
});

describe("App", () => {
  it("offers sign-in when signed out, and signs in on click", async () => {
    const { signIn } = view({ ...base, status: "signed_out" });
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("heading", { name: "neuron" })).toBeInTheDocument();
    expect(signIn).toHaveBeenCalledOnce();
  });

  it("shows the user and offers sign-out when signed in", async () => {
    const { signOut } = view({ status: "signed_in", displayName: "alice", error: null });
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(screen.getByText("Signed in as alice.")).toBeInTheDocument();
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("renders a hostile display name as text, never as markup", () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const { container } = render(
      <AuthProvider
        session={fakeSession({ status: "signed_in", displayName: hostile, error: null }).session}
      >
        <App apiUrl="http://127.0.0.1:8000" maxChars={12000} />
      </AuthProvider>,
    );

    expect(container.querySelector("img, script")).toBeNull();
    expect(screen.getByText(`Signed in as ${hostile}.`)).toBeInTheDocument();
  });

  it("tells the user the session ended when the token expires", () => {
    view({ ...base, status: "expired" });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your session ended. Please sign in again.",
    );
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it.each<[AuthErrorCode, string]>([
    ["state_mismatch", "That sign-in could not be verified. Please sign in again."],
    ["provider_error", "Sign-in was cancelled or refused. Please try again."],
    ["discovery_failed", "The sign-in service is unavailable. Please try again later."],
  ])("shows fixed wording for %s, never provider text", (error, text) => {
    view({ ...base, status: "error", error });

    expect(screen.getByRole("alert")).toHaveTextContent(text);
  });

  it("says nothing about the user while loading", () => {
    view({ ...base, status: "loading" });

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("App sections", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the data page only when it is opened, and keeps the chat draft meanwhile", async () => {
    const api = fakeApi({ memories: [memory(1, "likes tea")], threads: [] });
    vi.stubGlobal("fetch", api.fetch);
    const { signOut } = view({ status: "signed_in", displayName: "alice", error: null });
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("a half-written question");

    // Only the conversation list loads up front; the data page (memories) waits until opened.
    expect(api.calls.map((call) => call.url.pathname)).toEqual(["/v1/me/threads"]);
    await user.click(screen.getByRole("button", { name: "Your data" }));
    expect(await screen.findByText("likes tea")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message", hidden: true })).toHaveValue(
      "a half-written question",
    );

    await user.click(screen.getByRole("button", { name: "Chat" }));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("a half-written question");
    expect(signOut).not.toHaveBeenCalled();
  });

  it("signs the user out after a complete erase", async () => {
    const api = fakeApi({ memories: [memory(1)], threads: [thread(1, 2)] });
    vi.stubGlobal("fetch", api.fetch);
    const { signOut } = view({ status: "signed_in", displayName: "alice", error: null });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Your data" }));
    await user.type(await screen.findByLabelText(/Type erase my data to confirm/), "erase my data");
    await user.click(screen.getByRole("button", { name: "Erase all my data" }));

    await waitFor(() => {
      expect(signOut).toHaveBeenCalledOnce();
    });
  });
});
