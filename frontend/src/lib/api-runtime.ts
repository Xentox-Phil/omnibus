import type { CreateClientConfig } from '#/api/client.gen'
import { env } from '#/env'

// Hey API calls this to build the runtime client config. We point it at the
// FastAPI backend (VITE_API_URL, default http://localhost:8000). Vite inlines
// VITE_* at build time, so this resolves on both server (SSR) and browser.
//
// Lives outside src/api/ because Hey API wipes its output dir on every gen.
export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: env.VITE_API_URL,
})
