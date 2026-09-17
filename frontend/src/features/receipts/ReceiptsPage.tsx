import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Camera, FileImage } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { BackLink } from '@/components/ui/back-link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatDateTime } from '@/lib/dates'
import { formatKsh } from '@/lib/money'

import { ACCEPTED_TYPES, MAX_RECEIPT_BYTES, receiptsApi } from './api'
import { receiptKeys, useReceipts } from './hooks'
import { checkReceiptFile, describeReceiptError, STATUS_LABELS } from './status'

export default function ReceiptsPage() {
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const receipts = useReceipts()
  const inputRef = useRef<HTMLInputElement>(null)
  const [fileError, setFileError] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const uploaded = await receiptsApi.upload(file)
      // Read it straight away; a failure here still leaves the upload for a retry.
      try {
        return await receiptsApi.process(uploaded.id)
      } catch (error) {
        toast.error(describeReceiptError(error))
        return uploaded
      }
    },
    onSuccess: (receipt) => {
      void queryClient.invalidateQueries({ queryKey: receiptKeys.all })
      navigate(`/inventory/receipts/${receipt.id}`)
    },
  })

  const pick = (file: File | undefined) => {
    setFileError(null)
    if (!file) return
    const problem = checkReceiptFile(file)
    if (problem) {
      setFileError(problem)
      return
    }
    upload.mutate(file)
  }

  return (
    <>
      <BackLink to="/inventory">Inventory</BackLink>
      <PageHeader title="Supplier receipts" description="Photograph a supplier receipt and SokoWise reads it into a restock for you to check and confirm." />
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Scan a receipt</CardTitle>
          <CardDescription>JPEG, PNG or WebP, up to {Math.round(MAX_RECEIPT_BYTES / 1024 / 1024)} MB. Nothing is added to stock until you confirm it.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <input ref={inputRef} id="receipt-file" type="file" accept={ACCEPTED_TYPES.join(',')} capture="environment" className="sr-only" aria-label="Receipt photo" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button size="lg" onClick={() => inputRef.current?.click()} loading={upload.isPending}><Camera aria-hidden="true" /> Take or choose a photo</Button>
          </div>
          {upload.isPending && <p className="text-sm text-muted-foreground" role="status">Uploading and reading the receipt…</p>}
          {fileError && <Alert variant="destructive" role="alert">{fileError}</Alert>}
          {upload.isError && <Alert variant="destructive" role="alert">{describeReceiptError(upload.error)}</Alert>}
        </CardContent>
      </Card>

      {receipts.isPending ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      ) : receipts.isError ? (
        <ErrorState error={receipts.error} title="Could not load receipts" onRetry={() => receipts.refetch()} />
      ) : receipts.data.length === 0 ? (
        <EmptyState icon={FileImage} title="No receipts yet" description="Your scanned supplier receipts will appear here with their status." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Receipt</TableHead>
              <TableHead className="hidden sm:table-cell">Uploaded</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {receipts.data.map((r) => (
              <TableRow key={r.id} className="cursor-pointer" onClick={() => navigate(`/inventory/receipts/${r.id}`)}>
                <TableCell>
                  <button type="button" className="font-medium hover:underline" onClick={(e) => { e.stopPropagation(); navigate(`/inventory/receipts/${r.id}`) }}>
                    {r.supplier_name ?? r.original_filename ?? 'Receipt'}
                  </button>
                  <span className="block text-xs text-muted-foreground">{[r.receipt_number, r.line_count ? `${r.line_count} ${r.line_count === 1 ? 'line' : 'lines'}` : null].filter(Boolean).join(' · ')}</span>
                </TableCell>
                <TableCell className="hidden whitespace-nowrap text-muted-foreground sm:table-cell">{formatDateTime(r.created_at, tz)}</TableCell>
                <TableCell className="tabular text-right">{r.extracted_total ? formatKsh(r.extracted_total) : '—'}</TableCell>
                <TableCell><Badge variant={STATUS_LABELS[r.status].variant}>{STATUS_LABELS[r.status].label}</Badge></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  )
}
