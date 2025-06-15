'use client'

import React, { createContext, useContext } from 'react'
import { useSession } from 'next-auth/react'

const DiscordAuthContext = createContext()

export const useDiscordAuth = () => {
  const context = useContext(DiscordAuthContext)
  if (!context) {
    throw new Error('useDiscordAuth must be used within a DiscordAuthProvider')
  }
  return context
}

export default function DiscordAuthProvider({ children }) {
  const { data: session, status } = useSession()
  
  const loading = status === 'loading'
  const isAuthenticated = !!session
  
  // Since role checking is done during sign-in, if user is authenticated, they have the required role
  const hasCalvinWhaleRole = !!session
  
  const value = {
    session,
    loading,
    isLoading: loading, // Alternative name used by ProtectedRoute
    isAuthenticated,
    hasCalvinWhaleRole,
    canAccessVault: () => hasCalvinWhaleRole, // Function that ProtectedRoute expects
    userTier: hasCalvinWhaleRole ? 'CALVIN_WHALE' : 'NONE', // Tier info for ProtectedRoute
    user: session?.user || null
  }

  return (
    <DiscordAuthContext.Provider value={value}>
      {children}
    </DiscordAuthContext.Provider>
  )
} 