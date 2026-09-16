import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { describeError } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'

import { categoriesApi, type Category } from './api'
import { useCategories } from './hooks'

export function CategoriesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient()
  const categories = useCategories()
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<Category | null>(null)
  const [editName, setEditName] = useState('')
  const [removing, setRemoving] = useState<Category | null>(null)
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.categories.all })

  const create = useMutation({
    mutationFn: (value: string) => categoriesApi.create(value),
    onSuccess: () => { setName(''); void invalidate(); toast.success('Category added') },
    onError: (error) => toast.error(describeError(error)),
  })
  const rename = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => categoriesApi.rename(id, value),
    onSuccess: () => { setEditing(null); void invalidate(); void queryClient.invalidateQueries({ queryKey: queryKeys.products.all }) },
    onError: (error) => toast.error(describeError(error)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => categoriesApi.remove(id),
    onSuccess: () => { void invalidate(); toast.success('Category removed') },
    onError: (error) => toast.error(describeError(error)),
  })

  function submitNew(event: FormEvent) {
    event.preventDefault()
    if (name.trim()) create.mutate(name.trim())
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Categories</DialogTitle>
          <DialogDescription>Simple labels to group products, like Drinks or Cosmetics. A category in use cannot be removed.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submitNew} className="flex gap-2">
          <Input aria-label="New category name" placeholder="New category" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
          <Button type="submit" loading={create.isPending} disabled={!name.trim()}><Plus aria-hidden="true" /> Add</Button>
        </form>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {(categories.data ?? []).length === 0 && <li className="px-3 py-3 text-sm text-muted-foreground">No categories yet.</li>}
          {(categories.data ?? []).map((category) => (
            <li key={category.id} className="flex min-h-12 items-center gap-2 px-3 py-1.5">
              {editing?.id === category.id ? (
                <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); rename.mutate({ id: category.id, value: editName.trim() }) }}>
                  <Input aria-label="Category name" value={editName} onChange={(e) => setEditName(e.target.value)} maxLength={60} autoFocus />
                  <Button type="submit" size="sm" loading={rename.isPending}>Save</Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                </form>
              ) : (
                <>
                  <span className="flex-1 text-sm">{category.name}</span>
                  <Button size="icon" variant="ghost" aria-label={`Rename ${category.name}`} onClick={() => { setEditing(category); setEditName(category.name) }}><Pencil aria-hidden="true" /></Button>
                  <Button size="icon" variant="ghost" aria-label={`Remove ${category.name}`} onClick={() => setRemoving(category)}><Trash2 aria-hidden="true" /></Button>
                </>
              )}
            </li>
          ))}
        </ul>
        <ConfirmDialog
          open={!!removing}
          onOpenChange={(o) => !o && setRemoving(null)}
          title={`Remove “${removing?.name}”?`}
          description="Products keep their history; only the label disappears. This fails if any product still uses it."
          confirmLabel="Remove"
          destructive
          onConfirm={async () => { if (removing) await remove.mutateAsync(removing.id) }}
        />
      </DialogContent>
    </Dialog>
  )
}
