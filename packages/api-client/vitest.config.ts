import { defineConfig } from 'vitest/config'

// Unit tests must not read the build-time deployment environment.
//
// `apiBaseUrl` resolves from `import.meta.env.VITE_API_BASE_URL` and falls back
// to the relative "/api/v1" only when that variable is unset. The suite asserts
// the relative base in every URL expectation, which is correct — but CI exports
// VITE_API_BASE_URL for the demo build (the build and bundle-budget gates need
// it), and turbo.json lists it under `globalEnv`, so it leaked into `turbo run
// test` as well:
//
//   AssertionError: expected 'https://api.soymutdb.test/genes/Glyma...'
//                        to be '/api/v1/genes/Glyma.01G000100'
//
// vitest resolves `import.meta.env` from `process.env` first, so clearing the
// variable before the config is evaluated is what actually isolates the run.
// `test.env` alone is applied after module initialisation and is not sufficient.
delete process.env.VITE_API_BASE_URL
delete process.env.VITE_JBROWSE_BASE_URL
delete process.env.VITE_DEPLOYMENT_MODE

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    include: ['src/**/*.test.ts'],
    // Serial execution in a single forked child: keeps per-file module
    // isolation while avoiding worker IPC issues on newer Node runtimes.
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true,
        maxForks: 1,
      },
    },
    // Belt and braces: if a future Vitest changes resolution order, the values
    // are still blanked for the test environment.
    env: {
      VITE_API_BASE_URL: '',
      VITE_JBROWSE_BASE_URL: '',
      VITE_DEPLOYMENT_MODE: '',
    },
  },
})
