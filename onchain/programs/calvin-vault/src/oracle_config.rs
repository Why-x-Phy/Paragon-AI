// Calvin AI - Pyth Oracle Configuration

use anchor_lang::prelude::*;
// Updated for modern Pyth pull oracle SDK
use pyth_solana_receiver_sdk::price_update::PriceUpdateV2;

// Pyth Price Feed IDs (hex strings) - used with Hermes API for pull oracle model
pub const PYTH_PRICE_FEEDS: &[(&str, &str)] = &[
    ("USDC", "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a"), // Base currency for NAV
    ("SOL", "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d"), // Added SOL Pyth feed
    ("TRUMP", "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a"),
    ("RENDER", "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d"),
    ("JUP", "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996"),
    ("BONK", "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419"),
    ("FARTCOIN", "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608"),
    ("RAY", "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a"),
    ("JTO", "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2"),
    ("PYTH", "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff"),
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
    ("TRUMP", "D9jeEiEr4PkDCM7eNCtDbpiBkp6KkBav7DcgEsPiEius"),
    ("WIF", "9m1Ys7ga7jchMYRGXz1u5sUvjXbS15RBX6iRsmEJrQCC"),
    ("ATH", "3wadb2fsPkDNpQazr5VFa9A2BoLcEWMrPcPHNACFBDvt"),
    ("BONK", "68FbNAyrhME3DrSRSyKjuTFdQZ5b4erzK6uJQ3RTkitn"),
    ("FARTCOIN", "GWvcdLtk2tx5pMecRV6e2fg27QGB8vqHbC1YNvtpjCdV"),
    ("JTO", "Dp9sZHXjiyTd1atN2pKswWVnP9Q9ZkP3euqvoNv2yv8f"),
    ("JUP", "G8oxFvUWzVYE3saje8Z9JuBrn1qf4puwKQkbNU6PU4su"),
    ("MEW", "34muAMwQGCzXpjPnTuQqhdLfVPraitpRyFd9ZYXJejCU"),
    ("MNDE", "GnqWo8LEiShqYeFHsA8i6n8UJMmz9hv8M19XMgj9aMkL"),
    ("ORCA", "627A7kdEbVPGq7azuk43a8ebgJ5eipwMgwTVNBX9K8aU"),
    ("PENGU", "B3R37cUYMvRd35KZrYsJxZDs6VuwAMZ7mBQgt3dHTVPt"),
    ("POPCAT", "52jh55TNJpUguy8e9kGRE5HxPXvnhDM9QjAmojmzqzXr"),
    ("PYTH", "EbT9BxSXKi6Stn8EGwq1mZZfGW3oyUY7iRcT9uVbY9g7"),
    ("RAY", "8UP4XCJePyWvYUMhRUzVj1YSmuvMgb4hAqU713FFRaGN"),
    ("RENDER", "7z7En3AsXyV9xG99KNhEKS5tTnsRM5ViCwtcjtJ8NQ9r"),
    ("SPX", "4W492CojQZzWopVjHPqSyAKW5KSbusyPnvQuNNxjvn19"),
    ("VIRTUAL", "4daWXka1pSo1xvuYMTirCp378GgxhRoqr5vFK26dB9Zw"),
    ("W", "98YY8drz4bLD2jTXcQcqJibbtBYmARuoPyAgVq61Y66E"),
    ("SOL", "9BHh6RVPCt7ijv6K5MukZjeCUBtamHQXhRUr1TeudgUL"),
    ("USDC", "8F7VKK7ZtL3moBzV4QSkzPZo2xSUx15K6wv1G1QZQDix"),
];

// Get all Pyth price feed IDs (hex strings) for modern pull oracle approach
pub fn get_all_pyth_price_feed_ids() -> Vec<(&'static str, &'static str)> {
    PYTH_PRICE_FEEDS.to_vec()
}

// Get price feed ID for a specific token symbol
pub fn get_price_feed_id_for_symbol(symbol: &str) -> Option<&'static str> {
    PYTH_PRICE_FEEDS
        .iter()
        .find(|(feed_symbol, _)| *feed_symbol == symbol)
        .map(|(_, feed_id)| *feed_id)
}

