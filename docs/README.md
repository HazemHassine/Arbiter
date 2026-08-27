# Arbiter documentation

This directory contains the standalone Next.js and Fumadocs documentation site
for Arbiter.

## Development

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The Arbiter control panel
is a separate bundled application served by the Python API at
[http://127.0.0.1:8765](http://127.0.0.1:8765).

Before committing documentation changes, run:

```bash
npm run types:check
npm run build
```

Set `NEXT_PUBLIC_DOCS_URL` to the deployed documentation origin when building
outside local development. It defaults to `http://localhost:3000`.

## Structure

- `content/docs/` contains the MDX pages.
- `source.config.ts` defines the Fumadocs collections.
- `src/lib/source.ts` adapts generated content for navigation, search, and LLM
  text routes.
- `src/app/docs/` contains the documentation layout and page routes.
- `src/app/api/search/route.ts` provides the search endpoint.

See the [Fumadocs documentation](https://fumadocs.dev/docs) for framework
details.
