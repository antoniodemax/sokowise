import { ApiError } from './api'
import type { ValidationDetail } from '@/types/api'

/** Turn any thrown value into a short message a shop owner can act on. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 0:
        return error.message
      case 401:
        return error.code === 'INVALID_CREDENTIALS' ? error.message : 'Your session has ended. Please sign in again.'
      case 403:
        return error.code === 'BUSINESS_INACTIVE'
          ? 'This business is inactive. Contact SokoWise support.'
          : error.code === 'PASSWORD_CHANGE_REQUIRED'
            ? 'Please change your password to continue.'
            : error.code === 'CSRF_REJECTED'
              ? 'The server did not accept this request from this address. Check that the app origin is allowed (CORS_ORIGINS) and reload.'
              : 'You do not have permission to do this.'
      case 404:
        return 'Not found.'
      case 409:
        return error.message
      case 422:
        return validationSummary(error) ?? error.message
      case 429:
        return 'Too many attempts. Please wait a moment and try again.'
      default:
        return error.status >= 500 ? 'Something went wrong on our side. Please try again.' : error.message
    }
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong. Please try again.'
}

/** Field-level messages from a 422 envelope, keyed by the last part of `loc`. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.details)) return {}
  const out: Record<string, string> = {}
  for (const detail of error.details as ValidationDetail[]) {
    const field = detail.loc?.[detail.loc.length - 1]
    if (field && !out[field]) out[field] = detail.msg.replace(/^Value error, /, '')
  }
  return out
}

function validationSummary(error: ApiError): string | null {
  const fields = fieldErrors(error)
  const first = Object.values(fields)[0]
  return first ?? null
}
