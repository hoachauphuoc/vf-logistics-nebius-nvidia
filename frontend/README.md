# Floorline console

The Next.js 16 half of the `vf-app` container. In the deployed image it listens on
`$PORT`, the only port Cloud Run routes to, and reaches the Flask API on
`127.0.0.1:9090` behind it (the root `Dockerfile` and `entrypoint.sh` build and start
both). It is not deployed on its own, and not on Vercel.

## Run it locally

The console needs the API. From the repository root, start Flask (port 8080 by default):

```bash
PYTHONPATH=src python -m vf_logistics.app
```

Then, from `frontend/`:

```bash
npm ci
FLASK_API_BASE=http://127.0.0.1:8080 npm run dev    # http://localhost:3000
```

Without `FLASK_API_BASE` the console looks for the API at `http://127.0.0.1:9090`, the
address it has inside the container.

Sign-in and the console's other settings — `VF_SESSION_SECRET` (at least 32 characters,
required in production, where a missing one takes the console offline), `VF_OPERATORS`,
`VF_PUBLIC_READS`, `VF_ONE_CLICK_*` — are documented in the root `README.md`, under
*Signing in* and *Environment variables → Console*.

## Checks

```bash
npx tsc --noEmit    # typecheck
npm run lint
npm test            # 328 unit tests in 26 files (vitest)
npm run build
```

## Where things are

| Path | What it is |
|---|---|
| `src/app/` | App Router pages (the board at `/`, then radar, review, audit, governance, devops, agents, evaluation, admin, today, outcomes, cases, respond, legal, login) and the route handlers under `api/`, plus `health`, `metrics` and `demo` |
| `src/components/` | UI, including the case trace sheet and the layout shell |
| `src/app/api/proxy/[...path]/route.ts` | The console's BFF, and the only place the console's own API key is attached |
| `src/lib/proxy-policy.ts` | The allow-list that BFF enforces, including the routes a one-click session may not call |
| `src/lib/upstream.ts` | Transport to Flask, shared by the BFF and the public pass-through (`/api/v1/*`, `/health`, `/metrics`, `/demo`), which forwards only the caller's own credential |
| `src/lib/help-content.ts` | The help text behind every `?` on the screens |
| `src/proxy.ts` | The login door (Next 16 renamed `middleware` to `proxy`) |
| `scripts/make-operator.mjs` | Creates a PBKDF2 operator record; writes the password to a file |
