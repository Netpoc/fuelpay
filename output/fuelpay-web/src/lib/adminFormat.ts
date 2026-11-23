/** Small formatters for the admin console. */

export function bytes(value: number): string {
  const units = ['B', 'kB', 'MB', 'GB', 'TB']
  let n = value
  let i = 0
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000
    i += 1
  }
  return `${n >= 100 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 90) return `${Math.round(seconds)} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  if (seconds < 172_800) return `${(seconds / 3600).toFixed(1)} h`
  return `${Math.round(seconds / 86_400)} d`
}

export const date = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

export const dateTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'

/** "in 3 days" / "2 days ago" for a demo's expiry. */
export function untilText(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const days = Math.round((new Date(iso).getTime() - now) / 86_400_000)
  if (days === 0) return 'today'
  return days > 0 ? `in ${days} day${days === 1 ? '' : 's'}` : `${-days} day${days === -1 ? '' : 's'} ago`
}

export const KIND_LABEL = { real: 'Customer', demo: 'Demo', expired: 'Expired demo' } as const
export const KIND_STATE = { real: 'ok', demo: 'watch', expired: 'critical' } as const
