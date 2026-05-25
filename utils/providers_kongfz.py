"""孔夫子开放平台 API provider (Phase 2).

API docs: https://open.kongfz.com
Auth: AppKey + AppSecret + MD5 signature
Rate limit: QPS=3 per app

Endpoints:
  - books/search   — search second-hand listings
  - books/detail   — get detailed book info + price history
  - shops/search   — search seller shops
  - shops/detail   — get seller shop details
  - categories     — get book categories

Usage:
    from utils.providers_kongfz import KongfzAPIProvider
    provider = KongfzAPIProvider(app_key="your_key", app_secret="your_secret")
    info = provider.lookup_isbn("9787115380253")
    market = provider.get_market_data("9787115380253")
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

import httpx

from utils.book_data import BookInfo, BookDataProvider, MarketData, MarketDataPoint


class KongfzAPIError(Exception):
    """Kongfz API returned an error response."""


class KongfzAPIProvider(BookDataProvider):
    """
    Real book data via 孔夫子开放平台 API.

    Provides both book metadata AND real market pricing data
    from the largest Chinese second-hand book marketplace.
    """

    BASE_URL = "https://open.kongfz.com/api"
    DEFAULT_TIMEOUT = 10.0

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.DEFAULT_TIMEOUT)
        return self._client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _sign(self, params: dict) -> str:
        """Generate MD5 signature per Kongfz API spec."""
        sorted_keys = sorted(params.keys())
        raw = "".join(f"{k}{params[k]}" for k in sorted_keys) + self.app_secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    def _signed_params(self, extra: dict | None = None) -> dict:
        params: dict = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
        }
        if extra:
            params.update(extra)
        params["sign"] = self._sign(params)
        return params

    # ------------------------------------------------------------------
    # BookDataProvider interface
    # ------------------------------------------------------------------

    def lookup_isbn(self, isbn: str) -> Optional[BookInfo]:
        clean = isbn.replace("-", "").strip()
        try:
            result = self._books_detail(clean)
            return result
        except KongfzAPIError:
            return None

    def get_market_data(self, isbn: str) -> MarketData:
        clean = isbn.replace("-", "").strip()
        try:
            return self._search_market(clean)
        except KongfzAPIError:
            return MarketData()

    # ------------------------------------------------------------------
    # Kongfz API calls
    # ------------------------------------------------------------------

    def _books_detail(self, isbn: str) -> Optional[BookInfo]:
        """GET /books/detail — get book info by ISBN."""
        client = self._get_client()
        params = self._signed_params({"isbn": isbn})
        resp = client.get(f"{self.BASE_URL}/books/detail", params=params)
        resp.raise_for_status()
        body = self._check_response(resp.json())

        data = body.get("data") or body.get("result") or body
        if not data:
            return None

        try:
            return BookInfo(
                title=data.get("title", ""),
                author=data.get("author", ""),
                publisher=data.get("publisher", ""),
                pub_date=data.get("pubdate", ""),
                original_price=float(data.get("original_price", 0) or 0),
                isbn=isbn,
                cover_url=data.get("cover", ""),
                summary=data.get("summary", ""),
                pages=int(data.get("pages", 0) or 0),
            )
        except (ValueError, TypeError) as e:
            raise KongfzAPIError(f"Parse error: {e}") from e

    def _search_market(self, isbn: str) -> MarketData:
        """GET /books/search — search active listings and aggregate prices."""
        client = self._get_client()
        params = self._signed_params({"isbn": isbn, "page": 1, "page_size": 50})
        resp = client.get(f"{self.BASE_URL}/books/search", params=params)
        resp.raise_for_status()
        body = self._check_response(resp.json())

        items = (body.get("data") or body.get("result") or {}).get("list", [])
        if not items:
            return MarketData()

        prices = []
        for item in items:
            try:
                p = float(item.get("price", 0) or 0)
                if p > 0:
                    prices.append(p)
            except (ValueError, TypeError):
                continue

        if not prices:
            return MarketData()

        prices.sort()
        n = len(prices)
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2

        total_listings = body.get("total", n)
        sold = body.get("sold_last_30d")

        return MarketData(
            kongfz=MarketDataPoint(
                min_price=prices[0],
                max_price=prices[-1],
                median_price=round(median, 1),
                listings=total_listings,
                sold_last_30d=sold,
            )
        )

    # ------------------------------------------------------------------
    # Response validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_response(body: dict) -> dict:
        """Kongfz API returns {code: 0, msg: "ok", data: {...}}."""
        code = body.get("code", -1)
        if code != 0:
            msg = body.get("msg", body.get("message", "unknown"))
            raise KongfzAPIError(f"Kongfz error (code={code}): {msg}")
        return body
