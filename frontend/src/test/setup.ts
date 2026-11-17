import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// findBy* and waitFor wait up to 3 s, not the 1 s default: a page that loads through several mocked requests can take
// longer than a second when the whole suite runs in parallel on a busy machine (live draft tests, 2026-11-17).
configure({ asyncUtilTimeout: 3000 })

afterEach(() => {
  cleanup()
})
