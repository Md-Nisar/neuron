const MESSAGE_TYPE = "neuron-auth-callback";
const FRAME_TIMEOUT_MS = 10_000;

/**
 * Run in the silent-renew iframe: if this page was loaded as the sign-in callback inside a
 * frame, hand the callback URL to the parent (same origin only) and tell the caller not to
 * start the app. Returns true when it did.
 */
export function reportFrameCallback(win: Window = window): boolean {
  if (win.self === win.top) return false;
  const params = new URL(win.location.href).searchParams;
  if (!params.has("code") && !params.has("error")) return false;
  win.parent.postMessage({ type: MESSAGE_TYPE, href: win.location.href }, win.location.origin);
  return true;
}

/**
 * Load an authorization URL (`prompt=none`) in a hidden frame and resolve with the callback URL
 * the frame reports. Only a message from that frame, from this origin, with the right shape
 * counts; a timeout rejects. The frame is always removed.
 */
export function runAuthFrame(
  url: string,
  doc: Document = document,
  timeoutMs: number = FRAME_TIMEOUT_MS,
): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const frame = doc.createElement("iframe");
    frame.setAttribute("aria-hidden", "true");
    frame.tabIndex = -1;
    frame.style.display = "none";
    const win = doc.defaultView;
    if (win === null) {
      reject(new Error("no window"));
      return;
    }
    const finish = (settle: () => void): void => {
      win.removeEventListener("message", onMessage);
      win.clearTimeout(timer);
      frame.remove();
      settle();
    };
    const onMessage = (event: MessageEvent): void => {
      const data = event.data as { type?: unknown; href?: unknown } | null;
      if (
        event.origin !== win.location.origin ||
        event.source !== frame.contentWindow ||
        data?.type !== MESSAGE_TYPE ||
        typeof data.href !== "string"
      ) {
        return;
      }
      const href = data.href;
      finish(() => {
        resolve(href);
      });
    };
    const timer = win.setTimeout(() => {
      finish(() => {
        reject(new Error("silent renew timed out"));
      });
    }, timeoutMs);
    win.addEventListener("message", onMessage);
    frame.src = url;
    doc.body.append(frame);
  });
}
