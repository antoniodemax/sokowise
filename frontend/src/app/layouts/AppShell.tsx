import { LogOut, Menu, ShieldCheck, UserRound } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'

import { BrandMark } from '@/components/brand'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { toast } from 'sonner'
import { useAuth } from '@/features/auth/auth-context'
import { describeError } from '@/lib/errors'
import { cn } from '@/lib/utils'

import { NAV_ITEMS } from '../nav'

function NavLinks({ role, onNavigate }: { role: 'OWNER' | 'STAFF'; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV_ITEMS.filter((item) => !item.ownerOnly || role === 'OWNER').map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
              isActive ? 'bg-primary-soft text-primary' : 'text-foreground/80 hover:bg-muted hover:text-foreground',
            )
          }
        >
          {({ isActive }) => (
            <>
              <item.icon className={cn('size-5', isActive ? 'text-primary' : 'text-muted-foreground')} aria-hidden="true" />
              {item.label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

function BusinessIdentity({ name, role }: { name: string; role: 'OWNER' | 'STAFF' }) {
  return (
    <div className="flex items-center gap-3 px-3 py-4">
      <BrandMark size={40} />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold leading-tight">{name}</p>
        <p className="text-xs text-muted-foreground">
          SokoWise · {role === 'OWNER' ? 'Owner' : 'Staff'}
        </p>
      </div>
    </div>
  )
}

export function AppShell() {
  const { session, logout, logoutAll } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmLogoutAll, setConfirmLogoutAll] = useState(false)

  if (!session) return null
  const { user, business, role } = session

  async function handleLogout() {
    try {
      await logout()
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      navigate('/login', { replace: true })
    }
  }

  const accountMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="w-full justify-start gap-3 px-3 lg:h-12">
          <span className="flex size-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground" aria-hidden="true">
            {user.full_name
              .split(' ')
              .slice(0, 2)
              .map((part) => part[0]?.toUpperCase())
              .join('')}
          </span>
          <span className="min-w-0 flex-1 text-left">
            <span className="block truncate text-sm font-medium">{user.full_name}</span>
            <span className="block truncate text-xs text-muted-foreground">{user.phone}</span>
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="flex items-center justify-between">
          Signed in as <Badge variant={role === 'OWNER' ? 'default' : 'neutral'}>{role === 'OWNER' ? 'Owner' : 'Staff'}</Badge>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => {
            setMenuOpen(false)
            navigate('/settings')
          }}
        >
          <UserRound aria-hidden="true" /> Account
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            setMenuOpen(false)
            setConfirmLogoutAll(true)
          }}
        >
          <ShieldCheck aria-hidden="true" /> Sign out everywhere
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={handleLogout}>
          <LogOut aria-hidden="true" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )

  return (
    <div className="min-h-dvh bg-background lg:flex">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-card lg:sticky lg:top-0 lg:flex lg:h-dvh">
        <BusinessIdentity name={business.name} role={role} />
        <div className="flex-1 overflow-y-auto px-3">
          <NavLinks role={role} />
        </div>
        <div className="border-t border-border p-2">{accountMenu}</div>
      </aside>

      {/* Mobile header + drawer */}
      <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b border-border bg-card px-2 lg:hidden">
        <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
          <Menu className="size-6" aria-hidden="true" />
        </Button>
        <BrandMark size={32} />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{business.name}</p>
      </header>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent aria-describedby={undefined}>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Move between SokoWise sections</SheetDescription>
          <BusinessIdentity name={business.name} role={role} />
          <div className="flex-1 overflow-y-auto px-3">
            <NavLinks role={role} onNavigate={() => setMenuOpen(false)} />
          </div>
          <div className="border-t border-border p-2">{accountMenu}</div>
        </SheetContent>
      </Sheet>

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </div>
      </main>

      <ConfirmDialog
        open={confirmLogoutAll}
        onOpenChange={setConfirmLogoutAll}
        title="Sign out everywhere?"
        description="Every phone and computer signed in to your account will be signed out, including this one."
        confirmLabel="Sign out everywhere"
        destructive
        onConfirm={async () => {
          try {
            await logoutAll()
          } finally {
            navigate('/login', { replace: true })
          }
        }}
      />
    </div>
  )
}
