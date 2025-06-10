// Import and re-export individual instruction modules
pub mod initialize;
pub mod stake;
pub mod unstake;
pub mod verify_tier;
pub mod pause;
pub mod update_config;

// Re-export everything from each module
pub use initialize::*;
pub use stake::*;
pub use unstake::*;
pub use verify_tier::*;
pub use pause::*;
pub use update_config::*; 