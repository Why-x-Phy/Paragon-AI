'use client'

import React from 'react'
import { useDiscordAuth } from './provider/DiscordAuthProvider'
import DiscordAuthButton from './DiscordAuthButton'

const ProtectedRoute = ({ children, requireVaultAccess = true }) => {
  const { isLoading, isAuthenticated, canAccessVault, userTier } = useDiscordAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading authentication...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="max-w-md w-full px-6 py-8 bg-white dark:bg-gray-800 rounded-xl shadow-lg text-center">
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
              Calvin Vault Access
            </h1>
            <p className="text-gray-600 dark:text-gray-400">
              Connect your Discord account to access the Calvin vault system
            </p>
          </div>
          
          <div className="mb-6">
            <DiscordAuthButton />
          </div>
          
          <div className="text-sm text-gray-500 dark:text-gray-400">
            <p>You must be a member of the Calvin Discord server with the <span className="font-medium text-green-600">$CALVIN Whale</span> role to access the vault.</p>
          </div>
        </div>
      </div>
    )
  }

  if (requireVaultAccess && !canAccessVault()) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="max-w-md w-full px-6 py-8 bg-white dark:bg-gray-800 rounded-xl shadow-lg text-center">
          <div className="mb-6">
            <div className="w-16 h-16 bg-red-100 dark:bg-red-900 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
              Access Denied
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              Your Discord account doesn't have the required role to access the Calvin vault.
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              Current status: <span className="font-medium">{userTier === 'NONE' ? 'No Role' : userTier}</span>
            </p>
          </div>
          
          <div className="mb-6">
            <DiscordAuthButton />
          </div>
          
          <div className="text-sm text-gray-500 dark:text-gray-400 space-y-2">
            <p>To access the vault, you need the <span className="font-medium text-green-600">$CALVIN Whale</span> role in the Calvin Discord server.</p>
            <div className="text-left bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
              <p className="font-medium mb-1">How to get access:</p>
              <ul className="space-y-1 text-xs">
                <li>• Hold the required amount of $CALVIN tokens</li>
                <li>• Get verified in the Calvin Discord server</li>
                <li>• Contact the Calvin team for role assignment</li>
              </ul>
            </div>
            <p className="pt-2">Contact the Calvin team if you believe this is an error.</p>
          </div>
        </div>
      </div>
    )
  }

  // User is authenticated and has vault access
  return (
    <>
      {children}
    </>
  )
}

export default ProtectedRoute 