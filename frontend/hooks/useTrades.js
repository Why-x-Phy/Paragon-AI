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
      
      // Mock data for now - replace with actual API call
      const mockData = {
        trades: [
          {
            id: 1,
            time: '14:32:15',
            trade: 'BUY BONK',
            amount: '$1,250.00',
            pnl: 125.50,
            pnl_formatted: '+$125.50',
            is_profitable: true,
            win_rate: 68.5,
            tx_hash: 'ABC123...'
          },
          {
            id: 2,
            time: '13:45:22',
            trade: 'SELL JUP',
            amount: '$850.00',
            pnl: -45.25,
            pnl_formatted: '-$45.25',
            is_profitable: false,
            win_rate: 67.2,
            tx_hash: 'DEF456...'
          },
          {
            id: 3,
            time: '12:15:08',
            trade: 'BUY SOL',
            amount: '$2,100.00',
            pnl: 0,
            pnl_formatted: 'Pending',
            is_profitable: null,
            win_rate: 67.8,
            tx_hash: 'GHI789...'
          },
          {
            id: 4,
            time: '11:30:45',
            trade: 'BUY FARTCOIN',
            amount: '$500.00',
            pnl: 67.80,
            pnl_formatted: '+$67.80',
            is_profitable: true,
            win_rate: 69.1,
            tx_hash: 'JKL012...'
          },
          {
            id: 5,
            time: '10:55:12',
            trade: 'SELL BONK',
            amount: '$1,100.00',
            pnl: -23.40,
            pnl_formatted: '-$23.40',
            is_profitable: false,
            win_rate: 68.3,
            tx_hash: 'MNO345...'
          }
        ],
        stats: {
          total_trades: 25,
          current_win_rate: 67.5,
          total_pnl: 1250.75,
          profitable_trades: 17
        }
      };
      
      setData(mockData);
      
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades();
    
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchTrades, 30000);
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
