// Calvin AI - Pyth Oracle Configuration

use anchor_lang::prelude::*;

// Pyth Price Feed IDs (hex strings) - includes USDC for NAV calculation
pub const PYTH_PRICE_FEEDS: &[(&str, &str)] = &[
    ("USDC", "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a"), // Base currency for NAV
    ("TRUMP", "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a"),
    ("RENDER", "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d"),
    ("JUP", "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996"),
    ("BONK", "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419"),
    ("FARTCOIN", "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608"),
    ("RAY", "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a"),
    ("JTO", "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2"),
    ("PYTH", "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff"),
    ("WIF", "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc"),
    ("VIRTUAL", "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b"),
    ("PENGU", "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61"),
    ("W", "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389"), // WORMHOLE
    ("POPCAT", "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce"),
    ("ATH", "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a"),
    ("MEW", "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d"),
    ("MNDE", "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a"),
    ("SPX", "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a"), // SPX6900
    ("ORCA", "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c"),
];

// Switchboard On-Demand Feed Addresses (Mainnet)
pub const SWITCHBOARD_FEEDS: &[(&str, &str)] = &[
    ("TRUMP", "9wcBMATS8bGLQ2UcRuYjsRAD7TPqB1CMhqfueBx78Uj2"),
    ("WIF", "8GqzQoqqKzJoNaWZtf2udVGV3Fn74W9DQayYu1S1zvkt"),
    ("ATH", "21JapEAFu8r8SAAQjB2fURfjiosnTHAFFm4S27qe4vVF"),
    ("BONK", "7GCiue6chgGuk6BvaurQNWD1Ervho8zEdcNWt5ZCYQhu"),
    ("FARTCOIN", "EE8Uyquv38j2JmyCiPprCNUxDBTrzpCXqR4hL3RGDUGh"),
    ("JTO", "E9fHVUZnvT4i8H3jQLb6g2tSpcagunJpjwCGNTYxwKSE"),
    ("JUP", "2F9M59yYc28WMrAymNWceaBEk8ZmDAjUAKULp8seAJF3"),
    ("MEW", "7Eev1vbsrgEmiRbVjyyFL8nqRKQt7jNPVtxiS4C6ewns"),
    ("MNDE", "CwtLbG7w71oCasCMYR8KARZYEVJK5x1GXdoYpqjctp7E"),
    ("ORCA", "BFWHemmj4ZtvqQVsWrGrFrL2U8tz7Lzq8nhy1KRMVezL"),
    ("PENGU", "DAG9yMr4FbTVd41Jojw6X589EHiPgR375SP5AdAAW7tH"),
    ("POPCAT", "5FWVcePyDK5jF6ZqFgmEMyu9qu5qdsswwvMd7GvRmfFW"),
    ("PYTH", "72ukr6M31f9cCzxvZT4Ba7AGyWSFLQGHjXU6WUzN4xD7"),
    ("RAY", "AJkAFiXdbMonys8rTXZBrRnuUiLcDFdkyoPuvrVKXhex"),
    ("RENDER", "B6xHth4K3fj3KK1TASXtHfbAReShYW3EihgwSKvhsugz"),
    ("SPX", "8m5YKLgnftRTcVXJLk7bV37xc2qrWR9TkXq4TY3FP3pz"),
    ("VIRTUAL", "34aJFwk2jTKmB2C6zWnT641ABCQv1P2ghrob57i1gFdg"),
    ("W", "DwjV47HwtHW5YR1CPndw3Fq1QMeYyvYA7jYXhMtcUCte"),
    ("SOL", "E8TLLh5jkYDvSXfAES7qe3s8Cfjj4hyvjksuvUHe8NEw"),
    ("USDC", "aHTvxuDvCRRnmJDDR1JkfLa4SpCNsgC4vDeLMEcN3zY"),
];

// Convert hex string to Pubkey (manual implementation without hex crate)
pub fn hex_string_to_pubkey(hex_str: &str) -> Result<Pubkey> {
    let hex_clean = hex_str.strip_prefix("0x").unwrap_or(hex_str);
    
    if hex_clean.len() != 64 {
        return Err(error!(crate::errors::ErrorCode::InvalidOracleAccount));
    }
    
    let mut bytes = [0u8; 32];
    for i in 0..32 {
        let byte_str = &hex_clean[i*2..i*2+2];
        bytes[i] = u8::from_str_radix(byte_str, 16)
            .map_err(|_| error!(crate::errors::ErrorCode::InvalidOracleAccount))?;
    }
    
    Ok(Pubkey::from(bytes))
}

