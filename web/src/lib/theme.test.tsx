import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useTheme } from "./theme";

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.className = "";
});

describe("the colour scheme choice", () => {
  it("cycles system, light, dark, remembers it, and puts it on <html>", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.choice).toBe("system");

    act(() => {
      result.current.cycle();
    });
    expect(result.current.choice).toBe("light");
    expect(document.documentElement).toHaveClass("light");
    expect(document.documentElement).not.toHaveClass("dark");

    act(() => {
      result.current.cycle();
    });
    expect(result.current.choice).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("neuron.theme")).toBe("dark");

    expect(renderHook(() => useTheme()).result.current.choice).toBe("dark");
  });
});
