"""
Calvin AI Trades API Server

Simple FastAPI server to serve live trades data to the frontend.
"""

import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict, Any
from fastapi import Request

from src.vault.trades_api import simple_trades_api
from src.vault.performance_api import simple_performance_api
from src.utils.logger import log
from src.config.config import config
import aiohttp
import json

logger = log

# Create FastAPI app
app = FastAPI(
    title="Calvin AI Trades API",
    description="Live trades data for Calvin AI vault system",
    version="1.0.0"
)

# Add CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://calvin-ai.vercel.app"],  # Frontend URLs
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize the APIs on startup"""
    try:
        await simple_trades_api.initialize()
        await simple_performance_api.initialize()
        logger.info("🚀 Calvin AI API server started (trades + performance)")
    except Exception as e:
        logger.error(f"❌ Failed to initialize APIs: {e}")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "Calvin AI Trades API"}

@app.get("/api/trades")
async def get_trades(limit: int = 30) -> Dict[str, Any]:
    """
    Get live trades data
    
    Args:
        limit: Maximum number of trades to return (default 30)
        
    Returns:
        Dict with trades list and statistics
    """
    try:
        # Validate limit
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
        
        # Get trades data
        data = await simple_trades_api.get_live_trades(limit=limit)
        
        logger.debug(f"✅ Served {len(data.get('trades', []))} trades to frontend")
        return data
        
    except Exception as e:
        logger.error(f"❌ Trades API error: {e}")
        
        # Return error response
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch trades: {str(e)}"
        )

@app.get("/api/performance")
async def get_performance() -> Dict[str, Any]:
    """
    Get live portfolio performance statistics
    
    Returns:
        Dict with performance metrics for different time periods
    """
    try:
        # Get performance data
        data = await simple_performance_api.get_live_performance()
        
        logger.debug(f"✅ Served performance data to frontend")
        return data
        
    except Exception as e:
        logger.error(f"❌ Performance API error: {e}")
        
        # Return error response
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch performance: {str(e)}"
        )

@app.post("/api/solana/rpc")
async def solana_rpc_proxy(request: Request):
    """
    Proxy Solana RPC requests to Helius to hide API key from frontend
    """
    try:
        # Get the request body (JSON-RPC payload)
        body = await request.json()
        
        # Get Helius RPC URL with API key from environment
        helius_api_key = config.helius_api_key
        if not helius_api_key:
            raise HTTPException(status_code=500, detail="Helius API key not configured")
        
        helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"
        
        # Forward the request to Helius
        async with aiohttp.ClientSession() as session:
            async with session.post(
                helius_rpc_url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                # Return the response from Helius
                response_data = await response.json()
                return response_data
                
    except Exception as e:
        logger.error(f"❌ RPC proxy error: {e}")
        raise HTTPException(status_code=500, detail=f"RPC proxy failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Test database connections
        if not simple_trades_api.db_manager:
            await simple_trades_api.initialize()
        if not simple_performance_api.db_manager:
            await simple_performance_api.initialize()
        
        # Try to fetch data to test the full pipeline
        test_trades = await simple_trades_api.get_live_trades(limit=1)
        test_performance = await simple_performance_api.get_live_performance()
        
        return {
            "status": "healthy",
            "database": "connected",
            "trades_api": "operational",
            "performance_api": "operational",
            "sample_trades": len(test_trades.get('trades', [])),
            "performance_timestamp": test_performance.get('timestamp', 'unknown')
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        )

if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    ) 