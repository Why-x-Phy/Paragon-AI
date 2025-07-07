import { OracleJob } from "@switchboard-xyz/common"
import {
  AnchorUtils,
  PullFeed,
  getDefaultQueue,
  asV0Tx,
} from "@switchboard-xyz/on-demand";
import { CrossbarClient } from "@switchboard-xyz/common";

// Solana RPC URL from your config
const solanaRpcUrl = "https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d";

// Token configurations - you'll add more here
const tokenConfigs = {
  "TRUMP": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=TRUMPUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.TRUMP"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=TRUMP-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"TRUMP-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=TRUMP_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'TRUMP_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=TRUMPUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.result.list[?(@.symbol == 'TRUMPUSDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lastPrice"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid1Price"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask1Price"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    }
  ],
  
  "WIF": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.kraken.com/0/public/Ticker?pair=WIFUSD",
            "method": "METHOD_GET"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.result.WIFUSD.a[0]",
                  "aggregationMethod": "NONE"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.result.WIFUSD.b[0]",
                  "aggregationMethod": "NONE"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.result.WIFUSD.c[0]",
                  "aggregationMethod": "NONE"
                }
              }
            ]
          }
        }
      ]
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.binance.com/api/v3/ticker/price?symbol=WIFUSDC",
            "method": "METHOD_GET"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price",
            "aggregationMethod": "NONE"
          }
        }
      ]
    },
    {
      "tasks": [
        {
          "valueTask": {
            "big": "25000"
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "jupiterSwapTask": {
                    "inTokenAddress": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "outTokenAddress": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
                    "baseAmountString": "25000"
                  }
                }
              ]
            }
          }
        }
      ]
    }
  ],
  
  "BONK": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=BONKUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=BONKUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.BONK"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=BONK-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"BONK-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BONK_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'BONK_USDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BONK_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'BONK_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    }
  ],
  
  "FARTCOIN": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=FARTCOIN-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"FARTCOIN-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=FARTCOIN_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'FARTCOIN_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=FARTCOIN_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"FARTCOIN_USDC\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=FARTCOIN_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"FARTCOIN_USDT\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.kraken.com/0/public/Ticker?pair=FARTCOINUSD"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.result.FARTCOINUSD.a[0]"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.result.FARTCOINUSD.b[0]"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.result.FARTCOINUSD.c[0]"
                }
              }
            ]
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "JTO": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=JTOUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=JTOUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.JTO"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=JTO-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"JTO-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=JTO_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'JTO_USDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    }
  ],
  
  "JUP": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=JUPUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=JUPUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=JUP-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"JUP-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=JUP_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'JUP_USDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "MEW": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=MEW-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"MEW-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=MEW_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'MEW_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=MEWUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.result.list[?(@.symbol == 'MEWUSDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lastPrice"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid1Price"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask1Price"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=MEW_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"MEW_USDT\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "MNDE": [
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.MNDE"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=MNDE_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'MNDE_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.kucoin.com/api/v1/market/allTickers?symbol=MNDE-USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data.ticker[?(@.symbol == 'MNDE-USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.buy"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.sell"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "ORCA": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=ORCAUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.ORCA"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=ORCA_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'ORCA_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=ORCA_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"ORCA_USDT\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "PENGU": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=PENGUUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.PENGU"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=PENGU-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"PENGU-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=PENGU_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'PENGU_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "bed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "POPCAT": [
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.POPCAT"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=POPCAT-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"POPCAT-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=POPCAT_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'POPCAT_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=POPCAT_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"POPCAT_USDC\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "b9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "PYTH": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=PYTHUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.PYTH"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=PYTH-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"PYTH-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=PYTH_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'PYTH_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "RAY": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=RAYUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=RAY-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"RAY-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=RAY_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'RAY_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "RENDER": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=RENDERUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.RENDER"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=RENDER-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"RENDER-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=RENDER_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'RENDER_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=RENDER_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'RENDER_USDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    }
  ],
  
  "SPX": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=SPX_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'SPX_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=SPX_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"SPX_USDC\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.kraken.com/0/public/Ticker?pair=SPXUSD"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.result.SPXUSD.a[0]"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.result.SPXUSD.b[0]"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.result.SPXUSD.c[0]"
                }
              }
            ]
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.kucoin.com/api/v1/market/allTickers?symbol=SPX-USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data.ticker[?(@.symbol == 'SPX-USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.buy"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.sell"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "VIRTUAL": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=VIRTUALUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=VIRTUAL-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"VIRTUAL-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=VIRTUAL_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'VIRTUAL_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=VIRTUAL_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"VIRTUAL_USDT\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "W": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=WUSDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=W-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"W-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=W_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'W_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.mexc.com/open/api/v2/market/ticker?symbol=W_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.symbol == \"W_USDT\")]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.ask"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "eff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    }
  ],
  
  "SOL": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "valueTask": {
            "value": 1
          }
        },
        {
          "divideTask": {
            "job": {
              "tasks": [
                {
                  "httpTask": {
                    "url": "https://api.coinbase.com/v2/exchange-rates?currency=USD",
                    "headers": [
                      {
                        "key": "Accept",
                        "value": "application/json"
                      },
                      {
                        "key": "User-Agent",
                        "value": "Mozilla/5.0"
                      }
                    ]
                  }
                },
                {
                  "jsonParseTask": {
                    "path": "$.data.rates.SOL"
                  }
                }
              ]
            }
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=SOL-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"SOL-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=SOL_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'SOL_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=SOL_USDC"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'SOL_USDC')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    }
  ],
  
  "USDC": [
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.price"
          }
        }
      ],
      "weight": 4
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://www.okx.com/api/v5/market/index-tickers?instId=USDC-USD"
          }
        },
        {
          "jsonParseTask": {
            "path": "$.data[?(@.instId == \"USDC-USD\")].idxPx"
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "httpTask": {
            "url": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=USDC_USDT"
          }
        },
        {
          "jsonParseTask": {
            "path": "$[?(@.currency_pair == 'USDC_USDT')]"
          }
        },
        {
          "medianTask": {
            "tasks": [
              {
                "jsonParseTask": {
                  "path": "$.lowest_ask"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.highest_bid"
                }
              },
              {
                "jsonParseTask": {
                  "path": "$.last"
                }
              }
            ],
            "minSuccessfulRequired": 3
          }
        }
      ],
      "weight": 3
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "pythAddress": "eaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
            "pythConfigs": {
              "pythAllowedConfidenceInterval": 1
            }
          }
        }
      ],
      "weight": 2
    },
    {
      "tasks": [
        {
          "oracleTask": {
            "chainlinkAddress": "0x2946220288DbBF77dF0030fCecc2a8348CbBE32C",
            "chainlinkConfigs": {}
          }
        }
      ],
      "weight": 2
    }
  ],
  
  // ADD MORE TOKENS HERE AS YOU PROVIDE THEM  
  // etc.
};

