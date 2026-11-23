/**
 * Links back to the Netpoc corporate site, which hosts FuelPay's product page
 * and the PoC booking form. FuelPay is a Netpoc product; anyone who reaches the
 * app without a PoC code is sent there to get one.
 */
const ORIGIN = (import.meta.env.VITE_NETPOC_URL ?? '').replace(/\/+$/, '')

const withUtm = (path: string, content: string) => {
  if (!ORIGIN) return null
  const url = new URL(ORIGIN + path)
  url.searchParams.set('utm_source', 'fuelpay-app')
  url.searchParams.set('utm_medium', 'referral')
  url.searchParams.set('utm_content', content)
  return url.toString()
}

/** Netpoc's FuelPay page, PoC section. `null` when VITE_NETPOC_URL is unset. */
export const bookPocHref = (content: string) => withUtm('/fuelpay', content)?.concat('#poc') ?? null

/** Netpoc home. `null` when unset. */
export const netpocHref = (content: string) => withUtm('/', content)
