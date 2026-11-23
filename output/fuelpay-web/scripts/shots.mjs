/**
 * Screenshot harness — the verification backbone for the redesign.
 *
 * Captures every screen across both themes and three widths, and asserts the
 * one thing eyeballing reliably misses: horizontal overflow. A page that
 * scrolls sideways on a phone looks fine in a screenshot that was taken at the
 * scrolled width, so the check has to be a measurement, not a look.
 *
 *   node scripts/shots.mjs [outDir] [--theme=light|dark] [--reduced-motion]
 *                          [--real-tiles] [--api=http://localhost:8000]
 *                          [--base=http://localhost:5173]
 *
 * Requires the API on :8000 and Vite on :5173 — override either when another
 * dev server already holds those ports.
 */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const args = process.argv.slice(2)
const OUT = resolve(args.find((a) => !a.startsWith('--')) ?? 'screenshots')
const ONLY_THEME = args.find((a) => a.startsWith('--theme='))?.split('=')[1]
const REDUCED = args.includes('--reduced-motion')
const REAL_TILES = args.includes('--real-tiles')
const API = args.find((a) => a.startsWith('--api='))?.split('=')[1] ?? 'http://localhost:8000'

const BASE = args.find((a) => a.startsWith('--base='))?.split('=')[1] ?? 'http://localhost:5173'
const KEY = 'dev-local-key-change-me'

/**
 * A 1x1 transparent PNG, served in place of every basemap tile.
 *
 * The map's LAYOUT is what this harness tests; the imagery is CARTO's problem.
 * Fetching it for real would make ~40 network requests per shot across 36
 * shots, break the run entirely in an offline or sandboxed CI, and make every
 * screenshot diff noisy as the basemap changes underneath us. Pass
 * --real-tiles when you actually want to look at the map.
 */
const TRANSPARENT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
)

/** Design targets. 360 is the narrowest phone we support. */
const WIDTHS = [
  { name: '360', width: 360, height: 780 },
  { name: '768', width: 768, height: 1024 },
  { name: '1280', width: 1280, height: 1100 },
]
const THEMES = ONLY_THEME ? [ONLY_THEME] : ['light', 'dark']

async function firstId(path) {
  const res = await fetch(`${API}${path}`, { headers: { 'X-API-Key': KEY } })
  if (!res.ok) throw new Error(`API not reachable: ${res.status}`)
  const rows = await res.json()
  return rows[0]?.id
}

const failures = []
const rows = []

const browser = await chromium.launch()
await mkdir(OUT, { recursive: true })
const gid = await firstId('/v1/generators')
const sid = await firstId('/v1/sites')

const SCREENS = [
  { name: 'gate', path: '/fleet', noKey: true },
  { name: 'fleet', path: '/fleet' },
  { name: 'detail', path: `/generators/${gid}` },
  { name: 'site', path: `/sites/${sid}` },
  { name: 'incidents', path: '/incidents' },
  { name: 'notfound', path: '/no-such-page' },
]

for (const theme of THEMES) {
  for (const size of WIDTHS) {
    const context = await browser.newContext({
      viewport: { width: size.width, height: size.height },
      deviceScaleFactor: 2,
      colorScheme: theme,
      reducedMotion: REDUCED ? 'reduce' : 'no-preference',
    })

    if (!REAL_TILES) {
      await context.route(/arcgisonline\.com|basemaps\.cartocdn\.com/, (route) =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
      )
    }

    for (const screen of SCREENS) {
      const page = await context.newPage()
      const errors = []
      page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
      page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

      // The gate screen is the only one that must NOT be authenticated.
      await page.addInitScript(
        ([key, mode, authed]) => {
          if (authed) localStorage.setItem('fuelpay.apiKey', key)
          else localStorage.removeItem('fuelpay.apiKey')
          localStorage.setItem('fuelpay.theme', mode)
        },
        [KEY, theme, !screen.noKey],
      )

      try {
        await page.goto(`${BASE}${screen.path}`, {
          waitUntil: 'networkidle',
          timeout: 30_000,
        })
        await page.waitForTimeout(REDUCED ? 400 : 1600)
      } catch (caught) {
        failures.push(`${screen.name}/${theme}/${size.name}: navigation — ${caught.message}`)
        await page.close()
        continue
      }

      const label = `${screen.name}-${theme}-${size.name}${REDUCED ? '-rm' : ''}`
      await page.screenshot({ path: `${OUT}/${label}.png`, fullPage: true })

      // The assertion eyeballing misses.
      const overflow = await page.evaluate(() => {
        const el = document.scrollingElement ?? document.documentElement
        const widest = [...document.querySelectorAll('body *')]
          .filter((n) => n.getBoundingClientRect().right > el.clientWidth + 1)
          .slice(0, 3)
          .map((n) => `${n.tagName.toLowerCase()}.${(n.className || '').toString().slice(0, 40)}`)
        return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, widest }
      })

      const overflows = overflow.scrollWidth > overflow.clientWidth + 1
      if (overflows) {
        failures.push(
          `${label}: horizontal overflow ${overflow.scrollWidth} > ${overflow.clientWidth}` +
            (overflow.widest.length ? ` — culprits: ${overflow.widest.join(', ')}` : ''),
        )
      }
      if (errors.length) failures.push(`${label}: console — ${errors[0]}`)

      rows.push({ label, overflows, errors: errors.length })
      await page.close()
    }
    await context.close()
  }
}

await browser.close()

const ok = rows.filter((r) => !r.overflows && !r.errors).length
await writeFile(
  `${OUT}/report.txt`,
  [
    `${rows.length} shots — ${ok} clean, ${rows.length - ok} with findings`,
    '',
    ...failures.map((f) => `FAIL ${f}`),
  ].join('\n'),
)

console.log(`${rows.length} shots → ${OUT}`)
console.log(`${ok} clean, ${rows.length - ok} with findings`)
for (const f of failures) console.log(`  FAIL ${f}`)
process.exitCode = failures.length ? 1 : 0
