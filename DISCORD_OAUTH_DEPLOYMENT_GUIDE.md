# Calvin Vault Discord OAuth 2 + Subdomain Deployment Guide (Simplified)

## Overview
This guide shows how to deploy the Calvin Vault frontend with Discord OAuth 2 authentication as a subdomain of cabalcalvin.com. **Simplified for only '$CALVIN Whale' role access.**

## Prerequisites
- Discord Developer Account
- Access to cabalcalvin.com DNS settings  
- Netlify account
- Calvin Discord server admin access

---

## Part 1: Discord OAuth 2 Setup (Simplified)

### Step 1: Create Discord Application
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Name it "Calvin Vault"
4. Go to "OAuth2" tab

### Step 2: Configure OAuth2 Settings
```
Redirect URIs:
- https://vault.cabalcalvin.com/api/auth/callback/discord
- http://localhost:3000/api/auth/callback/discord (for development)

Scopes:
- identify
- email  
- guilds
- guilds.members.read
```

### Step 3: Get Discord Server Information
1. Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
2. Right-click your Calvin Discord server → "Copy Server ID"
3. Right-click the '$CALVIN Whale' role → "Copy Role ID"

**Note:** No Discord Bot creation required! We use OAuth2 tokens directly.

---

## Part 2: Environment Configuration

### Step 1: Update Environment Variables
Edit `frontend/.env.local`:

```env
# Discord OAuth 2 Configuration (Simplified)
DISCORD_CLIENT_ID=your_discord_client_id_from_step_1
DISCORD_CLIENT_SECRET=your_discord_client_secret_from_step_1
NEXTAUTH_URL=https://vault.cabalcalvin.com
NEXTAUTH_SECRET=generate_this_with_openssl_rand_base64_32
NEXT_PUBLIC_DISCORD_SERVER_ID=your_discord_server_id_from_step_3
```

### Step 2: Update Role Mapping
Edit `frontend/components/provider/DiscordAuthProvider.jsx`:

```javascript
const ROLE_MAPPINGS = {
  'CALVIN_WHALE': 'your_calvin_whale_role_id_here'
}
```

---

## Part 3: Subdomain Deployment

### Step 1: DNS Configuration
Add these DNS records to cabalcalvin.com:

```
Type: CNAME
Name: vault
Value: vault-cabalcalvin.netlify.app
TTL: 3600
```

### Step 2: Netlify Setup
1. Connect your repository to Netlify
2. Set build configuration:
   ```
   Base directory: frontend/
   Build command: npm run deploy
   Publish directory: frontend/out
   ```

### Step 3: Netlify Environment Variables
Add these to Netlify environment variables:

```
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret  
NEXTAUTH_URL=https://vault.cabalcalvin.com
NEXTAUTH_SECRET=your_nextauth_secret
NEXT_PUBLIC_DISCORD_SERVER_ID=your_discord_server_id
```

### Step 4: Custom Domain Setup
1. In Netlify, go to Site Settings → Domain Management
2. Add custom domain: `vault.cabalcalvin.com`
3. Netlify will provide SSL certificate automatically

---

## Part 4: Testing & Verification

### Step 1: Local Development Testing
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000` and test Discord login flow.

### Step 2: Production Testing
1. Deploy to Netlify
2. Visit `https://vault.cabalcalvin.com`
3. Test Discord OAuth flow
4. Verify role-based access control

### Step 3: Role Testing
Test with different Discord users:
- No roles → Should see "Access Denied"
- Has $CALVIN Whale role → Should see "$CALVIN Whale" with vault access
- Not in server → Should be denied at login

---

## Part 5: Security Considerations

### Step 1: Environment Security
- Never commit `.env.local` files
- Use different Discord applications for dev/prod
- Rotate secrets regularly

### Step 2: OAuth Token Security
- User OAuth tokens are handled securely by NextAuth
- No sensitive bot tokens stored client-side
- Discord API calls use user's own permissions

### Step 3: CORS & Security Headers
The Netlify configuration includes security headers:
- X-Frame-Options: DENY
- X-XSS-Protection: 1; mode=block
- Content-Security-Policy: Restricts resource loading

---

## Part 6: Troubleshooting

### Common Issues

#### Discord OAuth Errors
```
Error: "redirect_uri_mismatch"
Solution: Ensure redirect URI exactly matches in Discord app settings
```

#### Role Detection Not Working
```
Error: User always shows "No Access"
Solution: Check '$CALVIN Whale' role ID mapping in DiscordAuthProvider.jsx
```

#### Subdomain Not Loading
```
Error: DNS resolution fails
Solution: Verify CNAME record and Netlify custom domain setup
```

#### NextAuth Errors
```
Error: "NEXTAUTH_URL mismatch"
Solution: Ensure NEXTAUTH_URL matches exactly in all environments
```

---

## Part 7: Collaboration with Main Site

### For Main Site Developer
To integrate the vault subdomain with the main cabalcalvin.com site:

1. **Navigation Integration**
   Add a link to the vault in your main site navigation:
   ```html
   <a href="https://vault.cabalcalvin.com" target="_blank">
     Calvin Vault - $CALVIN Whale Access
   </a>
   ```

2. **Role Check Integration** (Optional)
   If you want to show vault access status on main site:
   ```javascript
   // Check if user has vault access
   const checkVaultAccess = async () => {
     try {
       const response = await fetch('https://vault.cabalcalvin.com/api/auth/session')
       const session = await response.json()
       return session.user ? true : false
     } catch (error) {
       return false
     }
   }
   ```

---

## Part 8: Deployment Commands

### Development
```bash
cd frontend
npm install
npm run dev
```

### Production Deployment
```bash
cd frontend
npm run deploy
```

This builds the static site and exports it to `frontend/out/` which Netlify will serve.

---

## Why No Bot Token?

**Simplified Approach:** We removed the Discord Bot Token requirement because:

1. **OAuth2 is Sufficient:** The Discord OAuth2 flow with `guilds.members.read` scope gives us access to user roles directly
2. **Better Security:** No sensitive bot tokens stored client-side
3. **Simpler Setup:** One less thing to configure and manage
4. **User Permissions:** Uses the user's own Discord permissions, which is more secure

**When You Might Need a Bot Token:**
- Server-side role management
- Automated role assignment
- Advanced server administration features

For this vault access system, OAuth2 user tokens are perfect!

---

## Quick Setup Summary

1. **Discord App:** Create application, set redirect URI, get Client ID/Secret
2. **Role ID:** Get '$CALVIN Whale' role ID from Discord
3. **Environment:** Set 5 environment variables (no bot token needed)
4. **Code:** Update role ID in `DiscordAuthProvider.jsx`
5. **Deploy:** Push to GitHub, connect to Netlify, add environment variables
6. **DNS:** Add CNAME record: `vault` → `vault-cabalcalvin.netlify.app`

That's it! Much simpler than the original multi-tier system. 