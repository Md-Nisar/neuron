import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderPage } from "./renderPage";

/** Stops jsdom from navigating and returns the submitted fields. */
function captureSubmit(form: HTMLFormElement) {
    const handler = vi.fn((event: Event) => event.preventDefault());
    form.addEventListener("submit", handler);
    return { handler, data: () => new FormData(form) };
}

describe("password reset", () => {
    it("asks for a username or email and posts it to Keycloak", async () => {
        const user = userEvent.setup();
        const { container } = await renderPage("login-reset-password.ftl", {
            url: { loginAction: "https://kc.test/reset-action", loginUrl: "https://kc.test/login" }
        });
        const form = container.querySelector("form") as HTMLFormElement;
        expect(form).toHaveAttribute("action", "https://kc.test/reset-action");
        expect(form).toHaveAttribute("method", "post");
        const submit = captureSubmit(form);

        await user.type(screen.getByRole("textbox"), "alice@example.com");
        await user.click(screen.getByRole("button", { name: /submit/i }));

        expect(submit.handler).toHaveBeenCalledTimes(1);
        expect(submit.data().get("username")).toBe("alice@example.com");
    });

    it("links back to the login page", async () => {
        await renderPage("login-reset-password.ftl", {
            url: { loginUrl: "https://kc.test/login" }
        });

        expect(document.getElementById("backToApplication")).toHaveAttribute(
            "href",
            "https://kc.test/login"
        );
    });
});

describe("one-time password (MFA)", () => {
    it("posts the code to Keycloak's login action", async () => {
        const user = userEvent.setup();
        const { container } = await renderPage("login-otp.ftl", {
            url: { loginAction: "https://kc.test/otp-action" }
        });
        const form = container.querySelector("form") as HTMLFormElement;
        expect(form).toHaveAttribute("action", "https://kc.test/otp-action");
        expect(form).toHaveAttribute("method", "post");
        const submit = captureSubmit(form);

        await user.type(container.querySelector("input[name=otp]") as HTMLInputElement, "123456");
        await user.click(screen.getByRole("button", { name: "Sign In" }));

        expect(submit.handler).toHaveBeenCalledTimes(1);
        expect(submit.data().get("otp")).toBe("123456");
    });

    it("shows Keycloak's error for a wrong code", async () => {
        await renderPage("login-otp.ftl", {
            messagesPerField: {
                get: () => "Invalid authenticator code.",
                existsError: () => true,
                exists: () => true,
                printIfExists: <T,>(_: string, text: T) => text,
                getFirstError: () => "Invalid authenticator code."
            }
        } as never);

        expect(screen.getAllByText("Invalid authenticator code.").length).toBeGreaterThan(0);
    });
});

describe("password update", () => {
    it("posts the new password and confirmation to Keycloak", async () => {
        const user = userEvent.setup();
        const { container } = await renderPage("login-update-password.ftl", {
            url: { loginAction: "https://kc.test/update-action" }
        });
        const form = container.querySelector("form") as HTMLFormElement;
        expect(form).toHaveAttribute("action", "https://kc.test/update-action");
        const submit = captureSubmit(form);

        await user.type(container.querySelector("input[name=password-new]")!, "N3w-pass!");
        await user.type(container.querySelector("input[name=password-confirm]")!, "N3w-pass!");
        await user.click(screen.getByRole("button", { name: /submit/i }));

        expect(submit.data().get("password-new")).toBe("N3w-pass!");
        expect(submit.data().get("password-confirm")).toBe("N3w-pass!");
    });
});

describe("sessions and errors", () => {
    it("offers 'log out of other sessions' on the password update form", async () => {
        const { container } = await renderPage("login-update-password.ftl");

        expect(container.querySelector("input[name=logout-sessions]")).toBeInTheDocument();
    });

    it("confirms logout with a button that posts to Keycloak", async () => {
        const { container } = await renderPage("logout-confirm.ftl", {
            url: { logoutConfirmAction: "https://kc.test/logout" }
        });

        expect(container.querySelector("form")).toHaveAttribute("action", "https://kc.test/logout");
        expect(screen.getByRole("button", { name: /logout/i })).toBeInTheDocument();
    });

    it("shows the expired-page notice with links to restart or continue", async () => {
        await renderPage("login-page-expired.ftl", {
            url: {
                loginRestartFlowUrl: "https://kc.test/restart",
                loginAction: "https://kc.test/continue"
            }
        });

        expect(
            screen.getAllByRole("link", { name: /click here/i }).map(a => a.getAttribute("href"))
        ).toEqual(["https://kc.test/restart", "https://kc.test/continue"]);
    });

    it("renders Keycloak's error page message", async () => {
        await renderPage("error.ftl", { message: { type: "error", summary: "Something broke." } });

        expect(screen.getByText("Something broke.")).toBeInTheDocument();
    });
});
