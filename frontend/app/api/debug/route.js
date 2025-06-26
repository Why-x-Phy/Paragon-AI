import { NextResponse } from 'next/server';

export async function GET() {
  try {
    const debugInfo = {
      timestamp: new Date().toISOString(),
      environment: process.env.NODE_ENV,
      nextauth_url: process.env.NEXTAUTH_URL,
      discord_configured: !!(process.env.DISCORD_CLIENT_ID && process.env.DISCORD_CLIENT_SECRET),
      discord_server_id: process.env.DISCORD_SERVER_ID ? 'configured' : 'missing',
      required_role_id: process.env.REQUIRED_ROLE_ID ? 'configured' : 'missing',
      nextauth_secret: process.env.NEXTAUTH_SECRET ? 'configured' : 'missing',
      backend_url: process.env.CALVIN_BACKEND_URL || 'using default',
    };

    return NextResponse.json(debugInfo);
  } catch (error) {
    return NextResponse.json({ 
      error: 'Debug endpoint failed',
      message: error.message 
    }, { status: 500 });
  }
} 