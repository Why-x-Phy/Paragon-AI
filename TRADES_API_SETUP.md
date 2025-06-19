# Calvin AI Trades API Integration

This document explains how to set up and use the real-time trades API integration between the Calvin AI backend and the frontend.

## Overview

The trades API integration consists of:

1. **Backend Trades API** (`calvin_1/src/vault/trades_api.py`) - Queries database for live trades data
2. **FastAPI Server** (`calvin_1/api_server.py`) - Serves trades data via REST API
3. **Frontend API Route** (`frontend/app/api/trades/route.js`) - Next.js API route that calls backend
4. **Frontend Hook** (`frontend/hooks/useTrades.js`) - React hook that fetches and displays trades data
5. **Trades Table Component** (`frontend/components/TradesTable.jsx`) - UI component that displays trades

## Setup Instructions

### 1. Install Dependencies

```bash
# Backend dependencies
cd calvin_1/
pip install fastapi uvicorn[standard]

# Or install from requirements.txt (already updated)
pip install -r requirements.txt
```

### 2. Database Setup

Make sure your TimescaleDB database is running with the trades table:

```bash
# Start database (if using Docker)
cd docker/
docker-compose -f docker-compose.dev.yml up -d timescaledb redis

# The trades table should already exist from previous setup
```

### 3. Test the Integration

```bash
cd calvin_1/
python test_trades_api.py
```

This test script will:
- ✅ Test database connection
- ✅ Insert a sample trade for testing
- ✅ Test the trades API functionality
- ✅ Verify FastAPI imports

### 4. Start the Backend API Server

```bash
cd calvin_1/
python main.py run-api-server

# Or with custom options:
python main.py run-api-server --host 0.0.0.0 --port 8000 --reload
```

The API server will be available at: `http://localhost:8000`

API endpoints:
- `GET /` - Health check
- `GET /api/trades?limit=30` - Get live trades data
- `GET /health` - Detailed health check

### 5. Start the Frontend

```bash
cd frontend/
yarn dev
```

The frontend will be available at: `http://localhost:3000`

### 6. View Live Trades

Open the frontend in your browser and check the **Live Trades** table. It should now display:

- ✅ Real trades data from the database
- ✅ Live P&L calculations
- ✅ Running win rate statistics
- ✅ Auto-refresh every 30 seconds
- ✅ Error handling with fallback data

## API Data Structure

### Trades API Response

```json
{
  "trades": [
    {
      "id": 1,
      "time": "14:32:15",
      "trade": "BUY BONK",
      "amount": "$1,250",
      "pnl": 125.50,
      "pnl_formatted": "+$125.50",
      "is_profitable": true,
      "win_rate": 68.5,
      "tx_hash": "ABC123..."
    }
  ],
  "stats": {
    "total_trades": 25,
    "current_win_rate": 67.5,
    "total_pnl": 1250.75,
    "profitable_trades": 17
  }
}
```

## Configuration

### Backend Configuration

Environment variables in `.env`:
```bash
DATABASE_URL=postgresql://calvin:password@localhost:5432/calvin_db
REDIS_URL=redis://localhost:6379/0
```

### Frontend Configuration

Environment variables in `frontend/.env.local`:
```bash
CALVIN_BACKEND_URL=http://localhost:8000
```

## Troubleshooting

### Common Issues

1. **"No trades found"** - This is normal if no trades have been executed yet. The test script inserts a sample trade.

2. **"Backend API error"** - Make sure the backend API server is running on port 8000.

3. **CORS errors** - The API server includes CORS middleware for `localhost:3000` and production URLs.

4. **Database connection failed** - Ensure TimescaleDB is running and the `DATABASE_URL` is correct.

### Debug Steps

1. **Check backend API directly:**
   ```bash
   curl http://localhost:8000/api/trades
   ```

2. **Check frontend API route:**
   ```bash
   curl http://localhost:3000/api/trades
   ```

3. **Check browser console** for any JavaScript errors

4. **Check backend logs** for API server errors

## Production Deployment

For production deployment:

1. **Backend**: Deploy the FastAPI server with proper environment variables
2. **Frontend**: Update `CALVIN_BACKEND_URL` to point to production backend
3. **Database**: Ensure production database has proper trades data
4. **CORS**: Update CORS origins in `api_server.py` for production domains

## Development Workflow

1. **Add sample trades** for testing:
   ```bash
   python test_trades_api.py
   ```

2. **Start backend API** in development mode:
   ```bash
   python main.py run-api-server --reload
   ```

3. **Start frontend** in development mode:
   ```bash
   cd frontend && yarn dev
   ```

4. **View live updates** in the browser trades table

The trades table will automatically refresh every 30 seconds and display real-time trading data from the Calvin AI system. 