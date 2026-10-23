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
