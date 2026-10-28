import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "@/App";
import { cn } from "@/lib/utils";

describe("scaffold", () => {
  it("renders the heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "neuron" })).toBeInTheDocument();
  });

  it("drops falsy classes and lets the last conflicting Tailwind class win", () => {
    expect(cn("p-2", { hidden: false, block: true }, "p-4")).toBe("block p-4");
  });
});
