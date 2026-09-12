# ADR 0005: Serve the SPA with an explicit document base

## Status

Accepted.

## Context

The Vite build uses relative asset URLs so the same build can be served below a
Home Assistant ingress prefix. A relative URL such as `./assets/app.js` resolves
against `/tonesets/` after a direct reload of `/tonesets/new`, which requests
`/tonesets/assets/app.js`. A test-only HTML injection hid that product defect.

## Decision

The backend owns the document base. It serves the built `index.html` and
ensures it contains one `<base>` element. The base is `/` for ordinary requests
and is the normalized `X-Ingress-Path` only when `AuthState.ingress_valid()`
accepts the Supervisor peer and add-on mode. The React router uses that base as
its basename, and the existing URL helpers resolve API and WebSocket URLs from
the same document base.

The backend serves static files only from the configured web root after a
resolved-path containment check. Hashed assets are immutable; the HTML is
revalidated on every request. API and health routes remain ahead of the SPA
fallback and keep the API CSP.

## Consequences

Root deep links and ingress deep links use the same build and URL rules. An
untrusted client cannot select an ingress base by sending the header. The
backend must read and lightly transform the HTML document, and deployments
must provide a built SPA in the configured web root.
