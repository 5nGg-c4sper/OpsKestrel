# OpsKestrel Console 2.0

React and TypeScript frontend for the local OpsKestrel operations console.

## Requirements

- Node.js 22 or newer
- pnpm 11

## Development

Start the Python console API first:

```bash
cd ../..
./scripts/start_opskestrel.sh
```

Then start Vite in a second terminal:

```bash
pnpm install
pnpm dev
```

Vite runs at `http://127.0.0.1:5173` and proxies `/api`, `/files`,
`/healthz`, and `/readyz` to the Python server.

## Production build

```bash
pnpm build
```

The build writes to `opskestrel/console_static`. The Python console serves that
directory at `/` and falls back to the legacy built-in HTML page if no compiled
frontend is present.
