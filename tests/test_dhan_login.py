from src.broker.dhan_broker import DhanBroker

broker = DhanBroker()

client = broker.get_client()

response = client.get_fund_limits()

print(response)