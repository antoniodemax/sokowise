/** Set on Vercel/`.env` as VITE_GOOGLE_CLIENT_ID; empty → the Google button is not rendered at all. */
export const GOOGLE_CLIENT_ID: string = ((import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? '').trim()
