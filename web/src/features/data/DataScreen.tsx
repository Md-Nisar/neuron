import type { DataDeps } from "./api";
import { EraseSection } from "./EraseSection";
import { ExportSection } from "./ExportSection";
import { MemoriesSection } from "./MemoriesSection";

export function DataScreen({ deps, onErased }: { deps: DataDeps; onErased: () => void }) {
  return (
    <section
      aria-label="Your data"
      className="mx-auto w-full max-w-3xl animate-in space-y-6 px-4 py-8 duration-300 fade-in-0"
    >
      <div>
        <p className="text-2xl font-semibold tracking-tight">Your data</p>
        <p className="mt-1 text-sm text-muted-foreground">
          See what neuron remembers about you, take a copy, or erase it.
        </p>
      </div>
      <MemoriesSection deps={deps} />
      <ExportSection deps={deps} />
      <EraseSection deps={deps} onErased={onErased} />
    </section>
  );
}
