// Calvin AI - Pyth Oracle Configuration
// Generated with manually found price feed IDs

use anchor_lang::prelude::*;

// Pyth Price Feed IDs (hex strings)
pub const PYTH_PRICE_FEEDS: &[(&str, &str)] = &[
    ("TRUMP", "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a"),
    ("RENDER", "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d"),
    ("JUP", "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996"),
    ("BONK", "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419"),
    ("FARTCOIN", "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608"),
    ("RAY", "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a"),
    ("JTO", "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2"),
    ("PYTH", "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff"),
    ("WIF", "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc"),
    ("SPX", "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a"),
    ("VIRTUAL", "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b"),
    ("PENGU", "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61"),
    ("W", "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389"),
    ("POPCAT", "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce"),
    ("ATH", "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a"),
    ("MEW", "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d"),
    ("ORCA", "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c"),
    ("MNDE", "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a"),
];

// Convert hex strings to Pubkeys
pub fn get_pyth_price_feed_pubkey(symbol: &str) -> Option<Pubkey> {
    for (feed_symbol, feed_id) in PYTH_PRICE_FEEDS {
        if *feed_symbol == symbol {
            // Remove 0x prefix and convert hex to bytes
            let hex_str = feed_id.strip_prefix("0x").unwrap_or(feed_id);
            if let Ok(bytes) = hex::decode(hex_str) {
                if bytes.len() == 32 {
                    return Some(Pubkey::new_from_array(
                        bytes.try_into().unwrap()
                    ));
                }
            }
        }
    }
    None
}

// Get all configured price feed pubkeys
pub fn get_all_pyth_price_feeds() -> Vec<(String, Pubkey)> {
    let mut feeds = Vec::new();
    
    for (symbol, feed_id) in PYTH_PRICE_FEEDS {
        let hex_str = feed_id.strip_prefix("0x").unwrap_or(feed_id);
        if let Ok(bytes) = hex::decode(hex_str) {
            if bytes.len() == 32 {
                let pubkey = Pubkey::new_from_array(bytes.try_into().unwrap());
                feeds.push((symbol.to_string(), pubkey));
            }
        }
    }
    
    feeds
}

// Token mint to symbol mapping (from TRACKED_TOKENS)
pub const TOKEN_MINT_TO_SYMBOL: &[(&str, &str)] = &[
    ("6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN", "TRUMP"),
    ("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof", "RENDER"),
    ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "JUP"),
    ("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "BONK"),
    ("9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", "FARTCOIN"),
    ("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "RAY"),
    ("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL", "JTO"),
    ("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "PYTH"),
    ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "WIF"),
    ("J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr", "SPX"),
    ("3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y", "VIRTUAL"),
    ("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv", "PENGU"),
    ("85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ", "W"),
    ("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "POPCAT"),
    ("Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7", "ATH"),
    ("MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5", "MEW"),
    ("orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE", "ORCA"),
    ("MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey", "MNDE"),
    // Note: GIGA (63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9) excluded - no oracle
];

// Get oracle index for a token mint
pub fn get_oracle_index_for_token(token_mint: &Pubkey) -> Option<u8> {
    let token_mint_str = token_mint.to_string();
    
    // Find symbol for this token mint
    let symbol = TOKEN_MINT_TO_SYMBOL
        .iter()
        .find(|(mint, _)| *mint == token_mint_str)
        .map(|(_, symbol)| *symbol)?;
    
    // Find oracle index for this symbol
    PYTH_PRICE_FEEDS
        .iter()
        .position(|(feed_symbol, _)| *feed_symbol == symbol)
        .map(|index| index as u8)
}

// Vault state update for oracle configuration
pub fn get_oracle_config_for_vault() -> (Vec<Pubkey>, Vec<(Pubkey, u8)>) {
    let feeds = get_all_pyth_price_feeds();
    let mut oracle_accounts = Vec::new();
    let mut token_oracle_mapping = Vec::new();
    
    // Add all oracle accounts
    for (_symbol, oracle_pubkey) in feeds.iter() {
        oracle_accounts.push(*oracle_pubkey);
    }
    
    // Map each token mint to its oracle index
    for (token_mint_str, symbol) in TOKEN_MINT_TO_SYMBOL {
        if let Ok(token_mint) = token_mint_str.parse::<Pubkey>() {
            if let Some(oracle_index) = get_oracle_index_for_token(&token_mint) {
                token_oracle_mapping.push((token_mint, oracle_index));
            }
        }
    }
    
    (oracle_accounts, token_oracle_mapping)
}

// Helper function to validate price feed
pub fn validate_price_feed(price_feed_account: &AccountInfo) -> Result<()> {
    // Add validation logic for Pyth price feed accounts
    // This should verify the account is owned by Pyth and has valid price data
    require!(
        price_feed_account.owner == &pyth_sdk_solana::ID,
        ErrorCode::InvalidPriceFeedAccount
    );
    Ok(())
}

#[error_code]
pub enum ErrorCode {
    #[msg("Invalid price feed account")]
    InvalidPriceFeedAccount,
}