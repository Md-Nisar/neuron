import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { KcPage } from "./kc.gen";
import { getKcContextMock } from "./login/mocks/getKcContextMock";

const kcContext = getKcContextMock({
    pageId: "login.ftl",
    overrides: { realm: { name: "neuron", displayName: "neuron", displayNameHtml: "neuron" } }
});

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <KcPage kcContext={kcContext} />
    </StrictMode>
);
