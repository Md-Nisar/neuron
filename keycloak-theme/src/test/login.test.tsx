import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import { renderPage } from "./renderPage";
import { setPrefersDark } from "./setup";

const messagesPerField = (errors: Record<string, string>) => ({
    get: (name: string) => errors[name] ?? "",
    existsError: (...names: string[]) => names.some(name => name in errors),
    exists: (name: string) => name in errors,
    printIfExists: <T,>(name: string, text: T) => (name in errors ? text : undefined),
    getFirstError: (...names: string[]) => errors[names.find(name => name in errors) ?? ""] ?? ""
});

describe("login page: form", () => {
    it("shows the username/email and password fields, remember me, forgot password and sign in", async () => {
        await renderPage("login.ftl");

        expect(screen.getByLabelText("Username or email")).toHaveAttribute("name", "username");
        expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
        expect(screen.getByRole("checkbox", { name: "Remember me" })).not.toBeChecked();
        expect(screen.getByRole("link", { name: "Forgot Password?" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Sign In" })).toHaveAttribute("type", "submit");
        expect(screen.getByRole("link", { name: "Sign up" })).toBeInTheDocument();
    });

    it("submits natively to Keycloak's login action and handles no credentials itself", async () => {
        const { container } = await renderPage("login.ftl", {
            url: { loginAction: "https://kc.test/realms/neuron/login-actions/authenticate?x=1" }
        });

        const form = container.querySelector("form#kc-form-login");
        expect(form).toHaveAttribute(
            "action",
            "https://kc.test/realms/neuron/login-actions/authenticate?x=1"
        );
        expect(form).toHaveAttribute("method", "post");
        // Only plain form fields go to Keycloak; no fetch/XHR is made by the page itself.
        const names = [...(form as HTMLFormElement).elements].map(
            e => (e as HTMLInputElement).name
        );
        expect(names).toEqual(
            expect.arrayContaining(["username", "password", "rememberMe", "credentialId", "login"])
        );
    });

    it("posts the typed values, including remember me, as a normal form submission", async () => {
        const user = userEvent.setup();
        const fetchSpy = vi.spyOn(globalThis, "fetch");
        const { container } = await renderPage("login.ftl");
        const form = container.querySelector("form#kc-form-login") as HTMLFormElement;
        let submitted: FormData | undefined;
        form.addEventListener("submit", event => {
            event.preventDefault();
            submitted = new FormData(form);
        });

        await user.type(screen.getByLabelText("Username or email"), "alice@example.com");
        await user.type(screen.getByLabelText("Password"), "s3cret!");
        await user.click(screen.getByRole("checkbox", { name: "Remember me" }));
        await user.click(screen.getByRole("button", { name: "Sign In" }));

        expect(submitted?.get("username")).toBe("alice@example.com");
        expect(submitted?.get("password")).toBe("s3cret!");
        expect(submitted?.get("rememberMe")).toBe("on");
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("submits with Enter from the password field", async () => {
        const user = userEvent.setup();
        const { container } = await renderPage("login.ftl");
        const form = container.querySelector("form#kc-form-login") as HTMLFormElement;
        const onSubmit = vi.fn((event: Event) => event.preventDefault());
        form.addEventListener("submit", onSubmit);

        await user.type(screen.getByLabelText("Password"), "pw{Enter}");

        expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    it("disables Sign In after a submit so a second click cannot double-post", async () => {
        const user = userEvent.setup();
        const { container } = await renderPage("login.ftl");
        container
            .querySelector("form#kc-form-login")!
            .addEventListener("submit", event => event.preventDefault());

        await user.click(screen.getByRole("button", { name: "Sign In" }));

        await waitFor(() => expect(screen.getByRole("button", { name: "Sign In" })).toBeDisabled());
    });

    it("prefills the username Keycloak sends back and the remember-me state", async () => {
        await renderPage("login.ftl", { login: { username: "bob", rememberMe: "on" } });

        expect(screen.getByLabelText("Username or email")).toHaveValue("bob");
        expect(screen.getByRole("checkbox", { name: "Remember me" })).toBeChecked();
    });
});

describe("login page: buttons", () => {
    it("shows and hides the password", async () => {
        const user = userEvent.setup();
        await renderPage("login.ftl");
        const password = screen.getByLabelText("Password");
        await user.type(password, "s3cret");

        await user.click(screen.getByRole("button", { name: "Show password" }));
        expect(password).toHaveAttribute("type", "text");
        expect(password).toHaveValue("s3cret");

        await user.click(screen.getByRole("button", { name: "Hide password" }));
        expect(password).toHaveAttribute("type", "password");
    });

    it("toggles remember me by its box, its label and the keyboard", async () => {
        const user = userEvent.setup();
        await renderPage("login.ftl");
        const box = screen.getByRole("checkbox", { name: "Remember me" });

        await user.click(box);
        expect(box).toBeChecked();
        await user.click(screen.getByText("Remember me"));
        expect(box).not.toBeChecked();
        box.focus();
        await user.keyboard(" ");
        expect(box).toBeChecked();
    });

    it("links forgot password and sign up to the URLs Keycloak provides", async () => {
        await renderPage("login.ftl", {
            url: {
                loginResetCredentialsUrl: "https://kc.test/reset",
                registrationUrl: "https://kc.test/register"
            }
        });

        expect(screen.getByRole("link", { name: "Forgot Password?" })).toHaveAttribute(
            "href",
            "https://kc.test/reset"
        );
        expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute(
            "href",
            "https://kc.test/register"
        );
    });

    it("hides remember me, forgot password and sign up when the realm turns them off", async () => {
        await renderPage("login.ftl", {
            realm: { rememberMe: false, resetPasswordAllowed: false, registrationAllowed: false }
        });

        expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Forgot Password?" })).not.toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Sign up" })).not.toBeInTheDocument();
    });

    it("sends the home button to the client's base URL, never to a URL parameter", async () => {
        window.history.replaceState({}, "", "/?redirect_url=https://evil.example");
        await renderPage("login.ftl", { client: { baseUrl: "https://app.test" } });
        expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute(
            "href",
            "https://app.test"
        );
        window.history.replaceState({}, "", "/");
    });

    it("falls back to # when the client has no base URL", async () => {
        window.history.replaceState({}, "", "/?redirect_url=https://evil.example");
        await renderPage("login.ftl", { client: { baseUrl: undefined } });
        expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "#");
        window.history.replaceState({}, "", "/");
    });
});

describe("login page: theme toggle", () => {
    it("switches light to dark and back, and remembers the choice", async () => {
        const user = userEvent.setup();
        await renderPage("login.ftl");
        const root = document.documentElement;
        expect(root).toHaveClass("light");

        // Following the OS (light), the first click must go to dark.
        await user.click(screen.getByRole("button", { name: "Switch to dark mode" }));
        expect(root).toHaveClass("dark");
        expect(window.localStorage.getItem("isDarkMode")).toBe("dark");

        await user.click(screen.getByRole("button", { name: "Switch to light mode" }));
        expect(root).toHaveClass("light");
        expect(root).not.toHaveClass("dark");
        expect(window.localStorage.getItem("isDarkMode")).toBe("light");
    });

    it("goes to light on the first click when the OS prefers dark", async () => {
        setPrefersDark(true);
        const user = userEvent.setup();
        await renderPage("login.ftl");
        expect(document.documentElement).toHaveClass("dark");

        await user.click(screen.getByRole("button", { name: "Switch to light mode" }));

        expect(document.documentElement).toHaveClass("light");
    });

    it("restores the saved choice on the next visit", async () => {
        window.localStorage.setItem("isDarkMode", "dark");
        await renderPage("login.ftl");

        expect(document.documentElement).toHaveClass("dark");
        expect(screen.getByRole("button", { name: "Switch to light mode" })).toBeInTheDocument();
    });
});

describe("login page: language picker", () => {
    it("lists the realm's languages as links to Keycloak's locale URLs", async () => {
        const user = userEvent.setup();
        await renderPage("login.ftl", {
            locale: {
                currentLanguageTag: "en",
                supported: [
                    { languageTag: "en", label: "English", url: "https://kc.test/?kc_locale=en" },
                    { languageTag: "de", label: "Deutsch", url: "https://kc.test/?kc_locale=de" }
                ]
            }
        });

        await user.click(screen.getByRole("button", { name: "Languages" }));

        const menu = await screen.findByRole("menu");
        expect(within(menu).getAllByRole("menuitem")).toHaveLength(2);
        expect(within(menu).getByRole("menuitem", { name: "Deutsch" })).toHaveAttribute(
            "href",
            "https://kc.test/?kc_locale=de"
        );
    });

    it("closes with Escape", async () => {
        const user = userEvent.setup();
        await renderPage("login.ftl");
        await user.click(screen.getByRole("button", { name: "Languages" }));
        await screen.findByRole("menu");

        await user.keyboard("{Escape}");

        await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    });
});

describe("login page: Keycloak messages and validation", () => {
    it("marks both fields invalid and shows Keycloak's error text", async () => {
        await renderPage("login.ftl", {
            messagesPerField: messagesPerField({ username: "Invalid username or password." }),
            message: { type: "error", summary: "Invalid username or password." }
        } as never);

        expect(screen.getByLabelText("Username or email")).toHaveAttribute("aria-invalid", "true");
        expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
        expect(screen.getAllByText("Invalid username or password.").length).toBeGreaterThan(0);
    });

    it("shows a Keycloak info message above the form", async () => {
        await renderPage("login.ftl", {
            message: { type: "info", summary: "You have been logged out." }
        });

        expect(screen.getByText("You have been logged out.")).toBeInTheDocument();
    });

    it("sanitises HTML in Keycloak's error text", async () => {
        await renderPage("login.ftl", {
            messagesPerField: messagesPerField({
                username: 'Bad <img src=x onerror="window.__xss=1"> input'
            })
        } as never);

        expect(document.querySelector("img[onerror]")).toBeNull();
        expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
    });
});

describe("login page: accessibility", () => {
    it("has no axe violations (colour contrast needs a real browser)", async () => {
        const { container } = await renderPage("login.ftl");
        document.documentElement.lang = "en";
        document.title = "Sign in";

        const results = await axe.run(container, {
            rules: { "color-contrast": { enabled: false }, region: { enabled: false } }
        });

        expect(
            results.violations.map(v => `${v.id}: ${v.nodes.map(n => n.target).join(",")}`)
        ).toEqual([]);
    });
});
