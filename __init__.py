"""Hermes model-provider discovery entrypoint (not a generic tool plugin)."""
from providers import register_provider
from .vibe_provider import profile

register_provider(profile)
