const { PublicKey } = require('@solana/web3.js');
const { getAssociatedTokenAddress } = require('@solana/spl-token');

async function checkATA() {
  const calvinMint = new PublicKey('CrWbUJ4kMgduYDVRK8bDXhNBHr8cScixi79nGdGejnb1');
  const wallet = new PublicKey('52da4YoPnFd2r6AMoRC3oSGoe3USLgMUVei7rK7JhdYo');
  
  const ata = await getAssociatedTokenAddress(calvinMint, wallet);
  
  console.log('Wallet:', wallet.toString());
  console.log('CALVIN Mint:', calvinMint.toString());
  console.log('Expected ATA:', ata.toString());
  console.log('Actual Token Account:', 'RT9HbCHygRdZk2LdDaxJt2wwwsYaKoL9p53V4bNxmLU');
  console.log('Match:', ata.toString() === 'RT9HbCHygRdZk2LdDaxJt2wwwsYaKoL9p53V4bNxmLU');
}

checkATA().catch(console.error); 