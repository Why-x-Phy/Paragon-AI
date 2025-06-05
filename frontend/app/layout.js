import { PT_Sans, Orbitron } from "next/font/google";
import "./globals.css";
import { SolanaProvider } from "@/components/provider/Solana";
import "@solana/wallet-adapter-react-ui/styles.css";
import { Toaster } from "sonner";

const pt_sans = PT_Sans({
  variable: "--font-pt_sans",
  weight: ["400", "700"],
  subsets: ["latin"],
});

const orbitron = Orbitron({
  variable: "--font-orbitron",
  weight: ["600"],
  subsets: ["latin"],
});

export const metadata = {
  title: "Calvin DAPP",
  description: "Stake your tokens and get access to automated trading vaults.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body
        className={`${pt_sans.variable} ${orbitron.variable} antialiased`}
      >
        <SolanaProvider>
          {children}
          <Toaster
            position="bottom-right"
            theme="dark"
            closeButton
            richColors={false}
            toastOptions={{
              style: {
                background: "#171717",
                color: "white",
                border: "1px solid rgba(75, 85, 99, 0.3)",
                borderRadius: "0.5rem",
                padding: "0.75rem 1rem",
                boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.5)",
              },
              className: "toast-container",
            }}
          />
        </SolanaProvider>
      </body>
    </html>
  );
}
