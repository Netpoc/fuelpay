/**
 * Generates the lockup SVGs with a MEASURED wordmark width.
 *
 * Guessing the advance width of "FuelPay" at a given size leaves either a
 * clipped descender or a slab of dead space inside the viewBox, and a logo
 * file with dead space misaligns everywhere it is placed. Playwright measures
 * the real text run, so the viewBox is exact.
 *
 * The wordmark stays live <text> rather than outlined paths — outlining needs
 * font tooling we do not have here. Documented in the manual: production
 * artwork for print should be outlined once, from these files.
 */
import { chromium } from '/Users/peterayenoto/Projects/fuelpay/output/fuelpay-web/node_modules/playwright/index.mjs'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const LOGO = resolve(HERE, '../logo')
const FONT = resolve(
  HERE,
  '../../fuelpay-web/node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2',
)

const NAVY = '#0B2545'
const AMBER = '#F2A93B'
const PAPER = '#E9EFF6'

// Mark height = 1.6x wordmark cap height. Inter's cap height is 0.727em.
const MARK = 32
const CAP = MARK / 1.6 // 20
const SIZE = +(CAP / 0.727).toFixed(2) // ~27.51
const GAP = MARK * 0.5 // 16
const TRACK = -0.012 // em

const fontData = await readFile(FONT).then((b) => b.toString('base64'))

const browser = await chromium.launch()
const page = await browser.newPage()
await page.setContent(`<style>
  @font-face { font-family:'Inter Variable'; src:url(data:font/woff2;base64,${fontData}) format('woff2'); font-weight:100 900 }
  body { margin:0 }
  span { font-family:'Inter Variable'; font-weight:600; font-size:${SIZE}px; letter-spacing:${TRACK}em; white-space:pre }
</style><span id="w">FuelPay</span><span id="t" style="font-size:${(CAP * 0.34).toFixed(2)}px;letter-spacing:0.08em;font-weight:500">FUEL TELEMETRY FOR GENERATOR FLEETS</span>`)

const [wordW, tagW] = await page.evaluate(() => [
  document.getElementById('w').getBoundingClientRect().width,
  document.getElementById('t').getBoundingClientRect().width,
])
await browser.close()

const W = Math.ceil(wordW)
const T = Math.ceil(tagW)
console.log(`measured: wordmark ${W}px @ ${SIZE}px, tagline ${T}px`)

const FONT_STACK = "'Inter Variable','Inter',-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"

/** The mark, inlined at a given offset — ids are suffixed to stay unique. */
const markAt = async (file, id, x, y, size) => {
  const raw = await readFile(resolve(LOGO, file), 'utf8')
  const body = raw
    .replace(/<svg[^>]*>/, '')
    .replace('</svg>', '')
    .replace(/<title>.*?<\/title>/s, '')
    .replace(/lm[a-z]*-fill/g, `${id}-fill`)
  return `<g transform="translate(${x} ${y}) scale(${size / 32})">${body}</g>`
}

const wordmark = (x, baseline, fill) =>
  `<text x="${x}" y="${baseline}" font-family="${FONT_STACK}" font-weight="600" font-size="${SIZE}" letter-spacing="${TRACK}em" fill="${fill}">FuelPay</text>`

const tagline = (x, baseline, fill) =>
  `<text x="${x}" y="${baseline}" font-family="${FONT_STACK}" font-weight="500" font-size="${(CAP * 0.34).toFixed(2)}" letter-spacing="0.08em" fill="${fill}">FUEL TELEMETRY FOR GENERATOR FLEETS</text>`

const doc = (w, h, inner, label) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${label}">
  <title>${label}</title>
${inner}
</svg>
`

// --- horizontal: cap box vertically centred on the mark ---------------------
// Cap spans baseline-CAP .. baseline. Centre that on the mark's centre (16).
const hBaseline = 16 + CAP / 2
const hW = MARK + GAP + W
{
  const inner = [await markAt('level-mark.svg', 'h', 0, 0, MARK), wordmark(MARK + GAP, hBaseline, NAVY)].join('\n')
  await writeFile(resolve(LOGO, 'lockup-horizontal.svg'), doc(hW, MARK, inner, 'FuelPay'))

  const rev = [
    await markAt('level-mark-reversed.svg', 'hr', 0, 0, MARK),
    wordmark(MARK + GAP, hBaseline, PAPER),
  ].join('\n')
  await writeFile(resolve(LOGO, 'lockup-horizontal-reversed.svg'), doc(hW, MARK, rev, 'FuelPay'))
}

// --- stacked ----------------------------------------------------------------
{
  const vGap = MARK * 0.35
  const h = MARK + vGap + CAP
  const w = Math.max(MARK, W)
  const inner = [
    await markAt('level-mark.svg', 's', (w - MARK) / 2, 0, MARK),
    wordmark((w - W) / 2, MARK + vGap + CAP, NAVY),
  ].join('\n')
  await writeFile(resolve(LOGO, 'lockup-stacked.svg'), doc(Math.ceil(w), Math.ceil(h), inner, 'FuelPay'))
}

// --- stacked + tagline ------------------------------------------------------
{
  const vGap = MARK * 0.35
  const tGap = CAP * 0.55
  const tCap = CAP * 0.34 * 0.727
  const h = MARK + vGap + CAP + tGap + tCap
  const w = Math.max(MARK, W, T)
  const inner = [
    await markAt('level-mark.svg', 'g', (w - MARK) / 2, 0, MARK),
    wordmark((w - W) / 2, MARK + vGap + CAP, NAVY),
    tagline((w - T) / 2, MARK + vGap + CAP + tGap + tCap, '#4B5A6E'),
  ].join('\n')
  await writeFile(resolve(LOGO, 'lockup-tagline.svg'), doc(Math.ceil(w), Math.ceil(h), inner, 'FuelPay — fuel telemetry for generator fleets'))
}

// --- wordmark alone ---------------------------------------------------------
await writeFile(
  resolve(LOGO, 'wordmark.svg'),
  doc(W, Math.ceil(CAP * 1.32), wordmark(0, CAP, NAVY), 'FuelPay'),
)

console.log('lockups written')
