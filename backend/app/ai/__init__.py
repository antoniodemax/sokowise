"""The AI copilot (docs/ARCHITECTURE.md §6, PRD §20).

This package never imports `services` or `models` for business data. Its only
data access is the read-only `analytics` functions, named repository read
functions listed in `tools.py`, and the `ai` repository for its own tables.
"""
