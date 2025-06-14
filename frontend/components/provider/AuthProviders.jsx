'use client'

import { SessionProvider } from 'next-auth/react'
import { DiscordAuthProvider } from './DiscordAuthProvider'

export const AuthProviders = ({ children }) => {
  return (
    <SessionProvider>
      <DiscordAuthProvider>
        {children}
      </DiscordAuthProvider>
    </SessionProvider>
  )
} 