// Results tracking
const deploymentResults: { [token: string]: { address: string, signature: string, error?: string } } = {};

async function deployTokenFeed(tokenSymbol: string, jobsConfig: any[]) {
  console.log(`\n🚀 Deploying ${tokenSymbol} feed...`);
  console.log('=' .repeat(50));
  
  try {
    // Convert JSON config to OracleJob format
    const jobs: OracleJob[] = jobsConfig.map((jobConfig: any) => {
      return new OracleJob(jobConfig);
    });

    console.log(`📊 Created ${jobs.length} oracle jobs for ${tokenSymbol}`);

    // Test simulation first
    console.log(`🧪 Testing ${tokenSymbol} simulation...`);
    const serializedJobs = jobs.map((oracleJob) => {
      const encoded = OracleJob.encodeDelimited(oracleJob).finish();
      const base64 = Buffer.from(encoded).toString("base64");
      return base64;
    });

    const response = await fetch("https://api.switchboard.xyz/api/simulate", {
      method: "POST",
      headers: [["Content-Type", "application/json"]],
      body: JSON.stringify({ cluster: "Mainnet", jobs: serializedJobs }),
    });

    if (!response.ok) {
      throw new Error(`Simulation failed: ${await response.text()}`);
    }

    const data = await response.json() as { result?: string };
    console.log(`✅ ${tokenSymbol} simulation SUCCESS: $${data.result || 'N/A'}`);

    // Proceed with deployment
    console.log(`📡 Deploying ${tokenSymbol} to mainnet...`);
    
    const queue = await getDefaultQueue(solanaRpcUrl);
    const crossbarClient = CrossbarClient.default();
    const payer = await AnchorUtils.initKeypairFromFile("./keypair.json");

    // Upload to Crossbar
    const { feedHash } = await crossbarClient.store(queue.pubkey.toBase58(), jobs);
    const [pullFeed, feedKeypair] = PullFeed.generate(queue.program);
    
    const initIx = await pullFeed.initIx({
      name: `${tokenSymbol} Price Feed`,
      queue: queue.pubkey,
      maxVariance: 1.0,
      minResponses: 1,              // Keep at 1 for maximum reliability
      feedHash: Buffer.from(feedHash.slice(2), "hex"),
      minSampleSize: 1,             // Minimum sample size
      maxStaleness: 600,            // Increase to 10 minutes for better availability
      payer: payer.publicKey,
    });

    const initTx = await asV0Tx({
      connection: queue.program.provider.connection,
      ixs: [initIx],
      payer: payer.publicKey,
      signers: [payer, feedKeypair],
      computeUnitPrice: 200_000,
      computeUnitLimitMultiple: 1.5,
    });

    const initSig = await queue.program.provider.connection.sendTransaction(initTx, {
      preflightCommitment: "processed",
      skipPreflight: false,
    });

    console.log(`✅ ${tokenSymbol} deployed successfully!`);
    console.log(`   Feed Address: ${feedKeypair.publicKey.toString()}`);
    console.log(`   Transaction: ${initSig}`);

    deploymentResults[tokenSymbol] = {
      address: feedKeypair.publicKey.toString(),
      signature: initSig
    };

    return feedKeypair.publicKey.toString();

  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    console.log(`❌ ${tokenSymbol} deployment failed: ${errorMessage}`);
    deploymentResults[tokenSymbol] = {
      address: '',
      signature: '',
      error: errorMessage
    };
    return null;
  }
}

