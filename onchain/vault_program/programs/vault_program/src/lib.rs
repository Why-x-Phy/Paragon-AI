use anchor_lang::prelude::*;

declare_id!("8yjiGc8pZeEfmP3nxSwuj8pke9s57Rp4Jt68wxWna8V1");

#[program]
pub mod vault_program {
    use super::*;

    pub fn initialize(ctx: Context<Initialize>) -> Result<()> {
        msg!("Greetings from: {:?}", ctx.program_id);
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Initialize {}