// Validate PriceUpdateV2 account and extract feed ID
pub fn validate_price_update_account(
    account_info: &AccountInfo,
    expected_feed_id: &str,
) -> Result<PriceUpdateV2> {
    let price_update = PriceUpdateV2::try_deserialize(
        &mut account_info.data.borrow().as_ref()
    ).map_err(|_| error!(crate::errors::ErrorCode::InvalidOracleAccount))?;
    
    // Validate that the price update contains the expected feed
    let expected_feed_bytes = hex_to_bytes(expected_feed_id)?;
    
    // Check if the price message feed id matches expected
    if price_update.price_message.feed_id != expected_feed_bytes {
        return Err(error!(crate::errors::ErrorCode::InvalidOracleAccount));
    }
    
    Ok(price_update)
}

// Helper function to convert hex string to bytes for feed ID comparison
fn hex_to_bytes(hex_str: &str) -> Result<[u8; 32]> {
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
    
    Ok(bytes)
}

// Token mint to symbol mapping (from TRACKED_TOKENS)
pub const TOKEN_MINT_TO_SYMBOL: &[(&str, &str)] = &[
    ("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "USDC"), // Base currency
    ("So11111111111111111111111111111111111111112", "SOL"), // Native SOL
    ("6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN", "TRUMP"),
    ("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof", "RENDER"),
    ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "JUP"),
    ("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "BONK"),
    ("9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", "FARTCOIN"),
    ("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "RAY"),
    ("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL", "JTO"),
    ("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "PYTH"),
    ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "WIF"),
    ("3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y", "VIRTUAL"),
    ("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv", "PENGU"),
    ("85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ", "W"), // WORMHOLE
    ("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "POPCAT"),
    ("Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7", "ATH"),
    ("MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5", "MEW"),
    ("MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey", "MNDE"),
    ("J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr", "SPX"), // SPX6900
    ("orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE", "ORCA"),
];

// Get price feed ID for a specific token mint
pub fn get_price_feed_id_for_token_mint(token_mint: &Pubkey) -> Option<&'static str> {
    let token_mint_str = token_mint.to_string();
    
    // Find symbol for this token mint
    let symbol = TOKEN_MINT_TO_SYMBOL
        .iter()
        .find(|(mint, _)| *mint == token_mint_str)
        .map(|(_, symbol)| *symbol)?;
    
    // Find price feed ID for this symbol
    get_price_feed_id_for_symbol(symbol)
}

// Get Switchboard oracle for a specific token symbol
pub fn get_switchboard_oracle_for_symbol(symbol: &str) -> Option<Pubkey> {
    SWITCHBOARD_FEEDS
        .iter()
        .find(|(feed_symbol, _)| *feed_symbol == symbol)
        .and_then(|(_, addr_str)| addr_str.parse().ok())
}

// Get both Pyth price feed ID and Switchboard oracle for a token symbol  
pub fn get_dual_oracle_config(symbol: &str) -> (Option<&'static str>, Option<Pubkey>) {
    let pyth_feed_id = get_price_feed_id_for_symbol(symbol);
    let switchboard_oracle = get_switchboard_oracle_for_symbol(symbol);
    
    (pyth_feed_id, switchboard_oracle)
}

// Get price feed configuration for vault - returns (feed_ids, token_feed_mapping)
// Note: For pull oracle model, oracle accounts are created dynamically, not statically stored
pub fn get_price_feed_config_for_vault() -> (Vec<&'static str>, Vec<(Pubkey, u8)>) {
    let feeds = get_all_pyth_price_feed_ids();
    let mut feed_ids = Vec::new();
    let mut token_feed_mapping = Vec::new();
    
    for (index, (_symbol, feed_id)) in feeds.iter().enumerate() {
        feed_ids.push(*feed_id);
        
        // Map each token mint to its feed index
        for (token_mint_str, symbol) in TOKEN_MINT_TO_SYMBOL.iter() {
            if *symbol == feeds[index].0 {
                if let Ok(token_mint) = token_mint_str.parse::<Pubkey>() {
                    token_feed_mapping.push((token_mint, index as u8));
                }
            }
        }
    }
    
    (feed_ids, token_feed_mapping)
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug)]
pub struct PythPriceFeedInfo {
    pub symbol: String,
    pub feed_id: String,  // Hex string used with Hermes API
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