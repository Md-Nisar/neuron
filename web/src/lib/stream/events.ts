/**
 * The seven events of `POST /v1/agent/stream` (protocol version 1), validated at runtime.
 *
 * Payloads are model- and tool-influenced text: they are checked for shape here and rendered
 * as text only. An unknown event name is ignored (additive protocol changes); a known event
 * with a bad payload is a protocol error. Error messages name the event, never its content.
 */

export type Decision = "approve" | "reject";

export interface FinalResponse {
  request_id: string;
  thread_id: string;
  run_id?: string;
  answer: string;
  used_tools: string[];
  confidence: number;
  refused: boolean;
  clarification_needed: boolean;
}

export interface PendingAction {
  name: string;
  args: Record<string, unknown>;
}

export interface ApprovalRequired {
  request_id: string;
  thread_id: string;
  approval: {
    approval_id: string;
    actions: PendingAction[];
    allowed_decisions: Decision[];
  };
}

export type StreamEvent =
  | { type: "run_started"; data: { request_id: string; thread_id: string; run_id?: string } }
  | { type: "token"; data: { text: string } }
  | { type: "tool_call"; data: { name: string } }
  | { type: "final"; data: FinalResponse }
  | { type: "approval_required"; data: ApprovalRequired }
  | { type: "error"; data: { code: string; retryable: boolean } }
  | { type: "done"; data: Record<string, never> };

/** A known event arrived with data that is not valid JSON or has the wrong shape. */
export class StreamProtocolError extends Error {
  constructor(
    readonly reason: "malformed_event_data" | "invalid_event_payload",
    readonly eventName: string,
  ) {
    super(`${reason} in "${eventName}" event`);
    this.name = "StreamProtocolError";
  }
}

const SAFE_CODE = /^[a-z0-9_]{1,64}$/;
/**
 * Ids from the server are put into URL paths. The same characters the API accepts for an
 * approval id, with at least one letter or digit so an id can never be `.` or `..`, which URL
 * normalisation would resolve out of the path.
 */
export const SAFE_ID = /^(?=.*[A-Za-z0-9])[A-Za-z0-9_.:-]{1,128}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  return typeof value === "string" ? value : undefined;
}

function invalid(name: string): never {
  throw new StreamProtocolError("invalid_event_payload", name);
}

function parseFinal(name: string, p: Record<string, unknown>): FinalResponse {
  const { answer, confidence, refused, clarification_needed, used_tools } = p;
  const requestId = text(p, "request_id");
  const threadId = text(p, "thread_id");
  if (
    typeof answer !== "string" ||
    requestId === undefined ||
    threadId === undefined ||
    typeof confidence !== "number" ||
    typeof refused !== "boolean" ||
    typeof clarification_needed !== "boolean" ||
    !Array.isArray(used_tools) ||
    !used_tools.every((tool) => typeof tool === "string")
  ) {
    return invalid(name);
  }
  const runId = text(p, "run_id");
  return {
    request_id: requestId,
    thread_id: threadId,
    ...(runId === undefined ? {} : { run_id: runId }),
    answer,
    used_tools,
    confidence,
    refused,
    clarification_needed,
  };
}

function parseApproval(name: string, p: Record<string, unknown>): ApprovalRequired {
  const requestId = text(p, "request_id");
  const threadId = text(p, "thread_id");
  const approval = p["approval"];
  if (requestId === undefined || threadId === undefined || !isRecord(approval)) {
    return invalid(name);
  }
  const approvalId = text(approval, "approval_id");
  const { actions, allowed_decisions } = approval;
  if (
    approvalId === undefined ||
    !SAFE_ID.test(approvalId) ||
    !SAFE_ID.test(threadId) ||
    !Array.isArray(actions) ||
    !Array.isArray(allowed_decisions)
  ) {
    return invalid(name);
  }
  const parsedActions = actions.map((action: unknown): PendingAction => {
    if (!isRecord(action)) return invalid(name);
    const actionName = text(action, "name");
    const args = action["args"];
    if (actionName === undefined || !isRecord(args)) return invalid(name);
    return { name: actionName, args };
  });
  const decisions = allowed_decisions.filter(
    (d: unknown): d is Decision => d === "approve" || d === "reject",
  );
  if (parsedActions.length === 0 || decisions.length === 0) return invalid(name);
  return {
    request_id: requestId,
    thread_id: threadId,
    approval: { approval_id: approvalId, actions: parsedActions, allowed_decisions: decisions },
  };
}

/** Turn one SSE message into a typed event; `null` for an event this client does not know. */
export function parseStreamEvent(name: string, raw: string): StreamEvent | null {
  switch (name) {
    case "run_started":
    case "token":
    case "tool_call":
    case "final":
    case "approval_required":
    case "error":
    case "done":
      break;
    default:
      return null;
  }
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new StreamProtocolError("malformed_event_data", name);
  }
  if (!isRecord(payload)) return invalid(name);

  switch (name) {
    case "run_started": {
      const requestId = text(payload, "request_id");
      const threadId = text(payload, "thread_id");
      if (requestId === undefined || threadId === undefined) return invalid(name);
      const runId = text(payload, "run_id");
      return {
        type: "run_started",
        data: {
          request_id: requestId,
          thread_id: threadId,
          ...(runId === undefined ? {} : { run_id: runId }),
        },
      };
    }
    case "token": {
      const value = text(payload, "text");
      return value === undefined ? invalid(name) : { type: "token", data: { text: value } };
    }
    case "tool_call": {
      const value = text(payload, "name");
      return value === undefined ? invalid(name) : { type: "tool_call", data: { name: value } };
    }
    case "final":
      return { type: "final", data: parseFinal(name, payload) };
    case "approval_required":
      return { type: "approval_required", data: parseApproval(name, payload) };
    case "error": {
      const code = text(payload, "code");
      return {
        type: "error",
        data: {
          code: code !== undefined && SAFE_CODE.test(code) ? code : "unknown_error",
          retryable: payload["retryable"] === true,
        },
      };
    }
    default:
      return { type: "done", data: {} };
  }
}
