// Import and re-export individual instruction modules
mod initialize;
mod stake;
mod unstake;
mod verify_tier;
mod pause;
mod update_config;

// Re-export everything from each module
pub use initialize::*;
pub use stake::*;
pub use unstake::*;
pub use verify_tier::*;
pub use pause::*;
pub use update_config::*; 