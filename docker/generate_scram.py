#!/usr/bin/env python3
import hashlib
import base64
import hmac
import os

def generate_scram_sha256(password, salt=None, iterations=4096):
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = salt.encode()
    
    # SCRAM-SHA-256 key derivation
    def hi(password, salt, iterations):
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
        return dk
    
    salted_password = hi(password, salt, iterations)
    client_key = hmac.new(salted_password, b'Client Key', hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted_password, b'Server Key', hashlib.sha256).digest()
    
    salt_b64 = base64.b64encode(salt).decode()
    stored_key_b64 = base64.b64encode(stored_key).decode()
    server_key_b64 = base64.b64encode(server_key).decode()
    
    return f'SCRAM-SHA-256${iterations}:{salt_b64}${stored_key_b64}:{server_key_b64}'

# Generate for calvin_dev user
scram_hash = generate_scram_sha256('calvin_dev_password')
print(f'"calvin_dev" "{scram_hash}"')

# Generate for admin user  
admin_hash = generate_scram_sha256('admin_password')
print(f'"admin" "{admin_hash}"')

# Generate for stats user
stats_hash = generate_scram_sha256('stats_password')
print(f'"stats" "{stats_hash}"') 