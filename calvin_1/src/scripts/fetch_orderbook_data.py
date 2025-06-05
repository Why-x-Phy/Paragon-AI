import requests
import json
import pandas as pd
from datetime import datetime
import argparse
import os
from dotenv import load_dotenv
import sys
from pathlib import Path

# Find and load environment variables from .env file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent  # Navigate to project root
root_env_path = project_root / '.env'

if root_env_path.exists():
    load_dotenv(root_env_path)
else:
    # Fallback to the current directory
    current_dir_env = current_file.parent.parent.parent / '.env'
    if current_dir_env.exists():
        load_dotenv(current_dir_env)
    else:
        # Last resort, try default behavior
        load_dotenv()

# Add project root to import path
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(scripts_dir)
sys.path.append(project_root)

def get_solana_token_historical_data(token_address, start_time, end_time, api_key):
    """
    Fetch historical transaction data for a specific Solana token
    
    Parameters:
    token_address (str): The mint address of the token
    start_time (str): Start time in ISO format (e.g., "2024-04-01T00:00:00Z")
    end_time (str): End time in ISO format (e.g., "2024-04-24T23:00:00Z")
    api_key (str): Your Bitquery API key
    
    Returns:
    pandas.DataFrame: DataFrame containing the historical transaction data
    """
    # Updated API endpoint
    url = "https://streaming.bitquery.io/eap"
    
    # GraphQL query with fixed format
    query = f"""
    query SolanaTokenHistoricalData {{
      Solana {{
        DEXTradeByTokens(
          where: {{
            Trade: {{
              Currency: {{ 
                MintAddress: {{ is: "{token_address}" }}
              }}
            }},
            Block: {{
              Time: {{ 
                since: "{start_time}", 
                till: "{end_time}" 
              }}
            }},
            Transaction: {{ 
              Result: {{ Success: true }} 
            }}
          }}
          limit: {{ count: 1000 }}
          orderBy: {{ descending: Block_Time }}
        ) {{
          Block {{
            Time
            Height
            Slot
          }}
          Trade {{
            Currency {{
              Name
              Symbol
              MintAddress
            }}
            Price
            PriceInUSD
            Amount
            AmountInUSD
            Side {{
              Type
              Amount
              Currency {{
                Symbol
                MintAddress
              }}
            }}
            Dex {{
              ProtocolName
              ProtocolFamily
              ProgramAddress
            }}
          }}
          Transaction {{
            Signature
            FeePayer
          }}
        }}
      }}
    }}
    """
    
    # Updated payload format
    payload = json.dumps({
       "query": query,
       "variables": {}
    })
    
    # Updated headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # Print request details for debugging
    print(f"Making request to: {url}")
    print(f"Headers: {headers['Content-Type']} + Authorization header")
    
    # Make the request
    response = requests.post(url, headers=headers, data=payload)
    
    # Print response status and headers for debugging
    print(f"Response status: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")
    
    if response.status_code == 200:
        try:
            data = response.json()
            print(f"Response received: {data.keys() if data else 'Empty response'}")
            
            # Print the full response for debugging (using the global json module)
            print(f"Full API response:\n{json.dumps(data, indent=2)[:1000]}...")  # Print first 1000 chars
            
            # First check if there are errors in the response
            if data and "errors" in data:
                print("API returned errors:")
                for error in data["errors"]:
                    print(f"  - {error.get('message', 'Unknown error')}")
                return pd.DataFrame()
            
            # Check if the response contains data
            if data and "data" in data and "Solana" in data["data"]:
                # Print entire data structure for debugging
                print(f"Data structure: {data['data'].keys()}")
                
                # Check if DEXTradeByTokens exists
                if "Solana" in data["data"] and data["data"]["Solana"] is not None and "DEXTradeByTokens" in data["data"]["Solana"]:
                    trades = data["data"]["Solana"]["DEXTradeByTokens"]
                    
                    # Debugging - check if we have trades
                    if not trades:
                        print("No trades found in the response")
                        return pd.DataFrame()
                    
                    print(f"Found {len(trades)} trades")
                    
                    # Convert to pandas DataFrame for easier analysis
                    results = []
                    for trade_data in trades:
                        block = trade_data.get("Block", {})
                        trade = trade_data.get("Trade", {})
                        transaction = trade_data.get("Transaction", {})
                        
                        # Extract base trade info
                        trade_info = {
                            "timestamp": block.get("Time"),
                            "block_height": block.get("Height"),
                            "block_slot": block.get("Slot"),
                            "token_name": trade.get("Currency", {}).get("Name"),
                            "token_symbol": trade.get("Currency", {}).get("Symbol"),
                            "token_address": trade.get("Currency", {}).get("MintAddress"),
                            "price": trade.get("Price"),
                            "price_usd": trade.get("PriceInUSD"),
                            "amount": trade.get("Amount"),
                            "amount_usd": trade.get("AmountInUSD"),
                            "dex_protocol": trade.get("Dex", {}).get("ProtocolName"),
                            "dex_family": trade.get("Dex", {}).get("ProtocolFamily"),
                            "dex_program": trade.get("Dex", {}).get("ProgramAddress"),
                            "transaction_signature": transaction.get("Signature"),
                            "fee_payer": transaction.get("FeePayer")
                        }
                        
                        # Add side info if available
                        if "Side" in trade and trade["Side"]:
                            side = trade["Side"]
                            trade_info.update({
                                "side_type": side.get("Type"),
                                "side_amount": side.get("Amount"),
                                "side_currency_symbol": side.get("Currency", {}).get("Symbol"),
                                "side_currency_address": side.get("Currency", {}).get("MintAddress")
                            })
                        
                        results.append(trade_info)
                    
                    return pd.DataFrame(results)
                else:
                    print("DEXTradeByTokens not found in the response")
                    return pd.DataFrame()
            else:
                print("No data found in the response")
                return pd.DataFrame()
        except Exception as e:
            print(f"Error processing response: {e}")
            return pd.DataFrame()
    else:
        print(f"Error: {response.status_code}")
        print(f"Response text: {response.text}")
        return pd.DataFrame()

