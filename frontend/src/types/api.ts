/** The backend error envelope (docs/ARCHITECTURE.md §8). */
export interface ErrorEnvelope {
  error: {
    code: string
    message: string
    details: unknown
    request_id: string | null
  }
}

export interface ValidationDetail {
  loc: string[]
  msg: string
  type: string
}
