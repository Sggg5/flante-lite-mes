import { afterEach, describe, expect, it, vi } from 'vitest'

import http from '../src/api/http'
import { describeImportError, describeRollbackError, IMPORT_REQUEST_TIMEOUT_MS, rollbackImport } from '../src/api/imports'

function axiosError(overrides: Record<string, unknown> = {}) {
  return { isAxiosError: true, ...overrides }
}

describe('large import request behavior', () => {
  afterEach(() => vi.restoreAllMocks())

  it('allows import processing for at most ten minutes', () => {
    expect(IMPORT_REQUEST_TIMEOUT_MS).toBe(600_000)
  })

  it('distinguishes file size, timeout, processing uncertainty and backend failure', () => {
    expect(describeImportError(axiosError({ response: { status: 413, data: {} } }))).toContain('文件过大')
    expect(describeImportError(axiosError({ code: 'ECONNABORTED' }))).toContain('后端可能仍在处理')
    expect(describeImportError(axiosError())).toContain('网络连接超时或中断')
    expect(describeImportError(axiosError({ response: { status: 500, data: { message: '虚拟失败' } } }))).toContain('后端处理失败：虚拟失败')
  })

  it('uses the ten minute timeout for rollback and gives rollback-specific timeout guidance', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: { status: 'ROLLED_BACK' } })

    await rollbackImport(42, '虚拟撤销原因')

    expect(post).toHaveBeenCalledWith(
      '/v1/imports/42/rollback',
      { reason: '虚拟撤销原因' },
      { timeout: 600_000 },
    )
    expect(describeRollbackError(axiosError({ code: 'ECONNABORTED' }))).toBe(
      '撤销请求超时，后端可能仍在执行，请刷新批次状态确认，不要重复提交',
    )
  })
})
