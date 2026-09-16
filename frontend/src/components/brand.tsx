import { cn } from '@/lib/utils'

/**
 * The official SokoWise assets, cropped from the brand file (never redrawn):
 * - lockup: mark + wordmark + tagline, on its own white background → auth screens
 * - mark: the green rounded square → app header, favicon
 */
export function BrandLockup({ className }: { className?: string }) {
  return <img src="/brand/sokowise-lockup.png" alt="SokoWise — AI-powered business intelligence" className={cn('h-auto w-56', className)} />
}

export function BrandMark({ className, size = 36 }: { className?: string; size?: number }) {
  return <img src="/brand/sokowise-mark.png" alt="SokoWise" width={size} height={size} className={cn('shrink-0 rounded-md', className)} />
}
