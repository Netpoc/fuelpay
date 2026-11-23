/**
 * Builds manual.html from manual.template.html by inlining every logo SVG.
 *
 * The manual has to open by double-clicking the file — a brand manual that
 * needs a web server is a brand manual nobody opens. `fetch()` is blocked
 * under file://, so the markup is baked in at build time instead.
 *
 *   node scripts/build-manual.mjs
 */
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')

const FILES = {
  mark: 'level-mark.svg',
  small: 'level-mark-small.svg',
  mono: 'level-mark-mono.svg',
  reversed: 'level-mark-reversed.svg',
  empty: 'level-mark-empty.svg',
  h: 'lockup-horizontal.svg',
  hr: 'lockup-horizontal-reversed.svg',
  stacked: 'lockup-stacked.svg',
  tagline: 'lockup-tagline.svg',
  wordmark: 'wordmark.svg',
}

const entries = await Promise.all(
  Object.entries(FILES).map(async ([key, file]) => {
    const raw = await readFile(resolve(ROOT, 'logo', file), 'utf8')
    // Strip the XML comments — they are for whoever opens the .svg, and they
    // would otherwise bloat the manual by several kilobytes each.
    const clean = raw.replace(/<!--[\s\S]*?-->/g, '').replace(/\n\s*\n/g, '\n').trim()
    return [key, clean]
  }),
)

const data = `{\n${entries.map(([k, v]) => `  ${k}: ${JSON.stringify(v)},`).join('\n')}\n}`

const template = await readFile(resolve(ROOT, 'manual.template.html'), 'utf8')
if (!template.includes('/*__SVG_DATA__*/')) throw new Error('template slot missing')

await writeFile(resolve(ROOT, 'manual.html'), template.replace('/*__SVG_DATA__*/ {}', data))
console.log(`manual.html built — ${entries.length} logos inlined`)
