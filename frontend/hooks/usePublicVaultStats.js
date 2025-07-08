/**
 * usePublicVaultStats Hook - Fetch vault statistics without wallet connection
 * Uses existing vault-client.js logic with a dummy public key
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Connection, PublicKey } from '@solana/web3.js';
import { VaultClient } from '@/lib/vault-client';
import { CONTRACTS } from '@/constants';

// Dummy wallet object for read-only operations
const createDummyWallet = () => ({
  publicKey: PublicKey.default, // Use default public key for read-only access
  connected: false,
  signTransaction: () => { throw new Error('Read-only mode'); },
  signAllTransactions: () => { throw new Error('Read-only mode'); },
});

export const usePublicVaultStats = () => {
  const [vaultStats, setVaultStats] = useState(null);
  const [totalStakedCalvin, setTotalStakedCalvin] = useState(null);
  const [loading, setLoading] = useState(true);
  const [initialFetchComplete, setInitialFetchComplete] = useState(false);
  const [error, setError] = useState(null);

  // Create vault client with dummy wallet for read-only operations
  const vaultClient = useMemo(() => {
    const dummyWallet = createDummyWallet();
    const connection = new Connection(CONTRACTS.RPC_ENDPOINT, {
      commitment: CONTRACTS.COMMITMENT,
      maxSupportedTransactionVersion: 0,
    });
    return new VaultClient(dummyWallet, connection);
  }, []);

  // Fetch vault statistics (public data)
  const fetchVaultStats = useCallback(async () => {
    if (!vaultClient) return;

    try {
      setError(null);
      const stats = await vaultClient.getVaultStats();
      setVaultStats(stats);
    } catch (err) {
      console.error('Error fetching public vault stats:', err);
      setError(err.message);
    }
  }, [vaultClient]);

  // Fetch total staked Calvin tokens (public data)
  const fetchTotalStakedCalvin = useCallback(async () => {
    if (!vaultClient) return;

    try {
      const totalStaked = await vaultClient.getTotalStakedCalvin();
      setTotalStakedCalvin(totalStaked);
    } catch (err) {
      console.error('Error fetching total staked Calvin:', err);
      // Don't overwrite error if vault stats already failed
      if (!error) {
        setError(err.message);
      }
    }
  }, [vaultClient, error]);

  // Fetch all public data
  const fetchPublicData = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([
        fetchVaultStats(),
        fetchTotalStakedCalvin()
      ]);
    } finally {
      setLoading(false);
      setInitialFetchComplete(true);
    }
  }, [fetchVaultStats, fetchTotalStakedCalvin]);

  // Refresh data function
  const refreshData = useCallback(async () => {
    await fetchPublicData();
  }, [fetchPublicData]);

  // Initial data fetch
  useEffect(() => {
    fetchPublicData();
  }, [fetchPublicData]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(refreshData, 30000);
    return () => clearInterval(interval);
  }, [refreshData]);

  return {
    vaultStats,
    totalStakedCalvin,
    loading: loading || !initialFetchComplete,
    error,
    refreshData,
  };
}; 