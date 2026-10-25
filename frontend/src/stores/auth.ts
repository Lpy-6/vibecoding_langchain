import { create } from 'zustand'
import { api, refreshSession, setAccessToken } from '../api/client'
import type { User } from '../types'

interface AuthState {
  user: User | null
  bootstrapped: boolean
  bootstrap: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, displayName: string) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: User | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  bootstrapped: false,
  bootstrap: async () => {
    try {
      const data = await refreshSession()
      set({ user: data.user, bootstrapped: true })
    } catch {
      setAccessToken(null)
      set({ user: null, bootstrapped: true })
    }
  },
  login: async (username, password) => {
    const res = await api.post('/auth/login', { username, password })
    setAccessToken(res.data.access_token)
    set({ user: res.data.user, bootstrapped: true })
  },
  register: async (username, password, displayName) => {
    const res = await api.post('/auth/register', {
      username,
      password,
      display_name: displayName,
    })
    setAccessToken(res.data.access_token)
    set({ user: res.data.user, bootstrapped: true })
  },
  logout: async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      /* ignore */
    }
    setAccessToken(null)
    set({ user: null })
  },
  setUser: (user) => set({ user }),
}))
