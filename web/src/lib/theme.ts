import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "neuron.theme";
const ORDER: readonly ThemeChoice[] = ["system", "light", "dark"];

function saved(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system"; // storage blocked (private window, policy): follow the OS
  }
}

function systemDark(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

/** Put `dark` or `light` on <html>; the stylesheet keys every colour token off that class. */
export function applyTheme(choice: ThemeChoice = saved()): void {
  const dark = choice === "dark" || (choice === "system" && systemDark());
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.classList.toggle("light", !dark);
}

/** The colour scheme choice, kept in this browser only (a per-viewer convenience). */
export function useTheme(): { choice: ThemeChoice; cycle: () => void } {
  const [choice, setChoice] = useState<ThemeChoice>(saved);

  useEffect(() => {
    applyTheme(choice);
    if (choice !== "system" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => {
      applyTheme("system");
    };
    query.addEventListener("change", follow);
    return () => {
      query.removeEventListener("change", follow);
    };
  }, [choice]);

  const cycle = useCallback(() => {
    setChoice((current) => {
      const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system";
      try {
        window.localStorage.setItem(KEY, next);
      } catch {
        // not saved; the choice still applies until the page is closed
      }
      return next;
    });
  }, []);

  return { choice, cycle };
}
