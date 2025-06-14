import NextAuth from 'next-auth'
import DiscordProvider from 'next-auth/providers/discord'

const authOptions = {
  providers: [
    DiscordProvider({
      clientId: process.env.DISCORD_CLIENT_ID,
      clientSecret: process.env.DISCORD_CLIENT_SECRET,
      authorization: {
        params: {
          scope: 'identify email guilds guilds.members.read'
        }
      }
    })
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      // Persist the OAuth access_token to the token right after signin
      if (account) {
        token.accessToken = account.access_token
        token.discordId = profile.id
      }
      return token
    },
    async session({ session, token }) {
      // Send properties to the client
      session.accessToken = token.accessToken
      session.discordId = token.discordId
      
      // Fetch user's Discord guild member info using the user's access token
      try {
        const response = await fetch(
          `https://discord.com/api/v10/users/@me/guilds/${process.env.NEXT_PUBLIC_DISCORD_SERVER_ID}/member`,
          {
            headers: {
              Authorization: `Bearer ${token.accessToken}`,
            },
          }
        )
        
        if (response.ok) {
          const member = await response.json()
          session.roles = member.roles || []
        } else {
          console.error('Failed to fetch Discord roles:', response.status)
          session.roles = []
        }
      } catch (error) {
        console.error('Error fetching Discord roles:', error)
        session.roles = []
      }
      
      return session
    },
    async signIn({ user, account, profile }) {
      // Basic validation - check if user has access to the required guild
      try {
        const response = await fetch(
          `https://discord.com/api/v10/users/@me/guilds`,
          {
            headers: {
              Authorization: `Bearer ${account.access_token}`,
            },
          }
        )
        
        if (response.ok) {
          const guilds = await response.json()
          const hasAccess = guilds.some(guild => guild.id === process.env.NEXT_PUBLIC_DISCORD_SERVER_ID)
          
          if (hasAccess) {
            return true // User is a member of the server
          } else {
            console.log('User is not a member of the required Discord server')
            return false
          }
        } else {
          console.error('Failed to fetch user guilds:', response.status)
          return false
        }
      } catch (error) {
        console.error('Error checking Discord membership:', error)
        return true // Allow signin on error to avoid blocking users
      }
    }
  },
  session: {
    strategy: 'jwt',
  },
  secret: process.env.NEXTAUTH_SECRET,
  debug: process.env.NODE_ENV === 'development'
}

const handler = NextAuth(authOptions)
export { handler as GET, handler as POST } 