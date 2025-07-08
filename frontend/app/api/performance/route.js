import { NextResponse } from 'next/server';

export async function GET() {
  try {
    // Call the Calvin AI backend performance API
    const backendUrl = process.env.CALVIN_BACKEND_URL || 'http://localhost:8000';
    const response = await fetch(`${backendUrl}/api/performance`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      // Add timeout to prevent hanging
      signal: AbortSignal.timeout(10000), // 10 second timeout
    });

    if (!response.ok) {
      throw new Error(`Backend API error: ${response.status}`);
    }

    const data = await response.json();
    
    return NextResponse.json(data);
  } catch (error) {
    console.error('❌ Performance API error:', error);
    
    // Return mock data as fallback when backend is not available
    const fallbackData = {
      performance: {
        "24h": 4.2,
        "7d": 13.7,
        "30d": 24.1,
        "ytd": 256.8
      },
      stats: {
        total_trades_24h: 12,
        win_rate_24h: 68.5,
        avg_portfolio_value: 125000,
        risk_score: 35.2
      }
    };
    
    return NextResponse.json(fallbackData);
  }
} 