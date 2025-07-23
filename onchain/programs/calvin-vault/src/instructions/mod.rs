// Import and re-export individual instruction modules
pub mod initialize;
pub mod deposit;
pub mod withdraw;
pub mod trade;
pub mod liquidate_to_cover;
pub mod set_pause_status;
pub mod update_config;
pub mod get_user_vault_shares;
pub mod initialize_token_accounts;
pub mod calculate_nav;
pub mod collect_performance_fees;
pub mod refresh_nav;

// 🔒 NEW SECURITY INSTRUCTION MODULES
pub mod add_whitelisted_token;
pub mod remove_whitelisted_token;
pub mod add_emergency_owner;
pub mod propose_emergency_action;
pub mod approve_emergency_action;
pub mod execute_emergency_action;
pub mod pause_trading;
pub mod pause_deposits;
pub mod pause_withdrawals;
pub mod pause_all;
pub mod admin_mint_shares;

// Re-export everything from each module
pub use initialize::*;
pub use deposit::*;
pub use withdraw::*;
pub use trade::*;
pub use liquidate_to_cover::*;
pub use set_pause_status::*;
pub use update_config::*;
pub use get_user_vault_shares::*;
pub use initialize_token_accounts::*;
pub use calculate_nav::*;
pub use collect_performance_fees::*;
pub use refresh_nav::*;

// 🔒 Re-export security instruction modules
pub use add_whitelisted_token::*;
pub use remove_whitelisted_token::*;
pub use add_emergency_owner::*;
pub use propose_emergency_action::*;
pub use approve_emergency_action::*;
pub use execute_emergency_action::*;
pub use pause_trading::*;
pub use pause_deposits::*;
pub use pause_withdrawals::*;
pub use pause_all::*;
pub use admin_mint_shares::*;
