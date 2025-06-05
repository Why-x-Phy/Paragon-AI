import sqlite3

conn = sqlite3.connect('data/tradingbot.db')
# Set row_factory to get column names
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Update Fartcoin's symbol
cursor.execute("UPDATE tokens SET symbol = ? WHERE token_id = ?", ("Fartcoin", 7))
conn.commit()
print("Updated Fartcoin's symbol from 'FART' to 'Fartcoin'")

# Get column names first
cursor.execute("PRAGMA table_info(tokens)")
columns = [column[1] for column in cursor.fetchall()]
print("Column names:", columns)

# Get and display token data
cursor.execute("SELECT * FROM tokens")
tokens = cursor.fetchall()
print("\nAll tokens in database:")
for token in tokens:
    # Convert each Row object to a dict for better readability
    token_dict = {columns[i]: token[i] for i in range(len(columns))}
    print(token_dict)

conn.close() 