# Two Truths and a Lie (Slidev deck)

Source for the slide deck published, unlinked, at `/chang26/` on michael-chang.ca.

## Editing

```
npm install
npm run dev
```

Opens a live-reloading preview at http://localhost:3030/.

## Rebuilding for the site

```
npm run build
```

This runs `slidev build` with the site's `/chang26/` base path and outputs
straight into `../../static/chang26/`, then patches in a `noindex` meta tag.
Zola copies `static/` verbatim, so after rebuilding just run `zola build`
(or `zola serve`) from the repo root as usual and commit the changed files
under `static/chang26/`.

## Notes

- `routerMode: hash` in `slides.md` frontmatter is intentional: the site is
  deployed via `rsync` to a plain static host with no SPA-fallback rewrite
  rule, so slide URLs use `#2`, `#3`, etc. instead of path segments.
- `global-bottom.vue` adds the small "← michael-chang.ca" link shown on
  every slide.
- The deck is intentionally not linked from any page or the sitemap. If
  this repository is public on GitHub, note that the URL and slide content
  are still visible to anyone reading the source — the obscurity only
  keeps it off nav/footer/sitemap and out of search engines (the exported
  HTML also carries a `noindex, nofollow` meta tag).
