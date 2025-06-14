'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'

const DiscordAuthContext = createContext({})

// Simplified role mapping - only '$CALVIN Whale' role
const ROLE_MAPPINGS = {
  // Replace this with the actual Discord role ID for '$CALVIN Whale'
  'CALVIN_WHALE': '1334226419584208957'
}

// Simple tier check - either you're a Calvin Whale or you're not
const getTierFromRoles = (roles) => {
  if (!roles || !Array.isArray(roles)) return 'NONE'
  
  if (roles.includes(ROLE_MAPPINGS.CALVIN_WHALE)) return 'CALVIN_WHALE'
  
  return 'NONE'
}

export const DiscordAuthProvider = ({ children }) => {
  const { data: session, status } = useSession()
  const [discordUser, setDiscordUser] = useState(null)
  const [userTier, setUserTier] = useState('NONE')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (status === 'loading') {
      setIsLoading(true)
      return
    }

    if (session?.user) {
      const tier = getTierFromRoles(session.roles)
      
      setDiscordUser({
        id: session.discordId,
        name: session.user.name,
        email: session.user.email,
        image: session.user.image,
        roles: session.roles || [],
        tier: tier
      })
      
      setUserTier(tier)
    } else {
      setDiscordUser(null)
      setUserTier('NONE')
    }
    
    setIsLoading(false)
  }, [session, status])

  // Helper functions for role/tier checking
  const hasCalvinWhaleRole = () => {
    return discordUser?.roles?.includes(ROLE_MAPPINGS.CALVIN_WHALE) || false
  }

  const canAccessVault = () => {
    return userTier === 'CALVIN_WHALE'
  }

  const getAccessLevel = () => {
    return userTier === 'CALVIN_WHALE' ? '$CALVIN Whale Access' : 'No Access'
  }

  const contextValue = {
    discordUser,
    userTier,
    isLoading: isLoading || status === 'loading',
    isAuthenticated: !!session?.user,
    hasCalvinWhaleRole,
    canAccessVault,
    getAccessLevel,
    session
  }

  return (
    <DiscordAuthContext.Provider value={contextValue}>
      {children}
    </DiscordAuthContext.Provider>
  )
}

export const useDiscordAuth = () => {
  const context = useContext(DiscordAuthContext)
  if (!context) {
    throw new Error('useDiscordAuth must be used within a DiscordAuthProvider')
  }
  return context
} 