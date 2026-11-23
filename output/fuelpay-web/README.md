# FuelPay Web

Fleet fuel monitoring for the simulated 25–100 kVA diesel generators served by
`../fuelpay-service`. Vue 3 + Pinia + Tailwind + Ant Design.

## Running it

Two processes. The API first:

```bash
cd ../fuelpay-service
docker compose up            # db + api on :8000, seeds a demo fleet
```

Then this app:

```bash
npm install
npm run dev                  # http://localhost:5173
```

Sign in with the seeded key `dev-local-key-change-me`, or set
`VITE_FUELPAY_API_KEY` in `.env.local` to skip the gate. Point at an API on a
different host with `VITE_PROXY_TARGET=http://host:8000`.

### Why CORS is not a problem in dev

`vite.config.ts` proxies `/v1` to the API, so the browser sees a single origin.
The service also ships real CORS middleware (`FUELPAY_CORS_ALLOW_ORIGINS`),
which is what a deployed build relies on — a proxy only exists in development.

Do not add compression to the proxy or the API: it buffers, and buffering breaks
the SSE stream.

## Commands

| Command | What |
|---|---|
| `npm run dev` | dev server on :5173 |
| `npm run build` | type-check + production build |
| `npm run test:unit` | vitest — the pure modules |
| `npm run type-check` | `vue-tsc` |
| `npm run lint` | oxlint + eslint |

## Layout

```
src/
  api/          types.ts mirrors the service's schemas; client.ts is the only fetch
  stores/       auth (key), fleet (generators + sites + latest readings, joined)
  components/
    tank/       FuelTank.vue + its pure modules (geometry, wave, state) and specs
    fleet/      GeneratorCard
    layout/     AppShell, ApiKeyGate
  lib/          format.ts — display formatting, unit-tested
  theme/        tokens.ts — the single source of colour, feeds antd and Tailwind
  views/        FleetDashboard, GeneratorDetail, IncidentsFeed
```

## Things that will bite you

**Tailwind has no preflight here.** `ant-design-vue/dist/reset.css` is the only
reset — running two breaks antd's buttons and headings. The consequence is that
base rules preflight would have supplied are ours to write; there is an
`@layer base` block in `assets/main.css` for exactly that. Anchor decoration
lives there, and its absence underlines every card.

**antd's CSS is injected at runtime and unlayered**, so it beats layered
Tailwind utilities on antd elements regardless of source order. Style your own
markup with Tailwind, and antd through `ConfigProvider` tokens. If you must
override, v4's important modifier is a *suffix*: `bg-red-500!`.

**`@theme static`, not `@theme`.** v4 tree-shakes theme variables that no
utility references, and the tank reads `var(--color-tank-*)` directly from
component CSS. Without `static` they vanish from the build.

**Every `<defs>` id must be unique per instance.** Twelve tanks sharing
`id="clip"` all clip to the first one's shape. `useId()` handles it — keep it
that way.

**Reading timestamps can be in the future.** The simulator's `run_span` steps
until it passes its target, so the newest reading may be up to one tick ahead of
wall-clock. Use `secondsSince()`, which clamps at zero, rather than subtracting
dates yourself.

**Never recompute `fuel_level_pct` from litres.** The service models sensor
noise and 0.1 L quantisation deliberately; recomputing launders it away and
shows a cleaner tank than the probe reported.

## Not built yet

Live SSE updates, telemetry and consumption charts, and the incidents feed —
`/incidents` is still a placeholder.
