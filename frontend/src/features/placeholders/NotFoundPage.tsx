import { Compass } from 'lucide-react'
import { Link } from 'react-router'

import { buttonVariants } from '@/components/ui/button-variants'
import { EmptyState } from '@/components/ui/empty-state'

export default function NotFoundPage() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      description="That link does not go anywhere in SokoWise."
      action={
        <Link to="/dashboard" className={buttonVariants({ variant: 'outline' })}>
          Back to the dashboard
        </Link>
      }
    />
  )
}