// Get all oracle pubkeys for vault initialization
pub fn get_all_pyth_price_feeds() -> Vec<(&'static str, Pubkey)> {
    PYTH_PRICE_FEEDS
        .iter()
        .filter_map(|(symbol, hex_str)| {
            match hex_string_to_pubkey(hex_str) {
                Ok(pubkey) => Some((*symbol, pubkey)),
                Err(_) => {
                    msg!("Failed to parse oracle pubkey for {}: {}", symbol, hex_str);
                    None
                }
            }
        })
        .collect()
}

// Token mint to symbol mapping (from TRACKED_TOKENS)
pub const TOKEN_MINT_TO_SYMBOL: &[(&str, &str)] = &[
    ("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "USDC"), // Base currency
    ("6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN", "TRUMP"),
    ("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof", "RENDER"),
    ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "JUP"),
    ("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "BONK"),
    ("9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", "FARTCOIN"),
    ("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "RAY"),
    ("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL", "JTO"),
    ("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3npgxbkkTs8LG", "PYTH"),
    ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "WIF"),
    ("BUjZjAS2vbbb65g7Z1Ca9ZRVYoJscURG5L3AkVXHP2ac", "VIRTUAL"),
    ("3Bmj7x4udgJhKa43EYRcmNq2JLkgz7eAayFn8qYhyXKV", "PENGU"),
    ("85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ", "W"), // WORMHOLE
    ("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "POPCAT"),
    ("ATHdb8YvGvBVhgJB3PaMU5sCdAUHkhkN42jdYWK4h2xQ", "ATH"),
    ("MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5", "MEW"),
    ("MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey", "MNDE"),
    ("AUKyeqDfN8p6B93X9gYCnCpdJUfvxU6ZWEmAy2VKqm3w", "SPX"), // SPX6900
    ("orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE", "ORCA"),
];

// Get oracle pubkey for a specific token mint
pub fn get_oracle_for_token_mint(token_mint: &Pubkey) -> Option<Pubkey> {
    let token_mint_str = token_mint.to_string();
    
    // Find symbol for this token mint
    let symbol = TOKEN_MINT_TO_SYMBOL
        .iter()
        .find(|(mint, _)| *mint == token_mint_str)
        .map(|(_, symbol)| *symbol)?;
    
    // Find oracle for this symbol
    PYTH_PRICE_FEEDS
        .iter()
        .find(|(feed_symbol, _)| *feed_symbol == symbol)
        .and_then(|(_, hex_str)| hex_string_to_pubkey(hex_str).ok())
}

// Get Switchboard oracle for a specific token symbol
pub fn get_switchboard_oracle_for_symbol(symbol: &str) -> Option<Pubkey> {
    SWITCHBOARD_FEEDS
        .iter()
        .find(|(feed_symbol, _)| *feed_symbol == symbol)
        .and_then(|(_, addr_str)| addr_str.parse().ok())
}

// Get both Pyth and Switchboard oracles for a token symbol
pub fn get_dual_oracle_config(symbol: &str) -> (Option<Pubkey>, Option<Pubkey>) {
    let pyth_oracle = PYTH_PRICE_FEEDS
        .iter()
        .find(|(feed_symbol, _)| *feed_symbol == symbol)
        .and_then(|(_, hex_str)| hex_string_to_pubkey(hex_str).ok());
    
    let switchboard_oracle = get_switchboard_oracle_for_symbol(symbol);
    
    (pyth_oracle, switchboard_oracle)
}

// Vault state update for oracle configuration - returns (oracle_accounts, token_oracle_mapping)
pub fn get_oracle_config_for_vault() -> (Vec<Pubkey>, Vec<(Pubkey, u8)>) {
    let feeds = get_all_pyth_price_feeds();
    let mut oracle_accounts = Vec::new();
    let mut token_oracle_mapping = Vec::new();
    
    for (index, (_symbol, oracle_pubkey)) in feeds.iter().enumerate() {
        oracle_accounts.push(*oracle_pubkey);
        
        // Map each token mint to its oracle index
        for (token_mint_str, symbol) in TOKEN_MINT_TO_SYMBOL.iter() {
            if *symbol == feeds[index].0 {
                if let Ok(token_mint) = token_mint_str.parse::<Pubkey>() {
                    token_oracle_mapping.push((token_mint, index as u8));
                }
            }
        }
    }
    
    (oracle_accounts, token_oracle_mapping)
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug)]
pub struct PythOracleInfo {
    pub symbol: String,
    pub oracle_pubkey: Pubkey,
    pub token_mint: Pubkey,
}

// Custom error for oracle operations
#[error_code]
pub enum OracleError {
    #[msg("Invalid oracle account")]
    InvalidOracleAccount,
    #[msg("Oracle not found for token")]
    OracleNotFound,
    #[msg("Stale oracle price")]
    StalePrice,
    #[msg("Invalid price data")]
    InvalidPriceData,
}