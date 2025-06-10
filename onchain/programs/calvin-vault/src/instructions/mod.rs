// Import and re-export individual instruction modules
pub mod initialize;
pub mod deposit;
pub mod withdraw;
pub mod trade;
pub mod liquidate_to_cover;
pub mod set_pause_status;
pub mod update_config;
pub mod get_user_vault_shares;

// Re-export everything from each module
pub use initialize::*;
pub use deposit::*;
pub use withdraw::*;
pub use trade::*;
pub use liquidate_to_cover::*;
pub use set_pause_status::*;
pub use update_config::*;
pub use get_user_vault_shares::*;
