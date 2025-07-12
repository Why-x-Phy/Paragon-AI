import NextAuth from 'next-auth'
import DiscordProvider from 'next-auth/providers/discord'

export const dynamic = 'force-dynamic'

const handler = NextAuth({
  providers: [
    DiscordProvider({
      clientId: process.env.DISCORD_CLIENT_ID,
      clientSecret: process.env.DISCORD_CLIENT_SECRET,
      authorization: {
        params: {
          scope: 'identify guilds.members.read'
        }
      }
    })
  ],
  trustHost: true,
  callbacks: {
    async signIn({ user, account }) {
      if (account.provider === 'discord') {
        try {
          console.log('🔍 Checking Discord guild membership for user:', user.name);
          
          const response = await fetch(`https://discord.com/api/v10/users/@me/guilds/${process.env.DISCORD_SERVER_ID}/member`, {
            headers: {
              Authorization: `Bearer ${account.access_token}`
            }
          })

          if (!response.ok) {
            console.log('❌ Failed to fetch Discord guild member info:', {
              status: response.status,
              statusText: response.statusText,
              serverId: process.env.DISCORD_SERVER_ID
            });
            return false
          }

          const data = await response.json()
          console.log('📋 User roles:', data.roles);
          
          // Support multiple required roles (comma-separated)
          const requiredRoles = (process.env.REQUIRED_ROLE_IDS || process.env.REQUIRED_ROLE_ID || '').split(',').filter(Boolean)
          console.log('🎯 Required roles:', requiredRoles);
          
          // Check if user has ANY of the required roles
          const hasRequiredRole = requiredRoles.some(roleId => data.roles.includes(roleId.trim()))
          
          if (!hasRequiredRole) {
            console.log('❌ User does not have any of the required roles:', requiredRoles)
            return false
          }

          console.log('✅ User authenticated successfully with required role')
        } catch (error) {
          console.error('❌ Discord role check error:', error)
          return false
        }
      }
      return true
    },
    async session({ session, token }) {
      session.user.discordId = token.sub
      return session
    }
  },
  pages: {
    signOut: '/auth/signout',
    error: '/auth/error'
  },
  secret: process.env.NEXTAUTH_SECRET,
  debug: process.env.NODE_ENV === 'development'
})

export { handler as GET, handler as POST } 