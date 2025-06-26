'use client'

import { useSession, signIn, signOut } from 'next-auth/react'
import { useEffect, useState } from 'react'

export default function TestAuth() {
  const { data: session, status } = useSession()
  const [debugInfo, setDebugInfo] = useState(null)
  const [browserInfo, setBrowserInfo] = useState(null)

  useEffect(() => {
    // Fetch debug info from our API endpoint
    fetch('/api/debug')
      .then(res => res.json())
      .then(data => setDebugInfo(data))
      .catch(err => console.error('Debug fetch failed:', err))

    // Set browser info only on client side
    if (typeof window !== 'undefined') {
      setBrowserInfo({
        userAgent: navigator.userAgent,
        url: window.location.href,
        cookiesEnabled: navigator.cookieEnabled,
        localStorageAvailable: typeof Storage !== 'undefined'
      })
    }
  }, [])

  const testDiscordAuth = async () => {
    console.log('Testing Discord auth...')
    try {
      const result = await signIn('discord', { redirect: false })
      console.log('Auth result:', result)
    } catch (error) {
      console.error('Auth error:', error)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">NextAuth Debug Page</h1>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Session Info */}
          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4">Session Status</h2>
            <div className="space-y-2">
              <p><strong>Status:</strong> {status}</p>
              <p><strong>Authenticated:</strong> {session ? 'Yes' : 'No'}</p>
              {session && (
                <>
                  <p><strong>User:</strong> {session.user?.name}</p>
                  <p><strong>Email:</strong> {session.user?.email}</p>
                  <p><strong>Discord ID:</strong> {session.user?.discordId}</p>
                </>
              )}
            </div>
          </div>

          {/* Debug Info */}
          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4">Configuration</h2>
            {debugInfo ? (
              <div className="space-y-2 text-sm">
                <p><strong>Environment:</strong> {debugInfo.environment}</p>
                <p><strong>NextAuth URL:</strong> {debugInfo.nextauth_url}</p>
                <p><strong>Discord Configured:</strong> {debugInfo.discord_configured ? '✅' : '❌'}</p>
                <p><strong>Discord Server ID:</strong> {debugInfo.discord_server_id}</p>
                <p><strong>Required Role ID:</strong> {debugInfo.required_role_id}</p>
                <p><strong>NextAuth Secret:</strong> {debugInfo.nextauth_secret}</p>
                <p><strong>Backend URL:</strong> {debugInfo.backend_url}</p>
              </div>
            ) : (
              <p>Loading debug info...</p>
            )}
          </div>

          {/* Test Buttons */}
          <div className="bg-gray-800 p-6 rounded-lg md:col-span-2">
            <h2 className="text-xl font-semibold mb-4">Test Actions</h2>
            <div className="flex gap-4">
              {!session ? (
                <button 
                  onClick={testDiscordAuth}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded transition-colors"
                >
                  Test Discord Auth
                </button>
              ) : (
                <button 
                  onClick={() => signOut()}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded transition-colors"
                >
                  Sign Out
                </button>
              )}
              
              <button 
                onClick={() => typeof window !== 'undefined' && window.location.reload()}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded transition-colors"
              >
                Refresh Page
              </button>
            </div>
          </div>

          {/* Browser Info */}
          <div className="bg-gray-800 p-6 rounded-lg md:col-span-2">
            <h2 className="text-xl font-semibold mb-4">Browser Info</h2>
            {browserInfo ? (
              <div className="space-y-2 text-sm">
                <p><strong>User Agent:</strong> {browserInfo.userAgent}</p>
                <p><strong>URL:</strong> {browserInfo.url}</p>
                <p><strong>Cookies Enabled:</strong> {browserInfo.cookiesEnabled ? 'Yes' : 'No'}</p>
                <p><strong>Local Storage:</strong> {browserInfo.localStorageAvailable ? 'Available' : 'Not Available'}</p>
              </div>
            ) : (
              <p>Loading browser info...</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
} 