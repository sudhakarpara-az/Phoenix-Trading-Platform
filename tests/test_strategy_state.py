from src.strategy.strategy_state import StrategyState

print("Available Strategy States")
print("-" * 40)

for state in StrategyState:
    print(state.name, "->", state.value)

print("-" * 40)
print("Default:", StrategyState.IDLE)