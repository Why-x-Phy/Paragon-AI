import argparse
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import sqlalchemy
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import sessionmaker
import os
import sys
import logging
import math
from pathlib import Path # Added for path handling

# Add project root to sys.path to allow importing src modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# Now import the db module
try:
    from src.database.db import Base, get_engine as get_sqlite_engine
except ImportError as e:
    print(f"Error importing database module: {e}")
    print("Ensure the script is run from the project root or the src directory is in PYTHONPATH.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CHUNK_SIZE = 1_000_000 # 1 million rows per chunk
# Reduce chunk size for potentially wider tables to manage memory
WIDE_TABLE_CHUNK_SIZE = 500_000

# --- Type Mapping ---
# Map SQLAlchemy types to DuckDB/Iceberg types
# This needs careful handling, especially for types like DateTime, Text etc.
SQLALCHEMY_TO_DUCKDB = {
    sqlalchemy.types.Integer: 'INTEGER',
    sqlalchemy.types.BigInteger: 'BIGINT',
    sqlalchemy.types.SmallInteger: 'SMALLINT',
    sqlalchemy.types.String: 'VARCHAR',
    sqlalchemy.types.Text: 'VARCHAR', # DuckDB VARCHAR can hold large strings
    sqlalchemy.types.Float: 'DOUBLE', # Use DOUBLE for precision
    sqlalchemy.types.Numeric: 'DECIMAL(18, 6)', # Example precision, adjust if needed
    sqlalchemy.types.DateTime: 'TIMESTAMP', # Timestamp with time zone is often better: TIMESTAMP WITH TIME ZONE
    sqlalchemy.types.Date: 'DATE',
    sqlalchemy.types.Time: 'TIME',
    sqlalchemy.types.Boolean: 'BOOLEAN',
    # Add other types as needed
}

def get_duckdb_type(sql_type, column_name=None, table_name=None):
    """Maps SQLAlchemy type to DuckDB type string."""
    # Special case handling for known problematic columns
    if column_name == 'address':
        return 'VARCHAR(100)'  # Make sure token address is a string
    if column_name == 'resolution':
        return 'VARCHAR(10)'   # Time resolution is a string like '1m', '1h', etc.
    # Handle token_id in tokens table which might be a string
    if column_name == 'token_id' and table_name == 'tokens':
        return 'VARCHAR(100)'  # Some token IDs might be addresses/strings
    # Handle timestamp-like columns in tokens that might have invalid formats
    if table_name == 'tokens' and column_name in ['created_at', 'creation_date']:
        return 'VARCHAR(100)'  # Store as strings until proper cleaning
    
    # Regular type mapping
    for sql_cls, duckdb_str in SQLALCHEMY_TO_DUCKDB.items():
        if isinstance(sql_type, sql_cls):
            # Handle specific cases like String length if necessary
            if isinstance(sql_type, sqlalchemy.types.String) and sql_type.length:
                if sql_type.length > 0:
                    return f'VARCHAR({sql_type.length})'
            # Handle decimal precision and scale
            if isinstance(sql_type, sqlalchemy.types.Numeric) and sql_type.precision:
                precision = sql_type.precision or 18
                scale = sql_type.scale or 6
                return f'DECIMAL({precision}, {scale})'
            return duckdb_str
    # Fallback or error for unmapped types
    logging.warning(f"Unmapped SQLAlchemy type: {type(sql_type)}. Falling back to VARCHAR.")
    return 'VARCHAR'

def get_partition_spec(table_name, columns):
    """Determine a reasonable partition spec based on table name and columns."""
    col_names = {c.name for c in columns}

    # Time-series tables
    if 'timestamp' in col_names:
        if table_name in ['ohlcv', 'social_metrics', 'trade_records', 'model_predictions', 'model_evaluations']:
             # Ensure timestamp is a compatible type for partitioning
            ts_col = next((c for c in columns if c.name == 'timestamp'), None)
            if ts_col is not None and isinstance(ts_col.type, (sqlalchemy.types.DateTime, sqlalchemy.types.Date)):
                 logging.info(f"Partitioning {table_name} by date_trunc")
                 # Use date_trunc with double quotes for SQL literals
                 return ['date_trunc("day", timestamp)']
            else:
                 logging.warning(f"'timestamp' column in {table_name} is not DateTime/Date. Cannot partition by day.")


    # Tables with symbol or token_id
    symbol_col = next((c for c in columns if c.name == 'symbol'), None)
    token_id_col = next((c for c in columns if c.name == 'token_id'), None)

    # Prefer partitioning by symbol if available and it's a String type
    if symbol_col is not None and isinstance(symbol_col.type, (sqlalchemy.types.String, sqlalchemy.types.Text)):
        logging.info(f"Partitioning {table_name} by bucket(symbol, 16)")
        return ["bucket(symbol, 16)"]
    # Otherwise, use token_id if available and it's an Integer type
    elif token_id_col is not None and isinstance(token_id_col.type, sqlalchemy.types.Integer):
         logging.info(f"Partitioning {table_name} by bucket(token_id, 16)")
         return ["bucket(token_id, 16)"]

    # Default partitioning for tables like 'tokens' or 'features' if no better spec found
    if 'token_id' in col_names and table_name == 'tokens':
        logging.info(f"Partitioning {table_name} by bucket(token_id, 16)")
        return ["bucket(token_id, 16)"] # Or maybe bucket(category, 4)?
    if 'ohlcv_id' in col_names and table_name == 'features':
        logging.info(f"Partitioning {table_name} by bucket(ohlcv_id, 64)") # Features might be numerous
        return ["bucket(ohlcv_id, 64)"]

    logging.warning(f"Could not determine a specific partition strategy for {table_name}. Using no partitioning.")
    return []


def bootstrap_lake(warehouse_path):
    """Migrates tables from SQLite to an Iceberg catalog using DuckDB."""
    logging.info(f"Starting data lake bootstrap process.")
    logging.info(f"Target Iceberg warehouse path: {warehouse_path}")

    # --- Ensure warehouse directory exists ---
    os.makedirs(warehouse_path, exist_ok=True)
    logging.info(f"Ensured warehouse directory exists: {warehouse_path}")

    # --- Connect to DuckDB ---
    # Use an in-memory DuckDB instance or a file-based one if needed
    # Connecting to a file allows resuming/debugging more easily
    duckdb_file = os.path.join(warehouse_path, 'migration.duckdb')
    con = duckdb.connect(database=duckdb_file, read_only=False)
    logging.info(f"Connected to DuckDB: {duckdb_file}")

    # --- Configure DuckDB for Iceberg ---
    try:
        # Load bundled extensions (INSTALL is not needed for duckdb>=0.10.1)
        # con.sql("INSTALL iceberg;") # Removed - bundled extension
        con.sql("LOAD iceberg;")
        # Optional: Load other potentially needed extensions if not automatically loaded
        # con.sql("LOAD httpfs;")
        # con.sql("LOAD parquet;")

        # Configure the catalog (use filesystem type)
        abs_warehouse_path = os.path.abspath(warehouse_path)
        formatted_warehouse_path = abs_warehouse_path.replace('\\', '/')

        # Use ATTACH for filesystem-based Iceberg catalog
        # Detach if it exists first to ensure clean state
        try:
            con.sql("DETACH lake;")
            logging.info("Detached existing 'lake' catalog if it existed.")
        except duckdb.Error:
            pass # Ignore if it doesn't exist

        # Convert path to absolute and use proper format
        warehouse_abs_path = Path(warehouse_path).resolve()
        posix_path = warehouse_abs_path.as_posix()
        
        # Load the extensions we need
        try:
            # First try to install extensions if they're not already present
            try:
                con.sql("INSTALL httpfs;")
                logging.info("Installed httpfs extension")
            except duckdb.Error as e:
                logging.warning(f"Could not install httpfs: {e}")
                # May already be installed
            
            try:
                con.sql("LOAD httpfs;")
                logging.info("Loaded httpfs extension")
            except duckdb.Error as e:
                logging.warning(f"Could not load httpfs extension: {e}")
                # Continue anyway as it might only be needed for S3
            
            try:
                con.sql("INSTALL parquet;")
                logging.info("Installed parquet extension")
            except duckdb.Error as e:
                logging.warning(f"Could not install parquet: {e}")
                # May already be installed
                
            try:
                con.sql("LOAD parquet;")
                logging.info("Loaded parquet extension")
            except duckdb.Error as e:
                logging.warning(f"Could not load parquet extension: {e}")
                # This is more critical but may be bundled in new versions
            
            logging.info("Attempted to load all required extensions")
        except Exception as e:
            logging.warning(f"Problem with extensions: {e}")
            # Continue anyway

        # Create a schema to use without Iceberg initially
        try:
            con.sql("CREATE SCHEMA IF NOT EXISTS lake;")
            con.sql("USE lake;")
            logging.info("Created and switched to 'lake' schema")
            
            # Configure DuckDB to create Iceberg tables through direct SQL
            # instead of using ATTACH with an Iceberg catalog
            # We'll create the tables directly in the target location
            # This bypasses the need for a formal Iceberg catalog
            
            # Set up DuckDB for the task
            con.sql("SET memory_limit='8GB';")
            logging.info("Successfully configured DuckDB for working with Iceberg tables directly")
            logging.info(f"Will create Iceberg tables directly in {posix_path}")
            
        except duckdb.Error as e:
            logging.error(f"Failed to configure DuckDB: {e}")
            con.close()
            return

        # Set memory limit
        con.sql("SET memory_limit='8GB';")
        logging.info(f"DuckDB Iceberg extension loaded and catalog 'lake' configured at {formatted_warehouse_path}")
    except Exception as e:
        logging.error(f"Failed to install or configure DuckDB Iceberg extension: {e}")
        con.close()
        return

    # --- SQLite Connection ---
    sqlite_engine = get_sqlite_engine() # Assumes env var DB_USE_SQLITE='true' or default path
    SqliteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SqliteSession()
    logging.info("Connected to SQLite database.")

    # --- Discover SQLAlchemy Models ---
    mapper_registry = Base.metadata
    tables = mapper_registry.tables # Dictionary of table_name: Table object

    logging.info(f"Discovered {len(tables)} tables in SQLAlchemy metadata: {list(tables.keys())}")

    # --- Process Each Table ---
    for table_name, table_obj in tables.items():
        logging.info(f"Processing table: {table_name}")

        # Get the corresponding SQLAlchemy model class
        try:
            model_class = next(cls for cls in Base.__subclasses__() if cls.__tablename__ == table_name)
            mapper = inspect(model_class)
        except (StopIteration, Exception) as e:
             logging.error(f"Could not find SQLAlchemy model class for table {table_name}: {e}")
             continue


        # --- Define Iceberg Schema and Partitioning ---
        columns_sql = []
        sqlalchemy_cols = list(mapper.columns) # Use inspected columns
        for col in sqlalchemy_cols:
            duckdb_type = get_duckdb_type(col.type, col.name, table_name)
            # Handle nullable constraints if necessary (Iceberg supports NULL by default)
            # duckdb_type += " NOT NULL" if not col.nullable else ""
            columns_sql.append(f"\"{col.name}\" {duckdb_type}") # Quote column names

        schema_sql = ", ".join(columns_sql)
        partition_spec = get_partition_spec(table_name, sqlalchemy_cols)
        partition_sql = f"PARTITIONED BY ({', '.join(partition_spec)})" if partition_spec else ""

        # --- Create Temporary Directory for Parquet Chunks ---
        temp_parquet_dir = os.path.join(warehouse_path, 'temp_parquet', table_name)
        os.makedirs(temp_parquet_dir, exist_ok=True)

        # --- Stream Data from SQLite and Write to Parquet ---
        total_rows = 0
        chunk_num = 0
        parquet_files = []
        
        # Adjust chunk size for potentially wide tables
        current_chunk_size = WIDE_TABLE_CHUNK_SIZE if table_name in ['features', 'social_metrics'] else CHUNK_SIZE
        
        try:
            # Stream results from SQLite with yield_per
            query = sqlite_session.query(model_class)
            stream = query.yield_per(current_chunk_size)
            
            # Process in batches
            batch = []
            for row in stream:
                batch.append(row)
                
                # When we reach the chunk size, process it
                if len(batch) >= current_chunk_size:
                    # Process this batch
                    chunk_num += 1
                    rows_in_batch = len(batch)
                    total_rows += rows_in_batch
                    
                    logging.info(f"Processing batch {chunk_num} ({rows_in_batch} rows) for table {table_name}...")
                    
                    try:
                        # Convert SQLAlchemy objects to dictionaries
                        data_dict = [r.__dict__ for r in batch]
                        
                        # Remove SQLAlchemy internal state
                        for row_dict in data_dict:
                            row_dict.pop('_sa_instance_state', None)
                            
                        # Create PyArrow table
                        arrow_table = pa.Table.from_pylist(data_dict)
                        
                        # Write batch to Parquet file
                        parquet_file = os.path.join(temp_parquet_dir, f'chunk_{chunk_num}.parquet')
                        pq.write_table(arrow_table, parquet_file, compression='ZSTD')
                        parquet_files.append(parquet_file.replace('\\', '/'))  # Forward slashes for DuckDB
                        
                        logging.info(f"Written batch {chunk_num} to {parquet_file}")
                    except Exception as e:
                        logging.error(f"Error processing batch {chunk_num} for {table_name}: {e}")
                    
                    # Reset batch for next round
                    batch = []
            
            # Process any remaining rows in the final batch
            if batch:
                chunk_num += 1
                rows_in_batch = len(batch)
                total_rows += rows_in_batch
                
                logging.info(f"Processing final batch {chunk_num} ({rows_in_batch} rows) for table {table_name}...")
                
                try:
                    # Convert SQLAlchemy objects to dictionaries
                    data_dict = [r.__dict__ for r in batch]
                    
                    # Remove SQLAlchemy internal state
                    for row_dict in data_dict:
                        row_dict.pop('_sa_instance_state', None)
                        
                    # Create PyArrow table
                    arrow_table = pa.Table.from_pylist(data_dict)
                    
                    # Write batch to Parquet file
                    parquet_file = os.path.join(temp_parquet_dir, f'chunk_{chunk_num}.parquet')
                    pq.write_table(arrow_table, parquet_file, compression='ZSTD')
                    parquet_files.append(parquet_file.replace('\\', '/'))  # Forward slashes for DuckDB
                    
                    logging.info(f"Written final batch {chunk_num} to {parquet_file}")
                except Exception as e:
                    logging.error(f"Error processing final batch {chunk_num} for {table_name}: {e}")
            
            logging.info(f"Finished reading {total_rows} rows for {table_name} into {len(parquet_files)} Parquet files.")
            
            if not parquet_files:
                logging.warning(f"No data found or processed for table {table_name}. Skipping Iceberg table creation.")
                continue  # Skip to next table if no data
                
        except Exception as e:
            logging.error(f"An error occurred processing table {table_name}: {e}", exc_info=True)
            continue  # Skip to next table
            
        finally:
            # Clean up temp dir more reliably (if needed)
            if os.path.exists(temp_parquet_dir):
                try:
                    # DuckDB might still hold locks, sometimes requires closing the connection first
                    # For simplicity, we'll leave the cleanup manual or improve later
                    logging.info(f"Temporary directory {temp_parquet_dir} was not removed.")
                except Exception as e:
                    logging.warning(f"Error during cleanup of {temp_parquet_dir}: {e}")
        
        # --- Create or Replace Iceberg Table and Load Data ---
        iceberg_table_name = f"lake.\"{table_name}\"" 
        temp_parquet_path_pattern = os.path.join(temp_parquet_dir, '*.parquet').replace('\\', '/')

        # Drop if exists to start clean
        con.sql(f"DROP TABLE IF EXISTS {iceberg_table_name};")
        logging.info(f"Dropped existing table {iceberg_table_name} if it existed.")

        # Create table with Iceberg format and explicit location in warehouse
        table_location = f"{posix_path}/{table_name}"
        os.makedirs(table_location, exist_ok=True)
        
        # Add partitioning inside the WITH clause if needed
        partition_prop = ""
        if partition_spec:
            partition_columns = ', '.join(partition_spec)
            partition_prop = f",\n            partitioning = '{partition_columns}'"
        
        create_sql = f"""
        CREATE TABLE {iceberg_table_name} (
            {schema_sql}
        )
        WITH (
            format = 'parquet',
            type = 'ICEBERG',
            location = '{table_location}'{partition_prop}
        );
        """
        logging.info(f"Executing CREATE TABLE SQL for {table_name}:\n{create_sql}")
        try:
            con.sql(create_sql)
            logging.info(f"Successfully created Iceberg table structure for {table_name}.")

            # Insert data from Parquet
            # Need to list files explicitly if CREATE TABLE AS SELECT * FROM read_parquet(...) is not used or buggy
            # Build a list of files for the read_parquet function
            files_list_str = ', '.join([f"'{f}'" for f in parquet_files])
            insert_sql = f"INSERT INTO {iceberg_table_name} SELECT * FROM read_parquet([{files_list_str}]);"

            logging.info(f"Executing INSERT INTO SQL for {table_name} from Parquet files.")
            try:
                con.sql(insert_sql)
                logging.info(f"Successfully loaded data into Iceberg table {iceberg_table_name}.")
            except duckdb.Error as e:
                logging.error(f"Failed to load data into Iceberg table {iceberg_table_name}: {e}")
                
                # More specific diagnostics for common issues
                if "Conversion Error" in str(e):
                    logging.error("Data type conversion error detected. This can happen if:")
                    logging.error("1. SQLite and DuckDB have different type interpretations")
                    logging.error("2. Data contains values that don't match the column type")
                    logging.error("Trying to inspect the Parquet data schema...")
                    
                    try:
                        # Try to read the first Parquet file to see its schema
                        if parquet_files:
                            parquet_info = con.sql(f"DESCRIBE SELECT * FROM read_parquet('{parquet_files[0]}')").df()
                            logging.info(f"Parquet schema from first file:\n{parquet_info}")
                            
                            # We could try to create a more dynamic SQL INSERT with explicit CAST operations
                            # But for now, let's continue to the next table
                    except Exception as inspect_err:
                        logging.error(f"Could not inspect Parquet schema: {inspect_err}")
                        
                continue  # Move to the next table

        except Exception as e:
             logging.error(f"Failed to create or load Iceberg table {iceberg_table_name}: {e}")
             # Optionally, attempt cleanup or provide more diagnostics
             continue # Move to the next table


        # --- Print Snapshot History ---
        try:
            history_sql = f"CALL system.snapshot_history('{table_name}');"
            logging.info(f"Fetching snapshot history for {table_name}:")
            snapshot_history = con.sql(history_sql).df()
            print(f"\n--- Snapshot History for {table_name} ---")
            print(snapshot_history.to_string())
            print("----------------------------------------\n")
        except Exception as e:
            logging.warning(f"Could not fetch snapshot history for {table_name}: {e}")

        # --- Clean up temporary Parquet files ---
        for f in parquet_files:
            try:
                os.remove(f)
            except OSError as e:
                logging.warning(f"Could not remove temporary file {f}: {e}")
        try:
            os.rmdir(temp_parquet_dir)
            # Try removing the parent 'temp_parquet' if it's empty
            try:
                 os.rmdir(os.path.dirname(temp_parquet_dir))
            except OSError:
                 pass # Ignore if not empty
        except OSError as e:
            logging.warning(f"Could not remove temporary directory {temp_parquet_dir}: {e}")
            logging.info(f"Cleaned up temporary Parquet files for {table_name}.")
        # Let's keep the parquet files for now for inspection, remove manually if needed.

    # --- Cleanup ---
    logging.info("Closing database connections.")
    sqlite_session.close()
    con.close() # Close DuckDB connection

    logging.info("Data lake bootstrap process completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap Iceberg data lake from SQLite DB.")
    parser.add_argument(
        "--warehouse",
        default="./lake/warehouse",
        help="Path to the Iceberg warehouse directory (default: ./lake/warehouse)"
    )
    # Add argument for SQLite DB path if needed, otherwise relies on get_sqlite_engine() logic
    parser.add_argument(
        "--sqlite-db",
        default=None, # Let get_sqlite_engine handle the default
        help="Path to the source SQLite database file (overrides environment/default behavior)."
    )

    args = parser.parse_args()

    # --- Update SQLite path if provided ---
    # This part needs adjustment based on how get_sqlite_engine is implemented
    # Currently, get_sqlite_engine uses env vars or a hardcoded path in 'data/'
    # We might need to modify get_sqlite_engine or pass the path differently.
    # For now, assuming get_sqlite_engine finds the DB at 'data/tradingbot.db' if DB_USE_SQLITE is set.
    # A cleaner way would be to pass the path directly to the engine creation.
    # Let's assume the default 'data/tradingbot.db' relative to project root is used.
    default_sqlite_path = os.path.join(project_root, 'data', 'tradingbot.db')
    if not os.path.exists(default_sqlite_path):
         # Check the path relative to the script location's parent if not found at root/data
         alt_sqlite_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'database', 'tradingbot.db'))
         if os.path.exists(alt_sqlite_path):
             logging.warning(f"Default SQLite DB not found at {default_sqlite_path}. Found at {alt_sqlite_path}. Adjust DB_USE_SQLITE or use --sqlite-db.")
             # Ideally, modify get_engine in db.py to accept a path argument.
         else:
             logging.error(f"SQLite database not found at default location: {default_sqlite_path} or {alt_sqlite_path}")
             logging.error("Please ensure 'data/tradingbot.db' exists relative to the project root, or specify the path using --sqlite-db (requires modifying script).")
             # sys.exit(1) # Exit if DB not found - maybe allow running anyway?

    # Check if running in WSL environment for path handling
    is_wsl = 'WSL_DISTRO_NAME' in os.environ or 'WSL_INTEROP' in os.environ
    if is_wsl:
        logging.info("Running in WSL environment detected.")
        # Convert warehouse path if needed, though absolute paths usually work
        warehouse_path = args.warehouse # Use as is, assuming it's a Linux-style path
    else:
         # If running on Windows directly, adjust paths if necessary
         # warehouse_path = args.warehouse.replace('/', '\\') # Example
         warehouse_path = args.warehouse # Assume user provides correct path format


    bootstrap_lake(warehouse_path) 