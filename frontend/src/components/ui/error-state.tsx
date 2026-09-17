import { AlertCircle, RefreshCw } from 'lucide-react'

import { ApiError } from '@/lib/api'
import { describeError } from '@/lib/errors'

import { Button } from './button'

interface ErrorStateProps {
  error: unknown
  title?: string
  onRetry?: () => void
}

export function ErrorState({ error, title = 'Something went wrong', onRetry }: ErrorStateProps) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center rounded-xl border border-destructive/30 bg-card px-6 py-10 text-center">
      <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-destructive-soft text-destructive">
        <AlertCircle className="size-6" aria-hidden="true" />
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{describeError(error)}</p>
      {onRetry && !(error instanceof ApiError && error.status === 404) && (
        <Button variant="outline" className="mt-5" onClick={onRetry}>
          <RefreshCw aria-hidden="true" /> Try again
        </Button>
      )}
    </div>
  )
}
