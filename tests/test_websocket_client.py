from src.market.market_service import MarketService
from src.market.tick_processor import TickProcessor
from src.market.websocket_client import WebSocketClient

service = MarketService()

processor = TickProcessor(service)

ws = WebSocketClient(processor)

print(ws.connected)

ws.connect()

print(ws.connected)

ws.disconnect()

print(ws.connected)