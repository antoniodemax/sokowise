import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { describeError } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'

import { adminApi, type PlatformBusinessRow } from './api'

/**
 * Deleting an account is the one thing on the admin page that cannot be undone, so the
 * operator has to type the business name before the button works.
 */
export function DeleteBusinessDialog({ business, onOpenChange }: { business: PlatformBusinessRow | null; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient()
  const [typed, setTyped] = useState('')
  const mutation = useMutation({
    mutationFn: (id: string) => adminApi.deleteBusiness(id),
    onSuccess: (result) => {
      toast.success(`${result.name} deleted`, { description: `${result.users_deleted} ${result.users_deleted === 1 ? 'person' : 'people'} removed with it.` })
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.overview })
      close(false)
    },
  })
  function close(open: boolean) {
    if (mutation.isPending) return
    if (!open) { setTyped(''); mutation.reset() }
    onOpenChange(open)
  }
  const matches = business !== null && typed.trim() === business.name

  return (
    <Dialog open={business !== null} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {business?.name}?</DialogTitle>
          <DialogDescription>
            This removes the business and everything it recorded: products, sales, customers and their debts, expenses, receipts and M-Pesa messages. People who belong only to this business lose their login. It cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {business && (
          <dl className="grid grid-cols-3 gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs">
            <div><dt className="text-muted-foreground">Products</dt><dd className="tabular font-medium">{business.products}</dd></div>
            <div><dt className="text-muted-foreground">Sales</dt><dd className="tabular font-medium">{business.sales}</dd></div>
            <div><dt className="text-muted-foreground">Last sale</dt><dd className="font-medium">{business.last_sale_at ? 'recorded' : 'never'}</dd></div>
          </dl>
        )}
        <Field id="confirm-name" label={`Type ${business?.name ?? 'the business name'} to confirm`}>
          <Input id="confirm-name" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={business?.name} />
        </Field>
        {mutation.isError && <Alert variant="destructive" role="alert">{describeError(mutation.error)}</Alert>}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)} disabled={mutation.isPending}>Cancel</Button>
          <Button variant="destructive" disabled={!matches} loading={mutation.isPending} onClick={() => business && mutation.mutate(business.id)}>
            <Trash2 aria-hidden="true" /> Delete business
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
