import { useCallback, useRef } from 'react'

/**
 * One Idempotency-Key per *intentional* submission (docs/ARCHITECTURE.md §5.8, §5.9).
 *
 * `keyFor(payload)` returns the key for the submission in progress: the same key
 * while the payload is unchanged, so a retry (network blip, "try again") replays
 * on the backend instead of duplicating; a fresh key as soon as the payload
 * differs, because the backend answers a reused key with a different body with
 * 409 IDEMPOTENCY_CONFLICT. `renew()` starts over after a success.
 */
export function useIdempotencyKey() {
  const ref = useRef<{ key: string; payload: string } | null>(null)
  const keyFor = useCallback((payload: unknown) => {
    const json = JSON.stringify(payload)
    if (ref.current?.payload !== json) ref.current = { key: crypto.randomUUID(), payload: json }
    return ref.current.key
  }, [])
  const renew = useCallback(() => {
    ref.current = null
  }, [])
  return { keyFor, renew }
}
