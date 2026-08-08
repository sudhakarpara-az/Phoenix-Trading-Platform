# M09 — Broker & Account Management Engine

## Status

COMPLETE

## Tasks Completed

- M09-T01 Broker & Account Domain Models
- M09-T02 Broker Session Manager
- M09-T03 Account Profile Provider
- M09-T04 Funds & Margin Snapshot
- M09-T05 Account Trading Eligibility
- M09-T06 Broker Connectivity Monitor
- M09-T07 Account State Registry
- M09-T08 Account Persistence Schema
- M09-T09 Account Repository Layer
- M09-T10 Dhan Account Adapter
- M09-T11 M08 → M09 Runtime Integration
- M09-T12 M09 → M06 Execution Safety Gate
- M09-T13 Exit Safety Semantics
- M09-T14 Session Expiry / Re-auth Handling
- M09-T15 Broker / Account Reconciliation
- M09-T16 Failure & Edge-Case Tests
- M09-T17 Full Regression & Milestone Closeout

## Architecture

    M08 Runtime
         |
         v
    M09 Account Runtime
         |
         +-- Broker Session
         +-- Account Profile
         +-- Funds / Margin
         +-- Connectivity
         +-- Account Health
         +-- Trading Eligibility
         +-- State Registry
         +-- Persistence
         +-- Re-authentication
         +-- Reconciliation
         |
         v
    M06 Entry Execution

Protective exits remain independent:

    M07 Exit Decision
         |
         v
    Protective Exit Safety
         |
         v
    M06 SELL Execution

## New-Entry Safety

A new BUY requires verified:

- Broker connectivity
- Authenticated broker session
- Active account
- Trading-enabled account
- Current profile
- Current funds
- Sufficient available cash
- Matching broker/account identity

M09 eligibility is only one Phoenix safety gate.

M07 risk, M08 runtime state, and M06 execution eligibility remain
independent.

## Exit Safety

M09 NEW-ENTRY restrictions must never independently suppress an
existing position's protective SELL.

This includes:

- Target exit
- Stop-loss exit
- 15:15 force exit

Broker/execution failures remain visible and are handled by the
existing execution/reconciliation architecture.

## Session Safety

- Expired sessions block new entries.
- Failed sessions block new entries.
- Concurrent re-authentication is prevented.
- New-entry readiness is restored only after authentication succeeds.
- Closed session managers remain terminal.

## Reconciliation

Persisted account state identifies the account Phoenix previously
operated.

Live broker state remains authoritative.

Startup reconciliation validates:

- Broker identity
- Account identity
- Session state
- Connectivity
- Account profile
- Funds state

Unknown or inconsistent broker/account truth fails closed.

Insufficient funds is not itself a reconciliation failure. It is a
new-entry eligibility failure.

## Persistence

M09 adds:

- broker_accounts
- broker_sessions
- account_fund_snapshots
- broker_connectivity_snapshots
- account_health_snapshots
- account_eligibility_snapshots

Broker credentials, access tokens, PINs, passwords, TOTP secrets, and
API secrets are not persisted.

## Regression

Full repository:

    python -m pytest -q

Result:

     1431 passed in 3.29s

Database:

    foreign_keys = 1
    integrity_check = ok

## Milestone Result

M09 Broker & Account Management Engine is complete and ready for
merge into develop.