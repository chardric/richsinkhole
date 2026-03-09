// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { getServerUrl, getToken, clearAuth } from '../api/client'

interface AuthContextType {
  isAuthenticated: boolean
  serverUrl: string
  logout: () => void
  refreshAuth: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [serverUrl, setServerUrl] = useState('')

  const refreshAuth = useCallback(() => {
    const url = getServerUrl()
    const token = getToken()
    setIsAuthenticated(!!(url && token))
    setServerUrl(url)
  }, [])

  const handleLogout = useCallback(() => {
    clearAuth()
    setIsAuthenticated(false)
    setServerUrl('')
  }, [])

  useEffect(() => {
    refreshAuth()
  }, [refreshAuth])

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        serverUrl,
        logout: handleLogout,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
