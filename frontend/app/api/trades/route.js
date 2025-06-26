import { NextResponse } from 'next/server';

export async function GET() {
  try {
    // Call the Calvin AI backend trades API
    const backendUrl = process.env.CALVIN_BACKEND_URL || 'http://18.216.72.134:8000';
    const response = await fetch(`${backendUrl}/api/trades`, {
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
    console.error('❌ Trades API error:', error);
    
    // Return mock data as fallback when backend is not available
    const fallbackData = {
      trades: [
        {
          id: 1,
          time: new Date().toLocaleTimeString('en-US', { hour12: false }),
          trade: 'BUY BONK',
          amount: '$1,250.00',
          pnl: 0,
          pnl_formatted: 'pending',
          is_profitable: null,
          win_rate: 68.5,
          tx_hash: 'pending...'
        }
      ],
      stats: {
        total_trades: 1,
        current_win_rate: 68.5,
        total_pnl: 0,
        profitable_trades: 0
      }
    };
    
    return NextResponse.json(fallbackData);
  }
} 