def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Fetch historical transaction data for a Solana token')
    parser.add_argument('--token-address', type=str, required=True, 
                       help='The mint address of the token')
    parser.add_argument('--start-time', type=str, default="2025-04-01T00:00:00Z",
                       help='Start time in ISO format (e.g., "2025-04-01T00:00:00Z")')
    parser.add_argument('--end-time', type=str, default="2025-04-29T00:00:00Z",
                       help='End time in ISO format (e.g., "2025-04-29T00:00:00Z")')
    parser.add_argument('--output', type=str, default=None,
                       help='Output CSV file path (optional)')
    
    args = parser.parse_args()
    
    # Get API key from environment variables
    api_key = os.getenv("BITQUERY_API_KEY")
    if not api_key:
        print("Error: BITQUERY_API_KEY not found in .env file")
        return
    
    # Validate API key format and print first/last few characters for debugging
    if len(api_key) < 10:
        print("Warning: API key seems too short, please check the format")
    else:
        # Show first/last 3 chars for debugging without exposing full key
        print(f"Using API key: {api_key[:3]}...{api_key[-3:]}")
    
    print(f"Fetching transaction data for token: {args.token_address}")
    print(f"Time range: {args.start_time} to {args.end_time}")
    
    df = get_solana_token_historical_data(
        args.token_address, 
        args.start_time, 
        args.end_time, 
        api_key
    )
    
    if not df.empty:
        print(f"Retrieved {len(df)} transactions")
        print(df.head())
        
        # Save to CSV if output path is provided
        if args.output:
            df.to_csv(args.output, index=False)
            print(f"Data saved to {args.output}")
        else:
            # Save with default name based on token address
            output_file = f"{args.token_address}_transactions.csv"
            df.to_csv(output_file, index=False)
            print(f"Data saved to {output_file}")

# Run the script if executed directly
if __name__ == "__main__":
    main()