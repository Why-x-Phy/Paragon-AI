"use client";

import { useState, useEffect, useCallback } from 'react';

export const useTrades = () => {
  const [data, setData] = useState({ trades: [], stats: {} });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchTrades = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Call the real trades API
      const response = await fetch('/api/trades', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
      }

      const apiData = await response.json();
      
      // Ensure data structure matches what the component expects
      const formattedData = {
        trades: apiData.trades || [],
        stats: {
          total_trades: apiData.stats?.total_trades || 0,
          current_win_rate: apiData.stats?.current_win_rate || 0,
          total_pnl: apiData.stats?.total_pnl || 0,
          profitable_trades: apiData.stats?.profitable_trades || 0
        }
      };
      
      setData(formattedData);
      console.log('✅ Trades data fetched:', formattedData);
      
    } catch (err) {
      console.error('❌ Failed to fetch trades:', err);
      setError(err.message);
      
      // Fallback to empty state on error
      setData({ 
        trades: [], 
        stats: { 
          total_trades: 0, 
          current_win_rate: 0, 
          total_pnl: 0, 
          profitable_trades: 0 
        } 
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades();
    
    // Auto-refresh every 60 seconds to reduce rate limits
    const interval = setInterval(fetchTrades, 60000);
    return () => clearInterval(interval);
  }, [fetchTrades]);

  return {
    trades: data.trades,
    stats: data.stats,
    loading,
    error,
    refresh: fetchTrades,
  };
};
