#!/usr/bin/env node
const fs   = require('fs');
const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

const { AnchorUtils, PullFeed, getDefaultQueue, asV0Tx } = require('@switchboard-xyz/on-demand');
const { CrossbarClient }                                 = require('@switchboard-xyz/common');

(async () => {
  const { keypair: payer, connection } = await AnchorUtils.loadEnv();
  const queue    = await getDefaultQueue(connection.rpcEndpoint);
  const crossbar = CrossbarClient.default();

  const feedDir = __dirname;
  const files   = fs.readdirSync(feedDir).filter(f => f.endsWith('.json'));

  for (const file of files) {
    const feedDef = JSON.parse(fs.readFileSync(path.join(feedDir, file), 'utf8'));
    const { feedHash } = await crossbar.store(queue.pubkey.toBase58(), feedDef.jobs);

    const [pullFeed, feedKeypair] = PullFeed.generate(queue.program);
    const initIx = await pullFeed.initIx({
      name:          feedDef.name,
      queue:         queue.pubkey,
      maxVariance:   feedDef.maxVariance,
      minResponses:  feedDef.minResponses,
      feedHash:      Buffer.from(feedHash.slice(2), 'hex'),
      minSampleSize: feedDef.minSampleSize,
      maxStaleness:  feedDef.maxStaleness,
      payer:         payer.publicKey,
    });

    const tx = await asV0Tx({
      connection,
      ixs:     [initIx],
      payer:   payer.publicKey,
      signers: [payer, feedKeypair],
    });
    const sig = await connection.sendTransaction(tx, { skipPreflight: true });
    console.log(`${file} → ${pullFeed.publicKey.toBase58()} (tx: ${sig})`);
  }
})();

