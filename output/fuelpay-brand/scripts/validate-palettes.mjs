/**
 * Colour validation gate. Exits non-zero on any FAIL.
 *
 * This is a build step, not a suggestion: the status palette is one careless
 * edit away from being indistinguishable to a colourblind operator, and the
 * failure is invisible to anyone with full colour vision. Re-run after ANY
 * change to tokens/color.json.
 *
 *   node scripts/validate-palettes.mjs
 */
import { execFileSync } from 'node:child_process'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const VALIDATOR =
  process.env.VALIDATOR ??
  '/private/tmp/claude-501/bundled-skills/2.1.328/2109a0515b88c85893d1f6d8f28aa421/dataviz/scripts/validate_palette.js'

const tokens = JSON.parse(await readFile(resolve(HERE, '../tokens/color.json'), 'utf8'))
const s = tokens.status
const c = tokens.chart

const CASES = [
  {
    name: 'status marks + fuel trace — light',
    colors: [c.light.fuel, s.light.ok, s.light.watch, s.light.critical],
    mode: 'light',
  },
  {
    name: 'status marks + fuel trace — dark',
    colors: [c.dark.fuel, s.dark.ok, s.dark.watch, s.dark.critical],
    mode: 'dark',
  },
  { name: 'status marks alone — light', colors: [s.light.ok, s.light.watch, s.light.critical], mode: 'light' },
  { name: 'status marks alone — dark', colors: [s.dark.ok, s.dark.watch, s.dark.critical], mode: 'dark' },
]

const lines = [
  'FuelPay palette validation',
  `generated from tokens/color.json`,
  '',
  'WHY THREE STATUS HUES AND NOT FOUR',
  'A four-step ok/watch/low/critical ramp cannot pass. The two ambers are',
  'metamers under deuteranopia. Recorded here so the constraint is not',
  'rediscovered later:',
  '',
]

let failed = false

// The documented counter-example, kept in the report on purpose.
try {
  const out = execFileSync(
    'node',
    [VALIDATOR, '#0F7B55,#B25E09,#C2410C,#B91C1C', '--mode', 'light', '--pairs', 'all'],
    { encoding: 'utf8' },
  )
  lines.push('  $ validate_palette "#0F7B55,#B25E09,#C2410C,#B91C1C" --mode light --pairs all')
  lines.push(...out.trimEnd().split('\n').map((l) => `  ${l}`), '')
} catch (caught) {
  // Expected to fail — that IS the finding.
  lines.push('  $ validate_palette "#0F7B55,#B25E09,#C2410C,#B91C1C" --mode light --pairs all')
  lines.push(...String(caught.stdout ?? '').trimEnd().split('\n').map((l) => `  ${l}`), '')
}

lines.push('SHIPPING PALETTES', '')

for (const testCase of CASES) {
  const arg = testCase.colors.join(',')
  let out = ''
  let ok = true
  try {
    out = execFileSync('node', [VALIDATOR, arg, '--mode', testCase.mode, '--pairs', 'all'], {
      encoding: 'utf8',
    })
  } catch (caught) {
    out = String(caught.stdout ?? caught.message)
    ok = false
  }
  if (/\[FAIL\]/.test(out)) ok = false
  if (!ok) failed = true

  lines.push(`  ${ok ? 'PASS' : 'FAIL'}  ${testCase.name}`)
  lines.push(`  $ validate_palette "${arg}" --mode ${testCase.mode} --pairs all`)
  lines.push(...out.trimEnd().split('\n').map((l) => `  ${l}`), '')
}

await mkdir(resolve(HERE, '../reports'), { recursive: true })
await writeFile(resolve(HERE, '../reports/palette-validation.txt'), lines.join('\n'))

console.log(lines.join('\n'))
if (failed) {
  console.error('\nPALETTE VALIDATION FAILED — fix the marked checks before shipping.')
  process.exit(1)
}
console.log('\nAll shipping palettes pass.')
