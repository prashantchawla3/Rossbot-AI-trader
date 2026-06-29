"""core.news — real-time Alpaca/Benzinga news streaming + catalyst verification.

Components:
  NewsStreamAdapter  — WebSocket subscriber (Alpaca NewsDataStream, wildcard "*")
  CatalystClassifier — keyword-based SKIP / VERIFIED classification (no external calls)
  CatalystVerifier   — looks up cached news for a symbol and classifies it
"""

from core.news.catalyst_classifier import CatalystClassifier, CatalystResult
from core.news.catalyst_verifier import CatalystVerifier
from core.news.news_stream import NewsItem, NewsStreamAdapter

__all__ = [
    "CatalystClassifier",
    "CatalystResult",
    "CatalystVerifier",
    "NewsItem",
    "NewsStreamAdapter",
]
