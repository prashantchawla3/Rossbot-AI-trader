"""Phase-7 catalyst detection package — spec §1 §13.1."""

from adapters.catalyst.models import CatalystResult, CatalystTag, NewsItem
from adapters.catalyst.provider import NLPCatalystProvider

__all__ = ["CatalystResult", "CatalystTag", "NewsItem", "NLPCatalystProvider"]
