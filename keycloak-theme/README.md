# neuron-keycloak-theme

Keycloak **login** theme for Neuron, built with Keycloakify 11, React, TypeScript, Tailwind CSS v4 and
shadcn/ui. It is based on the shadcn starter
([`@keycloakify/login-ui`](https://www.npmjs.com/package/@keycloakify/login-ui) and
[Oussemasahbeni/keycloakify-shadcn-starter](https://github.com/Oussemasahbeni/keycloakify-shadcn-starter)),
without the email and Storybook extras.

The theme only renders Keycloak's own pages and forms. Credentials, validation, password reset, OTP,
WebAuthn and session handling stay in Keycloak. The theme adds no auth API and handles no passwords itself.

## Commands

```bash
npm ci                       # Node 22, Maven and a JDK are needed for the JAR
npm run dev                  # preview the login page with mock Keycloak context
npm run build-keycloak-theme # writes dist_keycloak/neuron-theme.jar
npm run typecheck
npm test                     # Vitest + Testing Library against the Keycloak mock context
npm run format:check
```

## Deploy

Copy `dist_keycloak/neuron-theme.jar` to Keycloak's `providers/` directory (or mount it at
`/opt/keycloak/providers/`), then set **Realm settings -> Themes -> Login theme** to `neuron`
(or `"loginTheme": "neuron"` in the realm JSON). To try it locally:

```bash
npx keycloakify start-keycloak
```

## Configuration

Set these environment variables on the Keycloak server (defaults are in `vite.config.ts`):
`SHADCN_THEME_LAYOUT` (`two-column`, `centered-card`, `image-aside`), `SHADCN_THEME_PRESET`,
`SHADCN_THEME_BASE`, `SHADCN_THEME_RADIUS`, `SHADCN_THEME_FONT`, `SHADCN_THEME_PLACEHOLDER`,
`SHADCN_THEME_LOGO_WHITE_URL`, `SHADCN_THEME_LOGO_DARK_URL`, `SHADCN_THEME_SIDE_IMAGE_URL`.
