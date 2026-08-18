#!/usr/bin/env python3
"""Test script for DevDrop multi-file upload functionality."""
import urllib.request
import urllib.error
import json
from pathlib import Path

# Create test files
test_dir = Path("c:/temp_test_files")
test_dir.mkdir(exist_ok=True)

# Create test files
for i in range(1, 4):
    (test_dir / f"test{i}.txt").write_text(f"Test file {i} content")

# Test single file upload
print("=" * 60)
print("TEST 1: Single file upload")
print("=" * 60)

test_file = test_dir / "test1.txt"
with open(test_file, "rb") as f:
    data = f.read()

boundary = "----WebKitFormBoundary"
body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="files"; filename="test1.txt"\r\n'
    f"Content-Type: text/plain\r\n"
    f"\r\n"
).encode() + data + f"\r\n--{boundary}--\r\n".encode()

url = "http://192.168.0.107:8765/api/upload"
req = urllib.request.Request(url, data=body)
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

try:
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
        print(f"✓ Success: {result}")
except urllib.error.URLError as e:
    print(f"✗ Error: {e}")

# Test multiple file upload
print("\n" + "=" * 60)
print("TEST 2: Multiple files upload")
print("=" * 60)

boundary = "----WebKitFormBoundary"
body_parts = [f"--{boundary}\r\n"]

for i in range(1, 4):
    test_file = test_dir / f"test{i}.txt"
    with open(test_file, "rb") as f:
        file_data = f.read()
    
    body_parts.append(
        f'Content-Disposition: form-data; name="files"; filename="test{i}.txt"\r\n'
        f"Content-Type: text/plain\r\n"
        f"\r\n"
    )
    body_parts.append(file_data.decode())
    body_parts.append(f"\r\n--{boundary}\r\n")

body_parts[-1] = body_parts[-1].rstrip("\r\n") + "--\r\n"
body = "".join([
    p if isinstance(p, bytes) else p.encode() 
    for p in body_parts[:-1]
]) + body_parts[-1].encode()

req = urllib.request.Request(url, data=body)
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

try:
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
        print(f"✓ Success: {result}")
except urllib.error.URLError as e:
    print(f"✗ Error: {e}")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
