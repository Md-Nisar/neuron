import { render, screen } from "@testing-library/react";
import KcPage from "@/login/KcPage";
import { getKcContextMock } from "@/login/mocks/getKcContextMock";

type Params = Parameters<typeof getKcContextMock>[0];

/** Renders one Keycloak page with the mock context and waits for its lazy chunk to load. */
export async function renderPage<T extends Params["pageId"]>(
    pageId: T,
    overrides: Extract<Params, { pageId: T }>["overrides"] = {} as never
) {
    const kcContext = getKcContextMock({ pageId, overrides } as Params);
    const result = render(<KcPage kcContext={kcContext} />);
    await screen.findByRole("button", { name: /switch to/i });
    return { kcContext, ...result };
}
