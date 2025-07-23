#!/usr/bin/env python3
"""
Toggle Adaptive Strategy Script

This script allows you to easily enable or disable the adaptive strategy
by setting the appropriate environment variable.

When disabled, the system will use these default threshold values:
- Normal volatility: 1.0% buy, 1.5% sell
- High volatility: 2.0% buy, 3.0% sell  
- Low volatility: 0.75% buy, 1.15% sell
"""

import os
import argparse
import sys
from pathlib import Path

def set_env_variable(name: str, value: str, env_file: str = ".env"):
    """Set or update an environment variable in .env file"""
    env_path = Path(env_file)
    
    # Read existing content
    if env_path.exists():
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []
    
    # Update or add the variable
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[i] = f"{name}={value}\n"
            updated = True
            break
    
    if not updated:
        lines.append(f"{name}={value}\n")
    
    # Write back to file
    with open(env_path, 'w') as f:
        f.writelines(lines)
    
    print(f"✅ Set {name}={value} in {env_file}")

def main():
    parser = argparse.ArgumentParser(description="Toggle Calvin AI adaptive strategy on/off")
    parser.add_argument(
        "action", 
        choices=["enable", "disable", "status"],
        help="Action to perform: enable, disable, or check status"
    )
    parser.add_argument(
        "--env-file", 
        default=".env",
        help="Path to .env file (default: .env)"
    )
    
    args = parser.parse_args()
    
    if args.action == "enable":
        set_env_variable("ENABLE_ADAPTATION", "true", args.env_file)
        print("🚀 Adaptive strategy ENABLED")
        print("   - Thresholds will adjust based on market conditions and performance")
        print("   - System will adapt buy/sell thresholds dynamically")
        
    elif args.action == "disable":
        set_env_variable("ENABLE_ADAPTATION", "false", args.env_file)
        print("⏸️  Adaptive strategy DISABLED")
        print("   - Using fixed default thresholds:")
        print("   - Normal volatility: 1.0% buy, 1.5% sell")
        print("   - High volatility: 2.0% buy, 3.0% sell")
        print("   - Low volatility: 0.75% buy, 1.15% sell")
        
    elif args.action == "status":
        # Check current setting
        env_path = Path(args.env_file)
        current_value = "true"  # default
        
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith("ENABLE_ADAPTATION="):
                        current_value = line.split("=", 1)[1].strip()
                        break
        
        # Also check actual environment variable
        env_value = os.getenv("ENABLE_ADAPTATION", "true")
        
        print(f"📊 Adaptive Strategy Status:")
        print(f"   - .env file: {current_value}")
        print(f"   - Environment: {env_value}")
        print(f"   - Effective: {'ENABLED' if env_value.lower() == 'true' else 'DISABLED'}")
        
        if env_value.lower() == "true":
            print("   - Thresholds adapt to market conditions")
        else:
            print("   - Using fixed default thresholds")
    
    print("\n💡 Remember to restart the Calvin AI system for changes to take effect!")

if __name__ == "__main__":
    main() 