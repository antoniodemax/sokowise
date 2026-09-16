import { Toaster as Sonner } from 'sonner'

export function Toaster() {
  return (
    <Sonner
      position="top-center"
      closeButton
      toastOptions={{
        classNames: {
          toast: 'rounded-lg border border-border bg-card text-foreground shadow-md',
          description: 'text-muted-foreground',
        },
      }}
    />
  )
}

