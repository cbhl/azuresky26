# AGENTS.md

## Cursor Cloud specific instructions

This repository is the source for the static personal website **michael-chang.ca**, built with [Zola](https://www.getzola.org/) (a Rust static site generator). There is no backend, database, or package manager — the only dependency is the `zola` binary, and the build output is static HTML/CSS/JS.

### Services

| Service | Required | Command | URL |
|---|---|---|---|
| Zola dev server | Yes (for local preview) | `zola serve` | http://127.0.0.1:1111/ (live reload on :1112) |

To expose the dev server on all interfaces (useful in the cloud VM): `zola serve --interface 0.0.0.0 --port 1111`.

### Build / check / run (no lint or test frameworks exist)

- Build: `zola build` → outputs to `public/` (gitignored).
- "Lint"/validation: `zola check` validates internal links and the site structure (closest thing to a lint/test step; there is no separate test suite).
- Serve (dev): `zola serve` (see table above). See `README.md` for the documented workflow.

### Non-obvious notes

- The config file is named `zola.toml`, not the Zola default `config.toml`. **Zola >= 0.22 reads `zola.toml` natively**, so plain `zola serve` / `zola build` / `zola check` work. On older Zola versions you would need to pass `--config zola.toml`.
- `deploy.sh` runs `zola build` then `rsync`s `public/` to a NearlyFreeSpeech.net host over SSH. It is for production deploys only and requires SSH credentials — do not run it for local testing.
- `themes/` is intentionally empty (no external theme dependency).

## Pull request workflow

When opening or updating a PR:

1. Run `zola check`.
2. Inspect the diff against `main` and determine which site pages are visually affected. Explore `content/`, `templates/`, and related paths as needed — do not assume a fixed page list.
3. Run `zola serve --interface 0.0.0.0 --port 1111` and screenshot each affected page (full-page). Save screenshots locally. Use a command that exits when done (e.g. headless Chrome with `--virtual-time-budget=5000`, or wrap with `timeout 30s`) so the browser does not linger.
4. Include screenshots in the PR description:
   - **Cursor Cloud agents:** save under `/opt/cursor/artifacts/screenshots/` and embed using absolute artifact paths (e.g. `<img alt="..." src="/opt/cursor/artifacts/screenshots/...">`); they are uploaded automatically.
   - **Other agents:** upload each screenshot via whatever your environment provides (GitHub web UI, `gh`, API, etc.) and embed with standard markdown (`![description](url)`) or HTML `<img>` tags pointing at the hosted image URLs.

If nothing renderable changed, screenshot the home page (`/`) as a fallback so the PR still includes a visual check.
