"""The HTTP layer serving the confirmation UI (Phase 1 slice 1B).

A *transport boundary*, not an abstraction: it owns HTTP, authentication and
serialization, and **no domain logic**. Every write endpoint is
`authenticate -> load projection -> call exactly one storage/confirmations.py
function -> return`. Logic that isn't already in `storage/` belongs *in*
`storage/`, never in a route handler -- two write paths where only one is tested
is the failure mode this module is shaped to prevent
(`docs/decisions/2026-08-11-api-frontend-module-boundary.md` §2).
"""
