import NextAuth from 'next-auth'
import DiscordProvider from 'next-auth/providers/discord'

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
          const response = await fetch(`https://discord.com/api/v10/users/@me/guilds/${process.env.DISCORD_SERVER_ID}/member`, {
            headers: {
              Authorization: `Bearer ${account.access_token}`
            }
          })

          if (!response.ok) {
            console.log('Failed to fetch Discord guild member info:', response.status)
            return false
          }

          const data = await response.json()
          const hasRequiredRole = data.roles.includes(process.env.REQUIRED_ROLE_ID)
          
          if (!hasRequiredRole) {
            console.log('User does not have required role:', process.env.REQUIRED_ROLE_ID)
            return false
          }

          console.log('User authenticated successfully with required role')
        } catch (error) {
          console.error('Discord role check error:', error)
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