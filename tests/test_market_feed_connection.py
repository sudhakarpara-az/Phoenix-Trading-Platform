from src.broker.dhan_broker import DhanBroker
from src.market.market_service import MarketService
from src.market.tick_processor import TickProcessor
from src.broker.dhan_market_feed import DhanMarketFeed

broker = DhanBroker()

context = broker.get_context()

service = MarketService()

processor = TickProcessor(service)

feed = DhanMarketFeed(
    dhan_context=context,
    instruments=[],
    processor=processor,
)

print("Feed object created successfully.")