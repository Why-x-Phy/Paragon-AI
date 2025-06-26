"""
Jupiter V6 Client - Node.js Bridge Approach

Uses Jupiter's TypeScript SDK via Node.js to generate properly serialized swap instructions
that our Python code can consume. This eliminates complex HTTP API calls and manual serialization.
"""

import asyncio
import json
import subprocess
import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..config.config import config
from ..utils.logger import log

logger = log

class JupiterV6Client:
    """
    Jupiter V6 client using Node.js bridge for proper instruction generation
    """
    
    def __init__(self):
        # Path to our Node.js Jupiter instruction generator
        self.script_path = os.path.join(os.path.dirname(__file__), "../../jupiter_instruction_generator.js")
        
        # Performance tracking
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0
        
        # Configuration
        self.timeout = config.get('JUPITER_TIMEOUT_SECONDS', 30)
        self.max_retries = config.get('JUPITER_MAX_RETRIES', 3)
        
        logger.info("Jupiter V6 Client initialized with Node.js bridge")

    async def initialize(self):
        """Initialize the Jupiter client and verify Node.js dependencies"""
        try:
            # Check if Node.js is available
            result = await asyncio.create_subprocess_exec(
                'node', '--version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                raise Exception("Node.js not found - required for Jupiter bridge")
            
            node_version = stdout.decode().strip()
            logger.info(f"✅ Node.js available: {node_version}")
            
            # Check if our Jupiter script exists
            if not os.path.exists(self.script_path):
                raise Exception(f"Jupiter script not found: {self.script_path}")
            
            # Check if dependencies are installed
            package_json_path = os.path.join(os.path.dirname(self.script_path), "package.json")
            if os.path.exists(package_json_path):
                # Try to run the script with help flag to verify it works
                result = await asyncio.create_subprocess_exec(
                    'node', self.script_path, '--help',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.dirname(self.script_path)
                )
                stdout, stderr = await result.communicate()
                
                if result.returncode != 0 and "Cannot find module" in stderr.decode():
                    logger.warning("⚠️ Jupiter dependencies not installed, installing...")
                    await self._install_dependencies()
            
            logger.info("Jupiter V6 Client initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Jupiter Client initialization failed: {e}")
            raise

    async def _install_dependencies(self):
        """Install Node.js dependencies for Jupiter bridge"""
        try:
            logger.info("📦 Installing Jupiter SDK dependencies...")
            
            result = await asyncio.create_subprocess_exec(
                'npm', 'install',
                cwd=os.path.dirname(self.script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                logger.info("✅ Dependencies installed successfully")
            else:
                error_msg = stderr.decode()
                logger.error(f"❌ Failed to install dependencies: {error_msg}")
                raise Exception(f"npm install failed: {error_msg}")
                
        except Exception as e:
            logger.error(f"❌ Dependency installation failed: {e}")
            raise

    async def get_quote(self, input_mint: str, output_mint: str, amount: int, 
                       slippage_bps: int = 100, payer_pubkey: str = None) -> Optional[Dict]:
        """
        Get Jupiter quote using Node.js bridge
        
        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Amount in smallest token units
            slippage_bps: Slippage tolerance in basis points
            payer_pubkey: Public key of the payer (optional for quotes)
            
        Returns:
            Quote dictionary or None if failed
        """
        try:
            logger.debug(f"🔄 Getting Jupiter quote: {input_mint[:8]}...→{output_mint[:8]}... (amount: {amount})")
            
            # Use actual payer - required for production
            if not payer_pubkey:
                logger.error("❌ payer_pubkey is required for Jupiter quotes")
                return None
            user_pubkey = payer_pubkey
        
            start_time = time.time()
        
            # Call Node.js script to get quote
            result = await asyncio.create_subprocess_exec(
                'node', self.script_path,
                input_mint, output_mint, str(amount), user_pubkey, str(slippage_bps),
                '--quote-only',  # Flag to only get quote, not full instruction
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(self.script_path)
            )
            
            stdout, stderr = await asyncio.wait_for(
                result.communicate(), 
                timeout=self.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            self.total_response_time += response_time
            self.request_count += 1
            
            if result.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"❌ Jupiter quote failed: {error_msg}")
                self.error_count += 1
                return None
        
            # Parse the JSON response
            response_text = stdout.decode().strip()
            quote_data = json.loads(response_text)
            
            logger.debug(f"✅ Jupiter quote successful in {response_time:.1f}ms")
            return quote_data
            
        except asyncio.TimeoutError:
            logger.error(f"⏰ Jupiter quote timeout after {self.timeout}s")
            self.error_count += 1
            return None
        except Exception as e:
            logger.error(f"❌ Jupiter quote error: {e}")
            self.error_count += 1
            return None

    async def get_swap_transaction(self, quote_response, payer_pubkey, slippage_bps=100):
        """
        Get swap instruction using Node.js bridge - this is the key improvement!
        
        Args:
            quote_response: Quote from get_quote() or direct quote data
            payer_pubkey: Public key of the payer (vault authority)
            slippage_bps: Slippage tolerance in basis points
            
        Returns:
            Dictionary with properly serialized Jupiter instruction data
        """
        try:
            logger.debug(f"🔨 Generating Jupiter swap instruction for payer: {payer_pubkey}")
            
            start_time = time.time()
            
            # Extract trade parameters from quote if needed
            if isinstance(quote_response, dict):
                input_mint = quote_response.get('inputMint')
                output_mint = quote_response.get('outputMint') 
                amount = quote_response.get('inAmount')
            else:
                # If quote_response is not a dict, we need the parameters passed separately
                # This is a fallback - ideally we'd always have the quote dict
                raise ValueError("Quote response must be a dictionary with trade parameters")
            
            if not all([input_mint, output_mint, amount]):
                raise ValueError("Missing required trade parameters in quote response")
            
            # Call Node.js script to generate full swap instruction
            result = await asyncio.create_subprocess_exec(
                'node', self.script_path,
                input_mint, output_mint, str(amount), str(payer_pubkey), str(slippage_bps),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(self.script_path)
            )
            
            stdout, stderr = await asyncio.wait_for(
                result.communicate(),
                timeout=self.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            self.total_response_time += response_time
            
            if result.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"❌ Jupiter swap instruction generation failed: {error_msg}")
                return None
            
            # Parse the JSON response containing the serialized instruction
            response_text = stdout.decode().strip()
            instruction_data = json.loads(response_text)
            
            # Validate the instruction structure
            required_fields = ['programId', 'data', 'accounts']
            if not all(field in instruction_data for field in required_fields):
                logger.error(f"❌ Invalid instruction structure: missing fields")
                return None
            
            # Ensure we have the correct Jupiter program ID
            if instruction_data['programId'] != 'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4':
                logger.error(f"❌ Unexpected program ID: {instruction_data['programId']}")
                return None
            
            logger.debug(f"✅ Jupiter instruction generated successfully in {response_time:.1f}ms")
            logger.debug(f"  - Program ID: {instruction_data['programId']}")
            logger.debug(f"  - Accounts: {len(instruction_data['accounts'])}")
            logger.debug(f"  - Data size: {len(instruction_data['data'])} chars (base64)")
            
            return {
                'program_id': instruction_data['programId'],
                'accounts': instruction_data['accounts'],
                'data': instruction_data['data'],  # Base64 encoded - using 'data' key that vault client expects
                'sdk_generated': True,
                'generation_time_ms': response_time
            }
            
        except asyncio.TimeoutError:
            logger.error(f"⏰ Jupiter instruction generation timeout after {self.timeout}s")
            return None
        except Exception as e:
            logger.error(f"❌ Jupiter instruction generation error: {e}")
            return None

    async def close(self):
        """Close the client (no persistent connections to close)"""
        logger.info("Jupiter V6 Client closed")

    def get_stats(self) -> Dict[str, Any]:
        """Get client performance statistics"""
        avg_response_time = (
            self.total_response_time / self.request_count 
            if self.request_count > 0 else 0
        )
        
        success_rate = (
            (self.request_count - self.error_count) / self.request_count 
            if self.request_count > 0 else 0
        )
        
        return {
            'total_requests': self.request_count,
            'total_errors': self.error_count,
            'success_rate': success_rate,
            'avg_response_time_ms': avg_response_time,
            'bridge_type': 'nodejs',
            'script_path': self.script_path
        }

    async def health_check(self) -> bool:
        """Health check - verify Node.js bridge is working"""
        try:
            # Test with a simple quote
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            sol_mint = "So11111111111111111111111111111111111111112"
            test_amount = 1000000  # $1 USDC
            
            quote = await self.get_quote(usdc_mint, sol_mint, test_amount, 100)
            
            if quote:
                logger.debug("✅ Jupiter health check passed")
                return True
            else:
                logger.warning("⚠️ Jupiter health check failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Jupiter health check error: {e}")
            return False