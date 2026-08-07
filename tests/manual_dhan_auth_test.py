import os

from dhanhq import DhanContext, dhanhq
from dotenv import load_dotenv


load_dotenv()


client_id = os.getenv("DHAN_CLIENT_ID")
access_token = os.getenv("DHAN_ACCESS_TOKEN")

if not client_id:
    raise RuntimeError("DHAN_CLIENT_ID missing")

if not access_token:
    raise RuntimeError("DHAN_ACCESS_TOKEN missing")


context = DhanContext(
    client_id,
    access_token,
)

dhan = dhanhq(context)


print("=" * 60)
print("DHAN AUTHENTICATION TEST")
print("=" * 60)

print("Client ID:", client_id)

print()
print("FUND LIMITS")
print("-----------")

response = dhan.get_fund_limits()

print(response)