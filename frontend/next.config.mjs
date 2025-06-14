/** @type {import('next').NextConfig} */
const nextConfig = {
  // Only use static export for production builds
  ...(process.env.NODE_ENV === 'production' && {
    output: 'export',
    trailingSlash: true,
    assetPrefix: 'https://vault.cabalcalvin.com',
  }),
  
  images: {
    unoptimized: true,
  },
  
  env: {
    NEXTAUTH_URL: process.env.NEXTAUTH_URL,
  },
  
  // Only add rewrites for development (when not using static export)
  ...(process.env.NODE_ENV !== 'production' && {
    async rewrites() {
      return [];
    },
  }),
};

export default nextConfig;
