---
name: screenshot
description: Capture full-page screenshots for local visual verification of changed Zola website pages.
---

# Screenshot Visual Checks

## When to Use

Use this workflow when a change affects the rendering of a page on the personal website. Capture every affected page. If nothing renderable changed, capture the home page (`/`) as a fallback.

## Output location

Save local captures under `screenshots/` at the repository root. The directory is kept in Git with `.gitkeep`; all other contents are ignored and should not be committed.

## Workflow

### 1) Identify affected routes

Inspect the changes against `main` and use `content/`, `templates/`, and related paths to identify every affected route. For this Zola site, the output route follows the content page/section structure; confirm routes from the built site if needed.

### 2) Run the site

Start the local Zola server:

```sh
zola serve --interface 0.0.0.0 --port 1111
```

Keep the server running while capturing pages. On a fresh machine, install Playwright's Chromium browser once if needed:

```sh
npx playwright install chromium
```

Playwright is not a project dependency; `npx` downloads the requested release on demand, and each release needs its matching browser build.

### 3) Capture each affected page

Use the browser's native full-page capture mode. Do not substitute a tall fixed viewport for a full-page screenshot. For example:

```sh
npx playwright screenshot --browser chromium --full-page \
  http://127.0.0.1:1111/resume/ screenshots/resume-main.png
npx playwright screenshot --browser chromium --full-page \
  http://127.0.0.1:1111/resume/202607-canada/ screenshots/resume-canada.png
```

Repeat for each affected route, using descriptive filenames. The screenshot command exits when capture is complete; the Zola server may remain running for the user's preview.

### 4) Verify captures

```sh
ls -lh screenshots/<name>.png
```

Confirm each file is non-empty and visually reflects the updated page. Keep these generated captures out of commits.
