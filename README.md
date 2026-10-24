# Exactly As Shown

Implement exactly the screenshot and nothing else

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/5ca6fef9-2484-4133-b74c-9b0705d13ed3).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

## Architecture

This is a plain **Vite + React single-page app** (no SSR):

- Routing: React Router (`src/routes.tsx`) — `/`, `/signin`, `/signup`, and `/app` (requires sign-in via `RequireAuth`).
- Auth: the app's own Supabase project (`rrbbrhhiicrucwzdaavt`), via the single browser client in `src/integrations/supabase/client.ts`. It reads `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` (the `sb_publishable_*` key, which replaces the legacy anon key) at build time.
- Build: `npm run build` emits a static site to `dist/`.

## Deploying to Vercel

`vercel.json` sets the Vite framework preset, `dist/` as the output directory, and an SPA fallback rewrite so deep links such as `/app` load `index.html` and resolve client-side. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` to the Vercel project's environment variables (same values as `.env`) so they are available at build time.

## Fare alerts backend (M1)

The subscribe UI on `/app` calls an AWS HTTP API (`VITE_FLIGHT_API_URL`); the browser holds no AWS credentials. Lambda sources live in `aws/lambdas/`:

| Lambda | Role |
| --- | --- |
| `save_subscription` | `POST /subscribe` → upserts a row in DynamoDB `subscriptions` (PK `email`, SK `route`); plans: tokyo (TPE-TYO), seoul (TPE-SEL), london (TPE-LON) |
| `list_subscriptions` | `GET /subscriptions?email=` → the user's rows (no auth yet — production should verify the Supabase JWT) |
| `parser_wrapper` | EventBridge `rate(30 minutes)` → reads `flight-routes.json` from S3, fans out one parser per route |
| `parser` | Next month's cheapest fare from Travelpayouts (TWD gate, USD extra) → enqueues matches to SQS `flight-fare-queue` |
| `fare_notification` | SQS consumer → dedups via `notification_history` (24h floor, re-alert on ≥20% or ≥NT$2,000 drop) → emails via Resend |

API keys are read at runtime from AWS Secrets Manager (`flight/travelpayouts`, `flight/resend`) — never commit them.
