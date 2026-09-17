import { API_BASE_URL, ApiError, refreshSession, withDeadline } from './api'
import { sessionStore } from './session'

const DOWNLOAD_TIMEOUT_MS = 120_000

/**
 * Fetch an authenticated CSV export and return it as a Blob. The bearer header rules out a
 * plain link; one refresh is attempted on 401, exactly like `request`.
 */
export async function fetchCsv(path: string, params: Record<string, string | number | boolean | null | undefined>, fallback: string): Promise<Blob> {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin)
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
  const attempt = async () => {
    const deadline = withDeadline(undefined, DOWNLOAD_TIMEOUT_MS)
    try {
      return await fetch(url, { headers: { Authorization: `Bearer ${sessionStore.getToken() ?? ''}` }, credentials: 'include', signal: deadline.signal })
    } catch {
      throw deadline.timedOut() ? ApiError.timeout() : ApiError.network()
    } finally {
      deadline.release()
    }
  }
  let response = await attempt()
  if (response.status === 401 && (await refreshSession())) response = await attempt()
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | null
    throw new ApiError(response.status, body?.error?.code ?? 'HTTP_ERROR', body?.error?.message ?? fallback, body?.error?.details ?? null, body?.error?.request_id ?? null)
  }
  return response.blob()
}

export function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.append(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}
