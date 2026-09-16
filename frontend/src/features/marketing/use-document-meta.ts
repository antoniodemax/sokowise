import { useEffect } from 'react'

/** The public origin (no trailing slash) when deployment has set it; unset in development. */
export const PUBLIC_URL: string | undefined = (import.meta.env.VITE_PUBLIC_URL as string | undefined)?.replace(/\/$/, '') || undefined

function upsert(selector: string, create: () => HTMLElement, attr: string, value: string): () => void {
  let el = document.head.querySelector<HTMLElement>(selector)
  const created = !el
  el ??= create()
  const previous = el.getAttribute(attr)
  el.setAttribute(attr, value)
  if (created) document.head.append(el)
  return () => {
    if (created) el.remove()
    else if (previous !== null) el.setAttribute(attr, previous)
  }
}

/**
 * Title, description and — when the public origin is configured — canonical and
 * `og:url` for a public page. Restores the previous values on unmount so the
 * app's own title comes back after navigation.
 */
export function useDocumentMeta({ title, description, path }: { title: string; description: string; path: string }) {
  useEffect(() => {
    const previousTitle = document.title
    document.title = title
    const undo = [
      upsert('meta[name="description"]', () => Object.assign(document.createElement('meta'), { name: 'description' }), 'content', description),
    ]
    if (PUBLIC_URL) {
      const url = `${PUBLIC_URL}${path}`
      undo.push(
        upsert('link[rel="canonical"]', () => Object.assign(document.createElement('link'), { rel: 'canonical' }), 'href', url),
        upsert('meta[property="og:url"]', () => { const m = document.createElement('meta'); m.setAttribute('property', 'og:url'); return m }, 'content', url),
        upsert('meta[property="og:image"]', () => { const m = document.createElement('meta'); m.setAttribute('property', 'og:image'); return m }, 'content', `${PUBLIC_URL}/brand/sokowise-og.png`),
        upsert('meta[name="twitter:image"]', () => Object.assign(document.createElement('meta'), { name: 'twitter:image' }), 'content', `${PUBLIC_URL}/brand/sokowise-og.png`),
      )
    }
    return () => {
      document.title = previousTitle
      undo.forEach((fn) => fn())
    }
  }, [title, description, path])
}
