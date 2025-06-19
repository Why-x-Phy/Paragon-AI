"use client";

import React from 'react';
import { useTrades } from '@/hooks/useTrades';

const TradesTable = () => {
  const { trades, stats, loading, error, refresh } = useTrades();

  const getPnlColor = (pnl, isProfit) => {
    if (pnl === 0) return 'text-gray-400'; // pending
    return isProfit ? 'text-green-400' : 'text-red-400';
  };

  const getWinRateColor = (rate) => {
    if (rate >= 70) return 'text-green-400';
    if (rate >= 60) return 'text-[#B73E15]'; // Orange theme
    if (rate >= 50) return 'text-yellow-400';
    return 'text-red-400';
  };

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4">
        <p className="text-red-300">Failed to load trades: {error}</p>
        <button 
          onClick={refresh}
          className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-sm hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="bg-black/85 rounded-lg shadow-sm border border-gray-700/50">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-700/50">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">Live Trades</h3>
          <div className="flex items-center space-x-6">
            <div className="text-sm">
              <span className="text-gray-300">Win Rate: </span>
              <span className={`font-semibold ${getWinRateColor(stats?.current_win_rate || 0)}`}>
                {(stats?.current_win_rate || 0).toFixed(1)}%
              </span>
            </div>
            <div className="text-sm">
              <span className="text-gray-300">Total P&L: </span>
              <span className={`font-semibold ${(stats?.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${(stats?.total_pnl || 0).toFixed(2)}
              </span>
            </div>
            <div className="text-sm text-gray-300">
              {stats?.total_trades || 0} trades
            </div>
            <button
              onClick={refresh}
              disabled={loading}
              className="px-3 py-1 bg-[#B73E15] text-white rounded text-sm hover:bg-[#8B2E10] disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-900/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Time
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Trade
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Amount
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                P&L
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Win Rate
              </th>
            </tr>
          </thead>
          <tbody className="bg-transparent divide-y divide-gray-700/30">
            {!trades || trades.length === 0 ? (
              <tr>
                <td colSpan="5" className="px-6 py-8 text-center text-gray-400">
                  {loading ? 'Loading trades...' : 'No recent trades'}
                </td>
              </tr>
            ) : (
              trades.map((trade) => (
                <tr key={trade.id} className="hover:bg-gray-800/30">
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-white">
                    {trade.time}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                      trade.trade.startsWith('BUY') 
                        ? 'bg-green-900/30 text-green-300 border border-green-500/30' 
                        : 'bg-red-900/30 text-red-300 border border-red-500/30'
                    }`}>
                      {trade.trade}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-white font-medium">
                    {trade.amount}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <span className={getPnlColor(trade.pnl, trade.is_profitable)}>
                      {trade.pnl_formatted}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <span className={getWinRateColor(trade.win_rate)}>
                      {trade.win_rate.toFixed(1)}%
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TradesTable;
