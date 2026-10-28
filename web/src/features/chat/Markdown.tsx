import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";

/**
 * Model output is untrusted (ADR 0010, decision 7). This renders it as React elements only:
 * raw HTML in the text stays literal text, images are never loaded (an image URL is an
 * exfiltration channel), code is text, and only absolute http(s) and mailto links become
 * anchors, each opening in a new tab with its target shown next to the label.
 */
const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);
const LABEL_LIMIT = 60;

function parseSafeUrl(href: string): URL | null {
  try {
    const url = new URL(href);
    return ALLOWED_PROTOCOLS.has(url.protocol) ? url : null;
  } catch {
    return null; // relative, protocol-relative and malformed URLs are not links
  }
}

/** Everything unsafe becomes an empty URL; the components below then render plain text. */
function urlTransform(href: string): string {
  return parseSafeUrl(href)?.href ?? "";
}

function SafeLink({ href, children }: ComponentProps<"a">) {
  const url = href === undefined ? null : parseSafeUrl(href);
  if (url === null) return <span>{children}</span>;
  const target = url.protocol === "mailto:" ? url.pathname : url.host;
  return (
    <>
      <a href={url.href} target="_blank" rel="noopener noreferrer nofollow" className="underline">
        {children}
      </a>
      <span className="text-xs opacity-70"> ({target.slice(0, LABEL_LIMIT)})</span>
    </>
  );
}

function OmittedImage({ alt }: ComponentProps<"img">) {
  return (
    <span className="italic opacity-70">
      [image not shown{alt === undefined || alt === "" ? "" : `: ${alt.slice(0, LABEL_LIMIT)}`}]
    </span>
  );
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-2 break-words [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:border [&_pre]:p-2">
      <ReactMarkdown urlTransform={urlTransform} components={{ a: SafeLink, img: OmittedImage }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
