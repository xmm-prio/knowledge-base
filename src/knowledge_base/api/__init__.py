"""The REST API the web UI is built on."""

from knowledge_base.api.app import UpstreamHealth, create_app

__all__ = ["UpstreamHealth", "create_app"]
