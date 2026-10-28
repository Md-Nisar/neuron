import type { DataDeps } from "./api";
import { EraseSection } from "./EraseSection";
import { ExportSection } from "./ExportSection";
import { MemoriesSection } from "./MemoriesSection";

export function DataScreen({ deps, onErased }: { deps: DataDeps; onErased: () => void }) {
  return (
    <section aria-label="Your data" className="mt-4">
      <MemoriesSection deps={deps} />
      <ExportSection deps={deps} />
      <EraseSection deps={deps} onErased={onErased} />
    </section>
  );
}
