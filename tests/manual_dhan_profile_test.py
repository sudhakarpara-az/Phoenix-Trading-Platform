import os

import requests
from dotenv import load_dotenv


load_dotenv()


client_id = os.getenv("DHAN_CLIENT_ID")
access_token = os.getenv("DHAN_ACCESS_TOKEN")

if not client_id:
    raise RuntimeError("DHAN_CLIENT_ID missing")

if not access_token:
    raise RuntimeError("DHAN_ACCESS_TOKEN missing")


url = "https://api.dhan.co/v2/profile"

headers = {
    "access-token": access_token,
}


response = requests.get(
    url,
    headers=headers,
    timeout=15,
)


print("=" * 60)
print("DHAN PROFILE TEST")
print("=" * 60)

print("HTTP status:", response.status_code)

print()
print("RESPONSE")
print("--------")
print(response.text)