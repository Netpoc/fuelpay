/**
 * The one place an HTTP request is made.
 *
 * Holds the API key and the base URL, and turns non-2xx into a typed error so
 * callers never have to remember to check `response.ok`. A 401 is broadcast so
 * the auth store can drop straight back to the key gate from anywhere, without
 * every caller having to handle it.
 */

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/v1'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`)
    this.name = 'ApiError'
  }

  get isAuthFailure() {
    return this.status === 401
  }
}

let apiKey: string | null = null
const unauthorizedHandlers = new Set<() => void>()

export function setApiKey(key: string | null) {
  apiKey = key
}

export function getApiKey() {
  return apiKey
}

/** Register a callback for 401s. Returns an unsubscribe function. */
export function onUnauthorized(handler: () => void) {
  unauthorizedHandlers.add(handler)
  return () => unauthorizedHandlers.delete(handler)
}

export function authHeaders(): Record<string, string> {
  return apiKey ? { 'X-API-Key': apiKey } : {}
}

/**
 * Build a query string, repeating a key once per array item.
 *
 * The events endpoint expresses multiple types as `?event_type=A&event_type=B`.
 * A comma-joined list is a 422, so array values must never be stringified.
 */
export function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item))
    } else {
      search.append(key, String(value))
    }
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

/**
 * The request core, parameterised by credentials.
 *
 * The tenant API and the admin console authenticate differently and must fail
 * differently — a 401 in the console returns to the admin sign-in, never to the
 * tenant key gate — so both pass their own headers and 401 handler here.
 */
export async function send<T>(
  path: string,
  init: RequestInit,
  auth: Record<string, string>,
  onAuthFailure: () => void,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...auth,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      // FastAPI validation errors put an array here; keep it readable.
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* a non-JSON error body is not worth failing over */
    }
    if (response.status === 401) onAuthFailure()
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return send<T>(path, init, authHeaders(), () => {
    for (const handler of unauthorizedHandlers) handler()
  })
}

export function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>(`${path}${params ? queryString(params) : ''}`)
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}
