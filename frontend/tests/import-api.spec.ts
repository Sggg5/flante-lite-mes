import { describe, expect, it } from 'vitest'

import { describeImportError, IMPORT_REQUEST_TIMEOUT_MS } from '../src/api/imports'

function axiosError(overrides: Record<string, unknown> = {}) {
  return { isAxiosError: true, ...overrides }
}

describe('large import request behavior', () => {
  it('allows import processing for at most ten minutes', () => {
    expect(IMPORT_REQUEST_TIMEOUT_MS).toBe(600_000)
  })

  it('distinguishes file size, timeout, processing uncertainty and backend failure', () => {
    expect(describeImportError(axiosError({ response: { status: 413, data: {} } }))).toContain('文件过大')
    expect(describeImportError(axiosError({ code: 'ECONNABORTED' }))).toContain('后端可能仍在处理')
    expect(describeImportError(axiosError())).toContain('网络连接超时或中断')
    expect(describeImportError(axiosError({ response: { status: 500, data: { message: '虚拟失败' } } }))).toContain('后端处理失败：虚拟失败')
  })
})
