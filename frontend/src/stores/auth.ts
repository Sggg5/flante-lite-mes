import { defineStore } from 'pinia'

import { getCurrentUser, login, type LoginPayload, type UserProfile } from '../api/auth'
import { TOKEN_STORAGE_KEY } from '../api/http'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_STORAGE_KEY) ?? '',
    user: null as UserProfile | null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
  },
  actions: {
    async signIn(payload: LoginPayload) {
      const result = await login(payload)
      this.token = result.access_token
      localStorage.setItem(TOKEN_STORAGE_KEY, result.access_token)
      this.user = await getCurrentUser()
    },
    async loadProfile() {
      if (this.token && !this.user) {
        this.user = await getCurrentUser()
      }
    },
    signOut() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    },
  },
})
