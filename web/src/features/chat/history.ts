import { count, list, record, str } from "@/features/data/parse";

import type { ChatMessage, SkippedTool } from "./chatState";

/** Shape checks for `GET /v1/threads/{id}/messages`, and its mapping onto chat messages. */

const MAX_NAME_CHARS = 64;
const STATUSES = ["pending", "completed", "failed", "rejected"] as const;
type ToolStatus = (typeof STATUSES)[number];

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  tools: { name: string; status: ToolStatus }[];
}

export interface HistoryPage {
  messages: HistoryMessage[];
  total: number;
}

function parseMessage(value: unknown): HistoryMessage {
  const item = record(value);
  const role = str(item, "role");
  if (role !== "user" && role !== "assistant") throw new TypeError("shape");
  const calls = item["tool_calls"] === undefined ? [] : list(item, "tool_calls");
  return {
    role,
    content: str(item, "content"),
    tools: calls.map((call) => {
      const entry = record(call);
      const status = str(entry, "status");
      if (!STATUSES.includes(status as ToolStatus)) throw new TypeError("shape");
      // The summary of the arguments is not shown: the approval card shows them in full.
      return { name: str(entry, "name").slice(0, MAX_NAME_CHARS), status: status as ToolStatus };
    }),
  };
}

export function parseHistory(body: unknown): HistoryPage {
  const page = record(body);
  return { messages: list(page, "messages").map(parseMessage), total: count(page, "total") };
}

/** What the server recorded for each tool call, never inferred from the assistant's wording. */
export function toChatMessages(history: HistoryMessage[], newId: () => string): ChatMessage[] {
  return history.map((message) => {
    const skipped: SkippedTool[] = message.tools
      .filter((tool) => tool.status !== "completed")
      .map((tool) => ({ name: tool.name, why: tool.status as SkippedTool["why"] }));
    return {
      id: newId(),
      role: message.role,
      text: message.content,
      toolCalls: message.tools.filter((tool) => tool.status === "completed").map((t) => t.name),
      skipped,
      runId: null,
      status: skipped.some((tool) => tool.why === "pending") ? "needs_approval" : "done",
      failure: null,
      approval: null,
    };
  });
}
