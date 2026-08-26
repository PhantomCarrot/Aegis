# Aegis — frontend

Next.js (App Router). See the [root README](../README.md) for the full quickstart and [`../docs/architecture.md`](../docs/architecture.md) to understand how this frontend fits with the backend.

```bash
cp .env.example .env.local
npm install
npm run dev   # → http://localhost:3000
```

The browser never talks to the backend directly: everything goes through the authenticated proxy in [`app/api/backend/[...path]/route.ts`](app/api/backend/%5B...path%5D/route.ts).
