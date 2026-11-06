import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import contract from "@/lib/stream/contract.json";
import { SignedInView } from "@/SignedInView";
import { accessibilityViolations } from "@/test/axe";
import { fakeApi, thread, type FakeMessage } from "@/test/dataApi";
import { frame, sseResponse, streamOf } from "@/test/sse";

import { pagesText } from "./Sources";

const ID = thread(1, 0).thread_id;
const CITED = contract.payloads.final_with_citations;
const SECOND = {
  ...CITED.citations[0],
  cite_id: "c2",
  chunk_id: "2d0f8c74-5e3f-4a91-9c4d-7e8f9a0b1c2d",
  title: "Handbook",
  headings: [],
  page_start: 7,
  page_end: 7,
};
const FIELDS = {
  citations: [...CITED.citations, SECOND],
  citation_schema_version: 1,
  grounded: true,
};

/** A signed-in page whose stream answers with `final`, and whose one thread holds `stored`. */
function setup(final: Record<string, unknown>, stored: FakeMessage[] = []) {
  const api = fakeApi({
    memories: [],
    threads: [{ ...thread(1, 0), title: "Past", messages: stored }],
  });
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input, init) => {
      const url = new URL(input instanceof URL ? input.href : (input as string));
      if (init?.method === "POST" && url.pathname.endsWith("/stream")) {
        return Promise.resolve(
          sseResponse(
            streamOf([
              frame("run_started", { request_id: "r1", thread_id: ID }),
              frame("final", { ...CITED, thread_id: ID, ...final }),
              frame("done", {}),
            ]),
          ),
        );
      }
      return api.fetch(input, init);
    }),
  );
  const view = render(
    <SignedInView
      auth={{
        displayName: "alice",
        getAccessToken: () => "t",
        sessionEnded: vi.fn(),
        signOut: vi.fn(),
      }}
      apiUrl="http://127.0.0.1:8000"
      maxChars={12_000}
    />,
  );
  const user = userEvent.setup();
  const send = () => user.type(screen.getByLabelText("Message"), "How much leave?{Enter}");
  const ask = async () => {
    await send();
    await screen.findByText(CITED.answer);
  };
  const open = async () => {
    await user.click(await screen.findByRole("button", { name: "Open Past" }));
  };
  return { ask, send, open, view };
}

const chips = async () =>
  within(await screen.findByRole("list", { name: "Sources" }))
    .getAllByRole("listitem")
    .map((item) => item.textContent);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sources under an answer", () => {
  it("numbers the cited passages with their title and pages", async () => {
    const { ask } = setup(FIELDS);
    await ask();

    expect(await chips()).toEqual(["1Leave policypp. 3–4", "2Handbookp. 7"]);
    expect(screen.queryByText(/Not grounded/)).toBeNull();
  });

  it("shows the same chips when the thread is reloaded as when it was streamed", async () => {
    const streamed = setup(FIELDS);
    await streamed.ask();
    const live = await chips();
    streamed.view.unmount();

    const reloaded = setup({}, [
      { role: "user", content: "How much leave?" },
      { role: "assistant", content: CITED.answer, run_id: CITED.run_id, ...FIELDS },
    ]);
    await reloaded.open();

    expect(await chips()).toEqual(live);
  });

  it("says when an answer that searched knowledge is not grounded", async () => {
    const { ask, view } = setup({ citations: [], grounded: false });
    await ask();

    expect(screen.getByText(/Not grounded/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();
    expect(await accessibilityViolations(view.container)).toEqual([]);
  });

  it("shows nothing for an answer without knowledge or of an unknown schema version", async () => {
    const { ask } = setup({ citations: null, citation_schema_version: 2, grounded: false });
    await ask();

    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();
    expect(screen.queryByText(/Not grounded/)).toBeNull();
  });

  it("refuses a citation whose ids are not the server's UUIDs", async () => {
    const { send } = setup({ citations: [{ ...SECOND, chunk_id: "../../files" }] });
    await send();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(CITED.answer)).toBeNull();
    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();
  });
});

describe("pagesText", () => {
  it("names one page, a range, or none", () => {
    expect(pagesText({ page_start: 3, page_end: 3 })).toBe("p. 3");
    expect(pagesText({ page_start: 3, page_end: null })).toBe("p. 3");
    expect(pagesText({ page_start: 3, page_end: 5 })).toBe("pp. 3–5");
    expect(pagesText({ page_start: null, page_end: null })).toBe("");
  });
});
