/**
 * Renders a contact sheet of the logo files at real sizes, on light and dark,
 * so the mark can be judged rather than assumed — especially the point where
 * the fill line stops surviving.
 *
 *   node scripts/contact-sheet.mjs <out.png>
 */
import { chromium } from '/Users/peterayenoto/Projects/fuelpay/output/fuelpay-web/node_modules/playwright/index.mjs'
import { readFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const LOGO = resolve(HERE, '../logo')
const OUT = process.argv[2] ?? resolve(HERE, '../reports/contact-sheet.png')

const read = (f) => readFile(resolve(LOGO, f), 'utf8')

const [mark, small, mono, reversed, empty] = await Promise.all([
  read('level-mark.svg'),
  read('level-mark-small.svg'),
  read('level-mark-mono.svg'),
  read('level-mark-reversed.svg'),
  read('level-mark-empty.svg'),
])

const sized = (svg, px) => svg.replace(/width="32" height="32"/, `width="${px}" height="${px}"`)

const row = (label, svg, sizes, cls = '') => `
  <tr><th>${label}</th>${sizes
    .map((s) => `<td><div class="cell ${cls}">${sized(svg, s)}</div><span>${s}</span></td>`)
    .join('')}</tr>`

const SIZES = [96, 64, 48, 32, 24, 16]

const html = `
<style>
  body { margin:0; font: 12px/1.4 -apple-system, Segoe UI, sans-serif; background:#fff; color:#0B1B2B }
  h2 { font-size:13px; margin:22px 16px 6px; letter-spacing:.06em; text-transform:uppercase; color:#4B5A6E }
  table { border-collapse:collapse; margin:0 8px }
  th { text-align:right; padding-right:12px; font-weight:600; width:120px; color:#4B5A6E }
  td { text-align:center; padding:8px 10px }
  td span { display:block; margin-top:4px; color:#4B5A6E; font-size:10px }
  .cell { display:inline-flex; align-items:center; justify-content:center; min-height:96px }
  .dark { background:#0B1420; padding:6px; border-radius:6px }
  .navy { background:#0B2545; padding:6px; border-radius:6px }
  .onink { color:#0B1B2B }
  .onlight { color:#0B2545 }
</style>
<h2>Full mark — on white</h2>
<table>${row('level-mark', mark, SIZES)}</table>
<h2>Small variant — the ≤24px file</h2>
<table>${row('level-mark-small', small, SIZES)}</table>
<h2>Mono (currentColor = ink)</h2>
<table>${row('level-mark-mono', mono, SIZES, 'onink')}</table>
<h2>Reversed — on brand navy</h2>
<table>${row('level-mark-reversed', reversed, SIZES, 'navy')}</table>
<h2>Empty — the 404 mark</h2>
<table>${row('level-mark-empty', empty, [96, 64, 48], 'onlight')}</table>
`

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 900, height: 1200 }, deviceScaleFactor: 2 })
await page.setContent(html)
await page.screenshot({ path: OUT, fullPage: true })
await browser.close()
console.log(`contact sheet → ${OUT}`)
