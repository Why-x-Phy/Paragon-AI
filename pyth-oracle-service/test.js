console.log('Testing imports...');

Promise.all([
  import('@pythnetwork/hermes-client'), 
  import('@pythnetwork/pyth-solana-receiver')
]).then(() => {
  console.log('✅ Both packages work!');
}).catch(err => {
  console.error('❌ Error:', err.message);
});
