import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

/** "Back to the section" link at the top of a detail or sub-page; a fixed parent route, not browser history. */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="mb-4 inline-flex min-h-11 items-center gap-1 rounded-md text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" aria-hidden="true" /> {children}
    </Link>
  )
}
