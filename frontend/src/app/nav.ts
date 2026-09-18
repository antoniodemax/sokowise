import { BarChart3, Boxes, LayoutDashboard, Package, Receipt, Settings, ShoppingCart, Smartphone, Sparkles, Users, type LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Only OWNER sees these (PRD §16); the backend enforces it regardless. */
  ownerOnly?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/sales', label: 'Sales', icon: ShoppingCart },
  { to: '/mpesa', label: 'M-Pesa', icon: Smartphone },
  { to: '/products', label: 'Products', icon: Package },
  { to: '/inventory', label: 'Inventory', icon: Boxes },
  { to: '/customers', label: 'Customers', icon: Users },
  { to: '/expenses', label: 'Expenses', icon: Receipt, ownerOnly: true },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, ownerOnly: true },
  { to: '/assistant', label: 'Copilot', icon: Sparkles, ownerOnly: true },
  { to: '/settings', label: 'Settings', icon: Settings },
]
