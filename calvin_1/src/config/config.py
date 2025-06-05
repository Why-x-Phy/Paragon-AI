import os
import yaml
from dotenv import load_dotenv
from pathlib import Path

class Config:
    def __init__(self, config_path=None, env_path=None):
        # Find the .env file, first checking the provided path, then in project root
        if env_path:
            load_dotenv(env_path)
        else:
            # Get the absolute path to this file
            current_file = Path(__file__).resolve()
            # Navigate up to find the project root (2 levels up from src/config)
            project_root = current_file.parent.parent.parent.parent
            # Check if .env exists in the project root
            root_env_path = project_root / '.env'
            
            if root_env_path.exists():
                load_dotenv(root_env_path)
            else:
                # Fallback to the current directory (calvin_1 directory)
                calvin1_env_path = current_file.parent.parent.parent / '.env'
                if calvin1_env_path.exists():
                    load_dotenv(calvin1_env_path)
                else:
                    # Last resort, try default behavior
                    load_dotenv()
            
        # API Keys
        self.birdeye_api_key = os.getenv("BIRDEYE_API_KEY_1")  # Use BIRDEYE_API_KEY_1 as the default
        self.helius_api_key = os.getenv("HELIUS_API_KEY")
        self.lunarcrush_api_key = os.getenv("LUNARCRUSH_API_KEY")
        
        # Collect all BirdEye API keys
        self.birdeye_api_keys = []
        for i in range(1, 8):  # Check for BIRDEYE_API_KEY_1 through BIRDEYE_API_KEY_7
            key = os.getenv(f"BIRDEYE_API_KEY_{i}")
            if key:
                self.birdeye_api_keys.append(key)
        
        # Wallet settings
        self.wallet_private_key = os.getenv("WALLET_PRIVATE_KEY")
        self.wallet_public_key = os.getenv("WALLET_PUBLIC_KEY")
        
        # Solana network
        self.solana_network = os.getenv("SOLANA_NETWORK", "mainnet-beta")
        
        # Trading settings
        self.trading_amount_sol = float(os.getenv("TRADING_AMOUNT_SOL", 0.1))
        self.max_trade_amount_usd = float(os.getenv("MAX_TRADE_AMOUNT_USD", 100))
        self.stop_loss_percentage = float(os.getenv("STOP_LOSS_PERCENTAGE", 5))
        self.take_profit_percentage = float(os.getenv("TAKE_PROFIT_PERCENTAGE", 10))
        self.trading_interval_minutes = int(os.getenv("TRADING_INTERVAL_MINUTES", 15))
        
        # ML model settings
        self.model_type = os.getenv("MODEL_TYPE", "lstm")
        self.prediction_horizon = int(os.getenv("PREDICTION_HORIZON", 24))
        self.training_interval_hours = int(os.getenv("TRAINING_INTERVAL_HOURS", 24))
        self.retraining_threshold = float(os.getenv("RETRAINING_THRESHOLD", 0.05))
        
        # Model paths and registry
        self.MODEL_BASE_PATH = os.getenv("MODEL_BASE_PATH", "./models")
        self.MODEL_REGISTRY_PATH = os.getenv("MODEL_REGISTRY_PATH", f"{self.MODEL_BASE_PATH}/registry")
        
        # Redis configuration
        self.REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
        self.REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
        self.REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
        self.REDIS_DB = int(os.getenv("REDIS_DB", 0))
        
        # Logging
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # Load additional config from YAML if provided
        if config_path and os.path.exists(config_path):
            self._load_yaml_config(config_path)
    
    def _load_yaml_config(self, config_path):
        """Load configuration from a YAML file"""
        with open(config_path, 'r') as f:
            yaml_config = yaml.safe_load(f)
            
        # Update config with YAML values
        for key, value in yaml_config.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def get_rpc_url(self):
        """Get the Solana RPC URL based on the network"""
        if self.solana_network == "mainnet-beta":
            return f"https://api.mainnet-beta.solana.com"
        elif self.solana_network == "testnet":
            return f"https://api.testnet.solana.com"
        elif self.solana_network == "devnet":
            return f"https://api.devnet.solana.com"
        else:
            raise ValueError(f"Unknown Solana network: {self.solana_network}")
    
    def validate(self):
        """Validate that all required configuration is present"""
        required_fields = [
            'birdeye_api_key', 
            'helius_api_key',
            'wallet_private_key',
            'wallet_public_key'
        ]
        
        missing_fields = []
        for field in required_fields:
            if not getattr(self, field):
                missing_fields.append(field)
        
        if missing_fields:
            raise ValueError(f"Missing required configuration: {', '.join(missing_fields)}")
        
        return True

# Global config instance
config = Config()
