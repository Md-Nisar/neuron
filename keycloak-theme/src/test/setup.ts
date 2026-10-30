import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no matchMedia; the theme provider asks it for the OS colour scheme.
export function setPrefersDark(dark: boolean): void {
    vi.stubGlobal(
        "matchMedia",
        (query: string): MediaQueryList =>
            ({
                matches: dark && query.includes("dark"),
                media: query,
                addEventListener: () => undefined,
                removeEventListener: () => undefined,
                addListener: () => undefined,
                removeListener: () => undefined,
                dispatchEvent: () => false,
                onchange: null
            }) as MediaQueryList
    );
}

// Radix (checkbox, dropdown) measures elements with ResizeObserver, which jsdom lacks.
vi.stubGlobal(
    "ResizeObserver",
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    }
);

// user-event asks jsdom which element is under the pointer; jsdom has no layout.
document.elementFromPoint = () => null;

setPrefersDark(false);

afterEach(() => {
    cleanup();
    window.localStorage.clear();
    document.documentElement.className = "";
});
