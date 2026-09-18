import { LayoutDashboard, Menu } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { BrandMark } from '@/components/brand'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { useAuth } from '@/features/auth/auth-context'
import { cn } from '@/lib/utils'

import { HomeLink } from './HomeLink'
import { SECTION_LINKS } from './links'

/** The public site's header: brand, section links, sign in / get started; a drawer on phones. */
export function PublicHeader() {
  const { session } = useAuth()
  const [open, setOpen] = useState(false)
  const signedIn = !!session && !session.user.must_change_password

  const authLinks = (mobile: boolean) =>
    signedIn ? (
      <Link to="/dashboard" className={cn(buttonVariants(), mobile && 'w-full')} onClick={() => setOpen(false)}>
        <LayoutDashboard aria-hidden="true" /> Go to dashboard
      </Link>
    ) : (
      <>
        <Link to="/login" className={cn(buttonVariants({ variant: mobile ? 'outline' : 'ghost' }), mobile && 'w-full')} onClick={() => setOpen(false)}>
          Sign in
        </Link>
        <Link to="/register" className={cn(buttonVariants(), mobile && 'w-full')} onClick={() => setOpen(false)}>
          Get started
        </Link>
      </>
    )

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <HomeLink className="flex min-h-11 items-center gap-2.5 rounded-md font-semibold tracking-tight text-foreground">
          <BrandMark size={32} />
          <span className="text-lg">SokoWise</span>
        </HomeLink>
        <nav aria-label="Site" className="hidden items-center gap-1 md:flex">
          {SECTION_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
              {link.label}
            </a>
          ))}
          <span className="mx-2 h-6 w-px bg-border" aria-hidden="true" />
          {authLinks(false)}
        </nav>
        <div className="flex items-center gap-2 md:hidden">
          {!signedIn && (
            <Link to="/register" className={buttonVariants()}>
              Get started
            </Link>
          )}
          <Button variant="ghost" size="icon" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}>
            <Menu aria-hidden="true" />
          </Button>
        </div>
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="flex w-72 flex-col gap-6 p-5">
          <SheetTitle className="flex items-center gap-2.5 text-base font-semibold">
            <HomeLink className="flex min-h-11 items-center gap-2.5 rounded-md" onNavigate={() => setOpen(false)}>
              <BrandMark size={28} /> SokoWise
            </HomeLink>
          </SheetTitle>
          <SheetDescription className="sr-only">Site navigation</SheetDescription>
          <nav aria-label="Site" className="flex flex-col gap-1">
            {SECTION_LINKS.map((link) => (
              <SheetClose asChild key={link.href}>
                <a href={link.href} className="inline-flex min-h-11 items-center rounded-md px-3 text-base font-medium text-foreground hover:bg-muted">
                  {link.label}
                </a>
              </SheetClose>
            ))}
          </nav>
          <div className="mt-auto flex flex-col gap-2">{authLinks(true)}</div>
        </SheetContent>
      </Sheet>
    </header>
  )
}
