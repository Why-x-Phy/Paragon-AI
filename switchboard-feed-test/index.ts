import { OracleJob } from "@switchboard-xyz/common"
import {
  AnchorUtils,
  PullFeed,
  getDefaultQueue,
  getDefaultDevnetQueue,
  asV0Tx,
} from "@switchboard-xyz/on-demand";
import { CrossbarClient } from "@switchboard-xyz/common";

// Solana RPC URL from your config
const solanaRpcUrl = "https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d";

const jobs: OracleJob[] = [
  // Job 1: Binance TRUMP/USDC (weight 4)
  new OracleJob({
    tasks: [
      {
        httpTask: {
          url: "https://api.binance.com/api/v3/ticker/price?symbol=TRUMPUSDC"
        }
      },
      {
        jsonParseTask: {
          path: "$.price"
        }
      }
    ],
    weight: 4
  }),

  // Job 2: Coinbase with divide task (weight 4)
  new OracleJob({
    tasks: [
      {
        valueTask: {
          value: 1
        }
      },
      {
        divideTask: {
          job: {
            tasks: [
              {
                httpTask: {
                  url: "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                  headers: [
                    {
                      key: "Accept",
                      value: "application/json"
                    },
                    {
                      key: "User-Agent",
                      value: "Mozilla/5.0"
                    }
                  ]
                }
              },
              {
                jsonParseTask: {
                  path: "$.data.rates.TRUMP"
                }
              }
            ]
          }
        }
      }
    ],
    weight: 4
  }),

  // Job 3: OKX (weight 3)
  new OracleJob({
    tasks: [
      {
        httpTask: {
          url: "https://www.okx.com/api/v5/market/index-tickers?instId=TRUMP-USD"
        }
      },
      {
        jsonParseTask: {
          path: "$.data[?(@.instId == \"TRUMP-USD\")].idxPx"
        }
      }
    ],
    weight: 3
  }),

  // Job 4: Gate.io with median task (weight 3)
  new OracleJob({
    tasks: [
      {
        httpTask: {
          url: "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=TRUMP_USDT"
        }
      },
      {
        jsonParseTask: {
          path: "$[?(@.currency_pair == 'TRUMP_USDT')]"
        }
      },
      {
        medianTask: {
          tasks: [
            {
              jsonParseTask: {
                path: "$.lowest_ask"
              }
            },
            {
              jsonParseTask: {
                path: "$.highest_bid"
              }
            },
            {
              jsonParseTask: {
                path: "$.last"
              }
            }
          ],
          minSuccessfulRequired: 3
        }
      }
    ],
    weight: 3
  }),

  // Job 5: Bybit with median task (weight 3)
  new OracleJob({
    tasks: [
      {
        httpTask: {
          url: "https://api.bybit.com/v5/market/tickers?category=spot&symbol=TRUMPUSDC"
        }
      },
      {
        jsonParseTask: {
          path: "$.result.list[?(@.symbol == 'TRUMPUSDC')]"
        }
      },
      {
        medianTask: {
          tasks: [
            {
              jsonParseTask: {
                path: "$.lastPrice"
              }
            },
            {
              jsonParseTask: {
                path: "$.bid1Price"
              }
            },
            {
              jsonParseTask: {
                path: "$.ask1Price"
              }
            }
          ],
          minSuccessfulRequired: 3
        }
      }
    ],
    weight: 3
  })
];

console.log("Running TRUMP price feed simulation...\n");

// Print the jobs that are being run.
const jobJson = JSON.stringify({ jobs: jobs.map((job) => job.toJSON()) });
console.log(jobJson);
console.log();

// Serialize the jobs to base64 strings.
const serializedJobs = jobs.map((oracleJob) => {
  const encoded = OracleJob.encodeDelimited(oracleJob).finish();
  const base64 = Buffer.from(encoded).toString("base64");
  return base64;
});

// Call the simulation server.
const response = await fetch("https://api.switchboard.xyz/api/simulate", {
  method: "POST",
  headers: [["Content-Type", "application/json"]],
  body: JSON.stringify({ cluster: "Mainnet", jobs: serializedJobs }),
});

// Check response.
if (response.ok) {
  const data = await response.json();
  console.log(`Response is good (${response.status})`);
  console.log(JSON.stringify(data, null, 2));
} else {
  console.log(`Response is bad (${response.status})`);
  throw await response.text();
}

console.log("Storing and creating the feed...\n");

// Get the queue for mainnet
let queue = await getDefaultQueue(solanaRpcUrl);

// Get the crossbar server client
const crossbarClient = CrossbarClient.default();

// Get the payer keypair from local file
const payer = await AnchorUtils.initKeypairFromFile(
  "./keypair.json"
);
console.log("Using Payer:", payer.publicKey.toBase58(), "\n");

// Upload jobs to Crossbar, which pins valid feeds on ipfs
const { feedHash } = await crossbarClient.store(queue.pubkey.toBase58(), jobs);
const [pullFeed, feedKeypair] = PullFeed.generate(queue.program);
const initIx = await pullFeed.initIx({
  name: "ATH Price Feed", // the feed name (max 32 bytes)
  queue: queue.pubkey, // the queue of oracles to bind to
  maxVariance: 1.0, // the maximum variance allowed for the feed results
  minResponses: 1, // minimum number of responses of jobs to allow
  feedHash: Buffer.from(feedHash.slice(2), "hex"), // the feed hash
  minSampleSize: 1, // The minimum number of samples required for setting feed value
  maxStaleness: 300, // The maximum number of slots that can pass before a feed value is considered stale.
  payer: payer.publicKey, // the payer of the feed
});

const initTx = await asV0Tx({
  connection: queue.program.provider.connection,
  ixs: [initIx],
  payer: payer.publicKey,
  signers: [payer, feedKeypair],
  computeUnitPrice: 200_000,
  computeUnitLimitMultiple: 1.5,
});

// simulate the transaction
const simulateResult =
  await queue.program.provider.connection.simulateTransaction(initTx, {
    commitment: "processed",
  });
console.log(simulateResult);

const initSig = await queue.program.provider.connection.sendTransaction(
  initTx,
  {
    preflightCommitment: "processed",
    skipPreflight: false,
  }
);

console.log(`Feed ${feedKeypair.publicKey} initialized: ${initSig}`);