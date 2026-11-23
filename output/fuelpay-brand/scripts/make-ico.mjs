/**
 * Packs favicon-16/32/48.png into a multi-resolution favicon.ico.
 *
 * No dependency needed: an ICO is a 6-byte header, one 16-byte directory entry
 * per image, then the payloads — and every browser since Vista accepts PNG
 * payloads verbatim rather than requiring BMP.
 *
 *   node scripts/make-ico.mjs
 */
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ICONS = resolve(HERE, '../icons')
const SIZES = [16, 32, 48]

const images = await Promise.all(
  SIZES.map(async (size) => ({ size, data: await readFile(resolve(ICONS, `favicon-${size}.png`)) })),
)

const header = Buffer.alloc(6)
header.writeUInt16LE(0, 0) // reserved
header.writeUInt16LE(1, 2) // type 1 = icon
header.writeUInt16LE(images.length, 4)

const DIR_ENTRY = 16
let offset = header.length + images.length * DIR_ENTRY

const entries = images.map(({ size, data }) => {
  const entry = Buffer.alloc(DIR_ENTRY)
  // 0 means 256 in the ICO format; our sizes are all well under that.
  entry.writeUInt8(size >= 256 ? 0 : size, 0) // width
  entry.writeUInt8(size >= 256 ? 0 : size, 1) // height
  entry.writeUInt8(0, 2) // palette size — 0 for truecolour
  entry.writeUInt8(0, 3) // reserved
  entry.writeUInt16LE(1, 4) // colour planes
  entry.writeUInt16LE(32, 6) // bits per pixel
  entry.writeUInt32LE(data.length, 8)
  entry.writeUInt32LE(offset, 12)
  offset += data.length
  return entry
})

await writeFile(
  resolve(ICONS, 'favicon.ico'),
  Buffer.concat([header, ...entries, ...images.map((i) => i.data)]),
)
console.log(`favicon.ico  ${SIZES.join('/')}  ${offset} bytes`)
