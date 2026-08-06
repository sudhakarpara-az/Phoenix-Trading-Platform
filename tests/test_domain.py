from datetime import datetime

from src.domain import KSLevel
from src.domain import OptionSide
from src.domain import Signal


signal = Signal(
    signal_id="SIG0001",
    timestamp=datetime.now(),
    level=KSLevel.K5,
    side=OptionSide.CALL,
    strike=25350,
    delta=0.61,
    option_price=101.25,
    quantity=130,
)

print(signal)