'use client';

import { useState, useEffect } from 'react';
import { MOCK_DATA, UI } from '@/constants';

// This will be replaced with actual contract calls
export const useVaultData = () => {
  const [vaultData, setVaultData] = useState(MOCK_DATA);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    try {
      setIsLoading(true);
      // TODO: Replace with actual contract calls
      // const provider = new ethers.providers.Web3Provider(window.ethereum);
      // const vaultContract = new ethers.Contract(CONTRACTS.VAULT, VAULT_ABI, provider);
      // const data = await vaultContract.getVaultData();
      
      // For now, using mock data
      setVaultData(MOCK_DATA);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, UI.REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  return { vaultData, isLoading, error, refetch: fetchData };
}; 