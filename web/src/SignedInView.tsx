import { LogOut, Menu, MessageSquare, Monitor, Moon, ShieldCheck, Sun, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChatView } from "@/features/chat/ChatScreen";
import { useChat } from "@/features/chat/useChat";
import { DataScreen } from "@/features/data/DataScreen";
import { ThreadList } from "@/features/threads/ThreadList";
import type { UseAuth } from "@/lib/auth";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";

export interface SignedInViewProps {
  auth: Pick<UseAuth, "displayName" | "getAccessToken" | "sessionEnded" | "signOut">;
  apiUrl: string;
  maxChars: number;
}

const THEME: Record<ThemeChoice, { label: string; icon: ReactNode }> = {
  system: { label: "Theme: system", icon: <Monitor /> },
  light: { label: "Theme: light", icon: <Sun /> },
  dark: { label: "Theme: dark", icon: <Moon /> },
};

function NavButton({
  active,
  icon,
  children,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-sm font-medium text-sidebar-foreground/80 transition-colors outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 [&_svg]:size-4 [&_svg]:shrink-0",
        active && "bg-sidebar-accent text-sidebar-accent-foreground",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

/**
 * Everything that exists only while someone is signed in. It is unmounted on sign-out, so one
 * person's messages and conversation list never survive into the next person's session.
 */
export function SignedInView({ auth, apiUrl, maxChars }: SignedInViewProps) {
  const [view, setView] = useState<"chat" | "data">("chat");
  const [refresh, setRefresh] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const theme = useTheme();
  const chat = useChat({
    apiUrl,
    maxChars,
    getAccessToken: auth.getAccessToken,
    onSessionEnded: auth.sessionEnded,
  });
  const wasRunning = useRef(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  // A finished reply may have created or touched a conversation: reload the list.
  useEffect(() => {
    if (wasRunning.current && !chat.running) setRefresh((n) => n + 1);
    wasRunning.current = chat.running;
  }, [chat.running]);

  // On small screens the sidebar is a drawer: Escape closes it and focus goes back to the menu.
  useEffect(() => {
    if (!drawer) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawer(false);
        menuButton.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [drawer]);

  const dataDeps = {
    apiUrl,
    getAccessToken: auth.getAccessToken,
    onSessionEnded: auth.sessionEnded,
  };

  function show(next: "chat" | "data"): void {
    setView(next);
    setDrawer(false);
  }

  const initial = auth.displayName?.trim().charAt(0).toUpperCase() ?? "";
  const menu = (
    <Button
      ref={menuButton}
      type="button"
      variant="ghost"
      size="icon-sm"
      className="md:hidden"
      aria-label="Open sidebar"
      aria-expanded={drawer}
      aria-controls="sidebar"
      onClick={() => {
        setDrawer(true);
      }}
    >
      <Menu />
    </Button>
  );

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      {/* Drawer backdrop (small screens only). */}
      <div
        aria-hidden="true"
        className={cn(
          "fixed inset-0 z-30 bg-black/40 backdrop-blur-[1px] transition-opacity md:hidden",
          drawer ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={() => {
          setDrawer(false);
        }}
      />
      <aside
        id="sidebar"
        aria-label="Sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[translate,visibility] duration-200 ease-out md:static md:visible md:translate-x-0",
          drawer ? "visible translate-x-0 shadow-xl" : "invisible -translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 px-4">
          <Logo />
          <h1 className="text-lg font-semibold tracking-tight">neuron</h1>
          {drawer && (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="ml-auto md:hidden"
              aria-label="Close sidebar"
              onClick={() => {
                setDrawer(false);
                menuButton.current?.focus();
              }}
            >
              <X />
            </Button>
          )}
        </div>
        <nav aria-label="Sections" className="space-y-0.5 px-2 pb-2">
          <NavButton
            active={view === "chat"}
            icon={<MessageSquare />}
            onClick={() => {
              show("chat");
            }}
          >
            Chat
          </NavButton>
          <NavButton
            active={view === "data"}
            icon={<ShieldCheck />}
            onClick={() => {
              show("data");
            }}
          >
            Your data
          </NavButton>
        </nav>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 [scrollbar-width:thin]">
          <ThreadList
            deps={dataDeps}
            refresh={refresh}
            activeThreadId={chat.threadId}
            openDisabled={chat.running || chat.opening}
            onOpen={(threadId) => {
              show("chat");
              void chat.open(threadId);
            }}
            onDeleted={(threadId) => {
              if (chat.threadId === threadId) chat.newConversation();
            }}
          />
        </div>
        <div className="flex items-center gap-2 border-t border-sidebar-border p-3">
          <span
            aria-hidden="true"
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-sm font-medium"
          >
            {initial === "" ? "?" : initial}
          </span>
          <p className="min-w-0 flex-1 truncate text-sm">
            Signed in{auth.displayName === null ? "" : ` as ${auth.displayName}`}.
          </p>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={THEME[theme.choice].label}
                onClick={theme.cycle}
              >
                {THEME[theme.choice].icon}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">{THEME[theme.choice].label}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Sign out"
                onClick={auth.signOut}
              >
                <LogOut />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">Sign out</TooltipContent>
          </Tooltip>
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        {/* The chat stays mounted (hidden) so a conversation in progress survives a visit to "Your data". */}
        <div hidden={view !== "chat"} className="min-h-0 flex-1">
          <ChatView
            chat={chat}
            maxChars={maxChars}
            feedback={dataDeps}
            toolbarStart={view === "chat" ? menu : null}
          />
        </div>
        {view === "data" && (
          <div className="flex min-h-0 flex-1 flex-col">
            <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
              {menu}
              <h2 className="text-sm font-medium">Your data</h2>
            </header>
            <div className="flex-1 overflow-y-auto">
              <DataScreen deps={dataDeps} onErased={auth.signOut} />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
