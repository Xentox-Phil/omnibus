import { defineConfig } from '@hey-api/openapi-ts'

// Generates a typed client + TanStack Query option factories from the FastAPI
// backend's OpenAPI. Run with `pnpm gen:api` while the backend is up
// (`uv run uvicorn app.main:app --port 8000` from ../backend).
//
// The generated `src/api/**` is committed so teammates can typecheck the
// frontend without the backend running.
export default defineConfig({
  input: process.env.OPENAPI_URL ?? 'http://localhost:8000/openapi.json',
  output: { path: 'src/api', format: 'prettier' },
  plugins: [
    {
      name: '@hey-api/client-fetch',
      // baseUrl + any per-request config is set at runtime from env. Kept
      // outside src/api/ because Hey API wipes its output dir on every gen.
      runtimeConfigPath: './src/lib/api-runtime.ts',
    },
    '@hey-api/schemas',
    { name: '@hey-api/sdk', asClass: false },
    { name: '@tanstack/react-query' },
  ],
})
