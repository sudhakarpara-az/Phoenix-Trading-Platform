# M07 — Position & Risk Management Engine

## Status

COMPLETE

## Scope Completed

- M07-T01 Position & Risk Domain Models
- M07-T02 Position Registry
- M07-T03 Stop-Loss Policy
- M07-T04 Position P&L Calculator
- M07-T05 Position Risk Snapshot
- M07-T06 Option Position Price Monitor
- M07-T07 Target Trigger Monitor
- M07-T08 Stop-Loss Trigger Monitor
- M07-T09 KS Underlying → Option Target Mapping Boundary
- M07-T10 Position Exit Decision Engine
- M07-T11 Position Lifecycle Manager
- M07-T12 Exposure / Quantity Risk Limits
- M07-T13 Daily Risk Manager
- M07-T14 15:15 Position Force-Exit Coordinator
- M07-T15 M06 → M07 Filled Position Integration
- M07-T16 M07 → M06 Exit Integration
- M07-T17 Target / Stop / Force-Exit Priority & Race Handling
- M07-T18 Realized & Unrealized P&L Tracking
- M07-T19 Re-entry Risk Synchronization
- M07-T20 Full Position Lifecycle Integration
- M07-T21 Failure & Edge-Case Tests
- M07-T22 Full Regression & Milestone Closeout

## Core Safety Invariants

1. Actual broker fill price is the position cost basis.
2. Stop-loss is calculated from actual entry fill.
3. Only remaining open quantity may be exited.
4. Stale market data cannot trigger target or stop-loss exits.
5. Target exits use LIMIT orders.
6. Stop-loss exits use MARKET orders.
7. Mandatory 15:15 exits use MARKET orders.
8. Existing pending exits are reconciled before replacement.
9. Broker uncertainty moves positions to RECONCILIATION_REQUIRED.
10. Re-entry is released only after actual full position closure.
11. Daily risk locks block new entries but never position exits.
12. M07 never communicates directly with the broker; M06 owns execution.

## Regression

Final full repository regression:

    python -m pytest -q

Result:

   850 passed in 1.33s

## Milestone Result

M07 Position & Risk Management Engine is complete and ready for merge.