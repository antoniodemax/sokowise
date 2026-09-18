import { Toaster as Sonner } from 'sonner'

export function Toaster() {
  return (
    <Sonner
      position="top-center"
      closeButton
      richColors={false}
      duration={3500}
      toastOptions={{
        classNames: {
          toast: 'rounded-lg border border-border bg-card text-foreground shadow-md',
          success: '[&_[data-icon]]:text-success',
          error: '[&_[data-icon]]:text-destructive',
          description: 'text-muted-foreground',
        },
      }}
    />
  )
}

