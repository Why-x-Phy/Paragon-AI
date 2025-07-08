"use client";

import { useState, useEffect, useCallback } from 'react';

export const usePerformance = () => {
  const [data, setData] = useState({
    performance: { "24h": 0, "7d": 0, "30d": 0, "ytd": 0 },
    stats: { total_trades_24h: 0, win_rate_24h: 0, avg_portfolio_value: 0, risk_score: 0 }
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchPerformance = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Call the performance API
      const response = await fetch('/api/performance', {
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
        performance: {
          "24h": apiData.performance?.["24h"] || 0,
          "7d": apiData.performance?.["7d"] || 0,
          "30d": apiData.performance?.["30d"] || 0,
          "ytd": apiData.performance?.["ytd"] || 0
        },
        stats: {
          total_trades_24h: apiData.stats?.total_trades_24h || 0,
          win_rate_24h: apiData.stats?.win_rate_24h || 0,
          avg_portfolio_value: apiData.stats?.avg_portfolio_value || 0,
          risk_score: apiData.stats?.risk_score || 0
        }
      };
      
      setData(formattedData);
      console.log('✅ Performance data fetched:', formattedData);
      
    } catch (err) {
      console.error('❌ Failed to fetch performance:', err);
      setError(err.message);
      
      // Fallback to placeholder data on error
      setData({
        performance: { "24h": 4, "7d": 13, "30d": 24, "ytd": 256 },
        stats: { total_trades_24h: 0, win_rate_24h: 0, avg_portfolio_value: 0, risk_score: 0 }
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPerformance();
    
    // Auto-refresh every 60 seconds (same as trades)
    const interval = setInterval(fetchPerformance, 60000);
    return () => clearInterval(interval);
  }, [fetchPerformance]);

  return {
    performance: data.performance,
    stats: data.stats,
    loading,
    error,
    refresh: fetchPerformance,
  };
}; 