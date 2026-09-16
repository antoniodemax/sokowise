import { Hammer } from 'lucide-react'

import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'

/** A section whose screens arrive in the next phase; the backend for it already exists. */
export default function ComingSoonPage({ section }: { section: string }) {
  return (
    <>
      <PageHeader title={section} />
      <EmptyState icon={Hammer} title={`${section} is coming next`} description="The backend for this section is ready; the screens are being built in the next phase." />
    </>
  )
}
