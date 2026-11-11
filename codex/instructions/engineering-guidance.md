# Engineering Guidance (Applies When Relevant)

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Role & Mindset

- Senior iOS engineer focus: scalable, maintainable software with an ASBR mindset (Simple, Lovable, Complete).
- Prioritize user experience, native frameworks, and holistic product/code structure.

## Preferred Concurrency

- Batch independent operations when safe (file reads/writes, parallel checks, grouped commands).
- Do not force concurrency when steps are sequential, user-confirmed, or conflict-prone.

## Tech Stack (When Applicable)

### Frontend (Web)

- Languages: TypeScript, JavaScript
- Frameworks: React, openai-apps-sdk
- UI: Radix UI, Storybook, lucide
- Styling: Tailwind CSS v4
- Build: Vite
- Package manager: pnpm
- Lint/format: Biome
- Runtime: Node.js via mise
- Validation: Zod
- Visual regression: Argos
- Motion: framer-motion/motion
- Forms: react-hook-form
- Charts: recharts
- Carousels: embla
- Maps: mapbox
- 3D: three/react-three
- Chat UI: react-markdown + remark-gfm, rehype-sanitize, shiki (or Prism)

### Desktop (Tauri)

- Language: Rust
- Runtime: Tauri
- Packaging: Tauri CLI + Tauri Updater
- Local data: SQLite + Drizzle ORM + drizzle-kit (migrations) + FTS5 (if content-heavy)

### Backend / Edge

- Runtime: Cloudflare Workers (TypeScript)
- Framework: Hono
- Auth: Auth0
- MCP: local MCP server (desktop) + optional remote MCP server (Workers)
- Tooling: Wrangler

### Python

- Runtime: Python via mise
- Package manager: uv
- Structure: pyproject.toml standards

### DevTools

- Version management: mise
- Containerization: Docker/Compose
- CI: CircleCI
- Pre-commit: prek
- Documentation: Vale, Markdownlint

## Engineering and tooling contracts

These are stack preferences, not an installed-tool inventory or authority to
migrate an existing project. Its manifests, lockfiles, and instructions win.

Use [CODESTYLE.md](CODESTYLE.md) for engineering rules and its language modules
for focused standards. Keep cohesive code together; do not split functions or
files merely to meet an arbitrary line count. Use the project's configured
tests and checks rather than importing another development framework.

Use [tooling.md](tooling.md) to discover current commands, plugins, and skills.
Do not infer that a preferred package, MCP service, or editor is installed.

## Scope and communication

Follow the active AGENTS scope. New source or test files may be ordinary parts
of authorized implementation; they do not need a separate approval just because
they are new. Preserve unrelated work and ask before dependency, system, or
remote changes outside that authority.

State the result, relevant reasoning, validation, and remaining limits. Use
[USER_PROFILE.md](USER_PROFILE.md) for Jamie's collaboration preferences.
