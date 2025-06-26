import asyncio
import asyncpg
from src.config import get_config

async def test_connection():
    config = get_config()
    db_url = config.get('DATABASE_URL')
    print('Testing connection with URL:', db_url)
    
    try:
        conn = await asyncpg.connect(db_url)
        print('Connection successful')
        await conn.close()
    except Exception as e:
        print('Connection failed:', str(e))
        print('Exception type:', type(e).__name__)

if __name__ == "__main__":
    asyncio.run(test_connection()) 