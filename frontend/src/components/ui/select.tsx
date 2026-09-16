import { ChevronDown } from 'lucide-react'
import type { SelectHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean
}

/** A native select: the most reliable control on low-end Android browsers. */
export function Select({ className, invalid, children, ...props }: SelectProps) {
  return (
    <div className="relative">
      <select
        aria-invalid={invalid || undefined}
        className={cn(
          'flex h-11 w-full appearance-none rounded-md border border-input bg-card py-2 pr-9 pl-3 text-base text-foreground shadow-xs disabled:cursor-not-allowed disabled:opacity-50 sm:h-10 sm:text-sm',
          'aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
    </div>
  )
}
