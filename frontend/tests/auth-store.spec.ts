import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { TOKEN_STORAGE_KEY } from '../src/api/http'
import { useAuthStore } from '../src/stores/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('clears token and profile when signing out', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'temporary-token')
    const store = useAuthStore()
    store.token = 'temporary-token'
    store.user = {
      id: 1,
      username: 'admin',
      display_name: '系统管理员',
      roles: ['ADMIN'],
      permissions: ['system.view'],
    }

    store.signOut()

    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })
})
