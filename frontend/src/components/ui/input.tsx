import type { InputHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean
}

export function Input({ className, invalid, type = 'text', ...props }: InputProps) {
  return (
    <input
      type={type}
      aria-invalid={invalid || undefined}
      className={cn(
        'flex h-11 w-full rounded-md border border-input bg-card px-3 py-2 text-base text-foreground shadow-xs placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 sm:h-10 sm:text-sm',
        'aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive',
        className,
      )}
      {...props}
    />
  )
}
