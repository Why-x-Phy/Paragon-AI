/** @type {import('next').NextConfig} */
const nextConfig = {
  // Don't use static export since we have API routes that need server-side functionality
  // Static export is only for purely client-side apps
  
  images: {
    unoptimized: true,
  },
  
  env: {
    NEXTAUTH_URL: process.env.NEXTAUTH_URL,
  },
  
  async rewrites() {
    return [];
  },
};

export default nextConfig;
