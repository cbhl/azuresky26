// Injects a noindex/nofollow meta tag into the built HTML entrypoints so the
// deck isn't picked up by crawlers even though it isn't linked or sitemapped.
// Also drops the Netlify-only _redirects file: we use hash-mode routing, so
// deep slide links never touch the server and need no rewrite rule.
import { readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { join } from 'node:path'

const outDir = process.argv[2]
if (!outDir) {
  console.error('Usage: node scripts/postbuild.mjs <outDir>')
  process.exit(1)
}

const robotsMeta = '<meta name="robots" content="noindex, nofollow">'

const redirectsPath = join(outDir, '_redirects')
if (existsSync(redirectsPath)) rmSync(redirectsPath)

for (const file of ['index.html', '404.html']) {
  const filePath = join(outDir, file)
  if (!existsSync(filePath)) continue
  const html = readFileSync(filePath, 'utf-8')
  if (html.includes(robotsMeta)) continue
  writeFileSync(filePath, html.replace('<head>', `<head>\n${robotsMeta}`))
}
