"""fleet: the deterministic half of the homelab agent fleet.

Everything here runs without a model: GitHub calls, Telegram sends, brain
episode writes, and the pipeline stage plumbing. Scripts in ../scripts are
thin and import from here; the model stages (dsh) only ever see prompts.
"""
