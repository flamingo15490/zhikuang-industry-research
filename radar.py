"""Compatibility entry points for the versioned snapshot radar."""
from pathlib import Path

from scoring import DIMS
from score_view import EN2CN, peer_context, query_view, read_snapshot

BASE = Path(__file__).resolve().parent
# Historical fixture path only; the UI never consumes this cache.
SCORES_CACHE = BASE / 'data' / 'radar_scores.parquet'


def _peer_context(code: str):
    return peer_context(read_snapshot(), code)


def draw_radar(query: str):
    return query_view(query)[:3]
