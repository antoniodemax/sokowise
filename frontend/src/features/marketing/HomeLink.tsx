import type { MouseEvent, ReactNode } from 'react'
import { Link, useLocation } from 'react-router'

/**
 * The logo as a link to the top of the homepage. On any other page it navigates to `/`; on
 * the homepage itself it scrolls back to the hero (React Router keeps the scroll position for
 * a same-route link) and drops any `#section` from the address.
 */
export function HomeLink({ className, children, onNavigate, label = 'SokoWise home' }: { className?: string; children: ReactNode; onNavigate?: () => void; label?: string }) {
  const location = useLocation()
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onNavigate?.()
    if (location.pathname !== '/') return
    event.preventDefault()
    window.scrollTo({ top: 0, behavior: 'smooth' })
    if (window.location.hash) window.history.replaceState(null, '', '/')
  }
  return (
    <Link to="/" aria-label={label} className={className} onClick={handleClick}>
      {children}
    </Link>
  )
}
