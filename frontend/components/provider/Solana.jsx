"use client";

import React, { useMemo } from "react";
import {
  ConnectionProvider,
  WalletProvider,
} from "@solana/wallet-adapter-react";
import { WalletAdapterNetwork } from "@solana/wallet-adapter-base";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import { clusterApiUrl } from "@solana/web3.js";
import { PhantomWalletAdapter, SolflareWalletAdapter, LedgerWalletAdapter, WalletConnectWalletAdapter, CoinbaseWalletAdapter } from '@solana/wallet-adapter-wallets';

// Import the wallet adapter styles
import "@solana/wallet-adapter-react-ui/styles.css";

export const SolanaProvider = ({ children }) => {
  // The network can be set to 'devnet', 'testnet', or 'mainnet-beta'
  const network = WalletAdapterNetwork.Mainnet;

  // You can also provide a custom RPC endpoint
  const endpoint = useMemo(() => "https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d", []);

  // Configure connection config to support versioned transactions
  const connectionConfig = useMemo(() => ({
    commitment: 'confirmed',
    wsEndpoint: undefined,
    // Enable support for versioned transactions (version 0)
    // This is crucial for Pyth price feed transactions
    maxSupportedTransactionVersion: 0,
  }), []);

  const wallets = useMemo(
    () => [
      new PhantomWalletAdapter({ network }),
      new SolflareWalletAdapter({ network }),
      new LedgerWalletAdapter(),
      new WalletConnectWalletAdapter({ 
        network,
        options: {
          projectId: 'calvin-vault',
        }
      }),
      new CoinbaseWalletAdapter(),
    ],
    [network]
  );

  return (
    <ConnectionProvider endpoint={endpoint} config={connectionConfig}>
      <WalletProvider wallets={wallets} autoConnect>
        <WalletModalProvider>{children}</WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
};