async function batchDeploy() {
  console.log('🎯 Calvin AI Batch Feed Deployment');
  console.log('=' .repeat(60));
  console.log(`📋 Deploying ${Object.keys(tokenConfigs).length} token feeds...`);
  
  // Copy keypair for deployments
  console.log('🔑 Setting up keypair...');
  // You'll need to copy the keypair again: cp /home/ubuntu/.config/solana/id.json ./keypair.json
  
  const payer = await AnchorUtils.initKeypairFromFile("./keypair.json");
  console.log(`💰 Using wallet: ${payer.publicKey.toString()}`);
  
  // Get SOL balance
  const connection = new (await import('@solana/web3.js')).Connection(solanaRpcUrl);
  const balance = await connection.getBalance(payer.publicKey);
  console.log(`💸 Wallet balance: ${balance / 1e9} SOL`);
  
  const estimatedCost = Object.keys(tokenConfigs).length * 0.015;
  console.log(`📊 Estimated cost: ~${estimatedCost.toFixed(3)} SOL`);
  
  if (balance / 1e9 < estimatedCost) {
    console.log(`⚠️  WARNING: Low balance! You may need more SOL.`);
  }
  
  console.log('\n🚀 Starting deployments...\n');

  // Deploy each token
  for (const [tokenSymbol, jobsConfig] of Object.entries(tokenConfigs)) {
    await deployTokenFeed(tokenSymbol, jobsConfig);
    
    // Small delay between deployments
    await new Promise(resolve => setTimeout(resolve, 2000));
  }

  // Print final results
  console.log('\n📋 DEPLOYMENT SUMMARY');
  console.log('=' .repeat(60));
  
  for (const [token, result] of Object.entries(deploymentResults)) {
    if (result.error) {
      console.log(`❌ ${token}: FAILED - ${result.error}`);
    } else {
      console.log(`✅ ${token}: ${result.address}`);
    }
  }
  
  // Generate Python mapping for Calvin vault
  console.log('\n🐍 PYTHON MAPPING FOR CALVIN VAULT:');
  console.log('=' .repeat(60));
  console.log('SWITCHBOARD_ORACLE_MAPPING = {');
  
  for (const [token, result] of Object.entries(deploymentResults)) {
    if (!result.error) {
      console.log(`    # "${token}": "${result.address}",`);
    }
  }
  
  console.log('}');
  
  // Clean up keypair
  console.log('\n🧹 Cleaning up keypair file...');
  await import('fs').then(fs => fs.unlinkSync('./keypair.json'));
  console.log('✅ Keypair file removed for security');
}

// Run the batch deployment
if (import.meta.main) {
  batchDeploy().catch(console.error);
} 