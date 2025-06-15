'use client'

import { signOut } from 'next-auth/react'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function SignOutPage() {
  const router = useRouter()

  useEffect(() => {
    const handleSignOut = async () => {
      try {
        await signOut({ 
          redirect: false,
          callbackUrl: '/' 
        })
        router.push('/')
      } catch (error) {
        console.error('Sign out error:', error)
        router.push('/')
      }
    }

    handleSignOut()
  }, [router])

  return (
    <div className="min-h-screen bg-black flex items-center justify-center">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <p className="text-white">Signing you out...</p>
      </div>
    </div>
  )
} 