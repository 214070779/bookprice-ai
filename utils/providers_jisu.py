"""
极速数据 ISBN API provider (Phase 2).

API docs: https://www.jisuapi.com/api/isbn/
Pricing:  ¥140 / 10,000 calls (0.014元/call)
Free trial: 100 calls

Usage:
    from utils.providers_jisu import JisuISBNProvider
    provider = JisuISBNProvider(api_key="your_key")
    info = provider.lookup_isbn("9787115380253")

Note: This provider only covers book METADATA (title, author, publisher).
Market pricing data still comes from Kongfz or mock data.
"""

from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from utils.book_data import BookInfo, BookDataProvider, MarketData

# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class JisuAPIError(Exception):
    """Raised when the 极速数据 API returns an error."""


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class JisuISBNProvider(BookDataProvider):
    """
    Real ISBN lookup via 极速数据 API.

    Provides book metadata only. Market data falls back to mock.
    """

    BASE_URL = "https://api.jisuapi.com/isbn/query"
    DEFAULT_TIMEOUT = 10.0  # seconds
    MAX_RETRIES = 2

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._client = client

    def _get_client(self) httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.DEFAULT_TIMEOUT)
        return self._client

    # ------------------------------------------------------------------
    # BookDataProvider interface
    # ------------------------------------------------------------------

    def lookup_isbn(self, isbn: str) -> Optional[BookInfo]:
        clean = isbn.replace("-", "").strip()
        if len(clean) not in (10, 13):
            return None

        last_err: Optional[Exception] = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                return self._do_lookup(clean)
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500 and attempt < self.MAX_RETRIES:
                    continue  # retry on 5xx
                last_err = e
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(1 * (attempt + 1))
                    continue
            except JisuAPIError:
                raise

        # log warning in production
        return None

    def get_market_data(self, isbn: str) -> MarketData:
        """Jisu API only provides metadata. Market data returns empty."""
        return MarketData()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_lookup(self, isbn: str) -> Optional[BookInfo]:
        client = self._get_client()
        resp = client.get(
            self.BASE_URL,
            params={"appkey": self.api_key, "isbn": isbn},
        )
        resp.raise_for_status()
        body = resp.json()

        # 极速数据 returns {"status": 0, "msg": "ok", "result": {...}}
        status = body.get("status", -1)
        if status != 0:
            msg = body.get("msg", "unknown error")
            raise JisuAPIError(f"Jisu API error (status={status}): {msg}")

        result = body.get("result")
        if not result:
            return None

        # Map to BookInfo
        try:
            return BookInfo(
                title=result.get("title", ""),
                author=result.get("author", ""),
                publisher=result.get("publisher", ""),
                pub_date=result.get("pubdate", ""),
                original_price=float(result.get("price", 0) or 0),
                isbn=isbn,
                cover_url=result.get("pic", ""),
                summary=result.get("summary", ""),
                pages=int(result.get("pages", 0) or 0),
            )
        except (ValueError, TypeError) as e:
            raise JisuAPIError(f"Failed to parse Jisu response: {e}") from e
