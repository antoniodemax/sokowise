import type { InputHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

export function Checkbox({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={cn('size-5 shrink-0 rounded border-input accent-primary disabled:cursor-not-allowed disabled:opacity-50', className)}
      {...props}
    />
  )
}
