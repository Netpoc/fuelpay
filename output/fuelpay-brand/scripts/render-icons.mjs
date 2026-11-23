/**
 * Renders every raster icon from the logo SVGs. No new tooling — Playwright
 * and Chromium are already installed in fuelpay-web.
 *
 *   node scripts/render-icons.mjs
 */
import { chromium } from '/Users/peterayenoto/Projects/fuelpay/output/fuelpay-web/node_modules/playwright/index.mjs'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const LOGO = resolve(HERE, '../logo')
const ICONS = resolve(HERE, '../icons')
await mkdir(ICONS, { recursive: true })

const NAVY = '#0B2545'
const read = (f) => readFile(resolve(LOGO, f), 'utf8')

const browser = await chromium.launch()

/**
 * @param svg   markup to render
 * @param size  output edge in px
 * @param inset fraction of the canvas left as padding (maskable needs a lot)
 * @param bg    background colour, or null for transparent
 */
async function render(svg, size, { inset = 0, bg = null, out }) {
  const page = await browser.newPage({
    viewport: { width: size, height: size },
    deviceScaleFactor: 1,
  })
  const inner = Math.round(size * (1 - inset * 2))
  await page.setContent(
    `<style>
      html,body{margin:0;padding:0;width:${size}px;height:${size}px;
        display:flex;align-items:center;justify-content:center;
        background:${bg ?? 'transparent'}}
      svg{width:${inner}px;height:${inner}px;display:block}
     </style>${svg}`,
  )
  await page.screenshot({ path: resolve(ICONS, out), omitBackground: !bg })
  await page.close()
  console.log(`  ${out}  ${size}px`)
}

const small = await read('level-mark-small.svg')
const full = await read('level-mark.svg')
const reversed = await read('level-mark-reversed.svg')

console.log('favicons (small variant — optically compensated for these sizes)')
for (const size of [16, 32, 48]) {
  await render(small, size, { out: `favicon-${size}.png` })
}

console.log('app icons')
await render(full, 192, { out: 'icon-192.png' })
await render(full, 512, { out: 'icon-512.png' })

// iOS composites black behind transparency, so this one is opaque.
console.log('apple touch (opaque — iOS puts black behind alpha)')
await render(reversed, 180, { inset: 0.14, bg: NAVY, out: 'apple-touch-icon-180.png' })

// Android crops to a circle/squircle; 62% keeps the droplet clear of the crop.
console.log('maskable (62% inset for Android safe zone)')
await render(reversed, 512, { inset: 0.19, bg: NAVY, out: 'maskable-512.png' })

// --- OG / social card -------------------------------------------------------
console.log('social card')
const lockup = await read('lockup-horizontal-reversed.svg')
const ogPage = await browser.newPage({
  viewport: { width: 1200, height: 630 },
  deviceScaleFactor: 1,
})
await ogPage.setContent(`
<style>
  @font-face{font-family:'Inter Variable';src:url(data:font/woff2;base64,${await readFile(
    resolve(HERE, '../../fuelpay-web/node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2'),
  ).then((b) => b.toString('base64'))}) format('woff2');font-weight:100 900}
  html,body{margin:0;width:1200px;height:630px;background:#0B2545;
    font-family:'Inter Variable',sans-serif;color:#E9EFF6;overflow:hidden}
  .wrap{position:relative;height:100%;padding:84px 90px;box-sizing:border-box}
  .lockup svg{height:64px;width:auto}
  h1{font-size:64px;line-height:1.08;letter-spacing:-0.025em;font-weight:600;margin:44px 0 18px;max-width:760px}
  p{font-size:26px;line-height:1.4;color:#9AAABE;margin:0;max-width:680px}
  .amber{color:#F2A93B}
  /* A tank silhouette bleeding off the right edge — the product, not an abstract shape. */
  .tank{position:absolute;right:-90px;bottom:-120px;opacity:.13}
</style>
<div class="wrap">
  <div class="lockup">${lockup}</div>
  <h1>Know exactly where your <span class="amber">diesel</span> goes.</h1>
  <p>Live tank levels, refill records and theft detection for generator fleets.</p>
  <svg class="tank" width="520" height="620" viewBox="0 0 100 150">
    <ellipse cx="50" cy="26" rx="42" ry="10" fill="none" stroke="#E9EFF6" stroke-width="1.6"/>
    <path d="M8 26 L8 124 A42 10 0 0 0 92 124 L92 26" fill="none" stroke="#E9EFF6" stroke-width="1.6"/>
    <path d="M8 70 L8 124 A42 10 0 0 0 92 124 L92 70 A42 10 0 0 1 8 70 Z" fill="#F2A93B" opacity=".5"/>
  </svg>
</div>`)
await ogPage.screenshot({ path: resolve(ICONS, 'og-card-1200x630.png') })
await ogPage.close()
console.log('  og-card-1200x630.png  1200x630')

await browser.close()

// --- manifest ---------------------------------------------------------------
await writeFile(
  resolve(ICONS, 'site.webmanifest'),
  JSON.stringify(
    {
      name: 'FuelPay',
      short_name: 'FuelPay',
      description: 'Live tank levels, refill records and theft detection for generator fleets.',
      start_url: '/',
      display: 'standalone',
      theme_color: '#0B2545',
      background_color: '#0B1420',
      icons: [
        { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
        { src: '/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      ],
    },
    null,
    2,
  ) + '\n',
)
console.log('  site.webmanifest')
