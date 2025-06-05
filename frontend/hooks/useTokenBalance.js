'use client';

import { useState, useEffect } from 'react';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { CONTRACTS } from '@/constants';
import { PublicKey } from '@solana/web3.js';

export const useTokenBalance = () => {
  const { connection } = useConnection();
  const { publicKey } = useWallet();
  const [balances, setBalances] = useState({
    usdc: null,
    calvinToken: null,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const getTokenBalance = async (tokenMint) => {
    try {
      const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
        publicKey,
        { programId: TOKEN_PROGRAM_ID }
      );

      const tokenAccount = tokenAccounts.value.find(
        (account) => account.account.data.parsed.info.mint === tokenMint
      );

      if (tokenAccount) {
        return Number(tokenAccount.account.data.parsed.info.tokenAmount.uiAmount);
      }
      return 0;
    } catch (err) {
      console.error(`Error fetching balance for token ${tokenMint}:`, err);
      return 0;
    }
  };

  const fetchBalances = async () => {
    if (!publicKey) {
      setBalances({ usdc: null, calvinToken: null });
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);
      const [usdcBalance, calvinBalance] = await Promise.all([
        getTokenBalance(CONTRACTS.USDC),
        getTokenBalance(CONTRACTS.CALVIN_TOKEN)
      ]);

      setBalances({
        usdc: usdcBalance,
        calvinToken: calvinBalance
      });
      setError(null);
    } catch (err) {
      setError(err.message);
      console.error('Error fetching token balances:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchBalances();
    // Set up an interval to refresh balances
    const interval = setInterval(fetchBalances, 15000); // every 15 seconds
    return () => clearInterval(interval);
  }, [publicKey, connection]);

  return {
    balances,
    isLoading,
    error,
    refetch: fetchBalances
  };
}; 