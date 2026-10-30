import { cn } from "@/lib/utils";

/** The neuron mark: three linked nodes on the brand colour. Decorative; the name is text beside it. */
export function Logo({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand/70 text-brand-foreground shadow-sm ring-1 ring-brand/20",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" fill="none" className="size-[60%]">
        <path
          d="M6 17.5 12 6.5l6 11H6Z"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinejoin="round"
          opacity="0.55"
        />
        <circle cx="12" cy="6.5" r="2.5" fill="currentColor" />
        <circle cx="6" cy="17.5" r="2.5" fill="currentColor" />
        <circle cx="18" cy="17.5" r="2.5" fill="currentColor" />
      </svg>
    </span>
  );
}
