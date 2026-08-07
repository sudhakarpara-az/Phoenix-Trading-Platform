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
print("DHAN MARKET QUOTE TEST")
print("=" * 60)


securities = {
    "IDX_I": [13],
}


response = dhan.ticker_data(
    securities
)


print()
print("MARKET QUOTE RESPONSE")
print("---------------------")
print(response)