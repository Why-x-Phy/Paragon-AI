// Import and re-export individual instruction modules
mod initialize;
mod stake;
mod deposit;
mod withdraw;
mod trade;
mod liquidate_to_cover;
mod set_pause_status;
mod update_config;

// Re-export everything from each module
pub use initialize::*;
pub use stake::*;
pub use deposit::*;
pub use withdraw::*;
pub use trade::*;
pub use liquidate_to_cover::*;
pub use set_pause_status::*;
pub use update_config::*;
