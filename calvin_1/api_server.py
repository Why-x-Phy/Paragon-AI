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

from src.vault.trades_api import simple_trades_api
from src.utils.logger import log

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
    """Initialize the trades API on startup"""
    try:
        await simple_trades_api.initialize()
        logger.info("🚀 Calvin AI Trades API server started")
    except Exception as e:
        logger.error(f"❌ Failed to initialize trades API: {e}")

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

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Test database connection
        if not simple_trades_api.db_manager:
            await simple_trades_api.initialize()
        
        # Try to fetch one trade to test the full pipeline
        test_data = await simple_trades_api.get_live_trades(limit=1)
        
        return {
            "status": "healthy",
            "database": "connected",
            "trades_api": "operational",
            "sample_trades": len(test_data.get('trades', []))
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