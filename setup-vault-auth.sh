#!/bin/bash

# Calvin Vault Discord OAuth Setup Script
# This script helps you set up Discord OAuth 2 and prepare for deployment

set -e

echo "🚀 Calvin Vault Discord OAuth Setup"
echo "=================================="
echo ""

# Check if we're in the right directory
if [ ! -d "frontend" ]; then
    echo "❌ Error: Run this script from the root directory of the Calvin Vault project"
    exit 1
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Error: Node.js is not installed. Please install Node.js first."
    exit 1
fi

# Check if dependencies are installed
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend
    npm install
    cd ..
    echo "✅ Dependencies installed"
fi

# Generate NextAuth secret
echo "🔐 Generating NextAuth secret..."
NEXTAUTH_SECRET=$(openssl rand -base64 32)
echo "✅ NextAuth secret generated"

# Create .env.local from template
echo "📝 Setting up environment file..."
cp frontend/.env.production.template frontend/.env.local

# Update the NextAuth secret in the file
if command -v sed &> /dev/null; then
    sed -i.bak "s/YOUR_NEXTAUTH_SECRET_HERE/$NEXTAUTH_SECRET/g" frontend/.env.local
    rm -f frontend/.env.local.bak
    echo "✅ NextAuth secret added to .env.local"
else
    echo "⚠️  Please manually replace YOUR_NEXTAUTH_SECRET_HERE with: $NEXTAUTH_SECRET"
fi

echo ""
echo "✅ Basic setup complete!"
echo ""
echo "📋 Next Steps:"
echo "1. Go to https://discord.com/developers/applications"
echo "2. Create a new application called 'Calvin Vault'"
echo "3. Go to OAuth2 tab and add redirect URI:"
echo "   - https://vault.cabalcalvin.com/api/auth/callback/discord"
echo "   - http://localhost:3000/api/auth/callback/discord"
echo "4. Copy Client ID and Client Secret"
echo "5. Go to Bot tab, create bot, and copy Bot Token"
echo "6. Get your Discord server ID (enable Developer Mode, right-click server)"
echo "7. Get your Discord role IDs (right-click each role)"
echo ""
echo "📁 Files to update:"
echo "   - frontend/.env.local (add your Discord credentials)"
echo "   - frontend/components/provider/DiscordAuthProvider.jsx (add role IDs)"
echo ""
echo "🧪 Test locally:"
echo "   cd frontend && npm run dev"
echo ""
echo "🚀 Deploy to Netlify:"
echo "   1. Connect your GitHub repo to Netlify"
echo "   2. Set build directory: frontend/"
echo "   3. Set build command: npm run deploy"  
echo "   4. Set publish directory: frontend/out"
echo "   5. Add environment variables from frontend/.env.local"
echo "   6. Set up custom domain: vault.cabalcalvin.com"
echo ""
echo "📖 Full guide: See DISCORD_OAUTH_DEPLOYMENT_GUIDE.md"
echo ""
echo "🎉 Happy coding!" 