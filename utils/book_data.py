"""
Book data module — ISBN lookup + marketplace data aggregation.

Architecture:
  MVP (now):   MockBookProvider  — hardcoded example data for development
  Phase 2:     JisuISBNProvider  — real 极速数据 ISBN API integration
  Phase 2:     KongfzAPIProvider — real 孔夫子开放平台 integration
  Future:      XianyuScraper, DuozhuayuScraper, etc.

Usage:
  from utils.book_data import get_book_provider
  provider = get_book_provider()         # returns best available provider
  info = provider.lookup_isbn("9787115380253")
  market = provider.get_market_data("9787115380253")
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BookInfo:
    """Basic book information from ISBN lookup."""
    title: str
    author: str
    publisher: str
    pub_date: str
    original_price: float
    isbn: str
    cover_url: str = ""
    summary: str = ""
    pages: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketDataPoint:
    """Price data from a single marketplace."""
    min_price: float
    max_price: float
    median_price: float
    listings: int
    sold_last_30d: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketData:
    """Aggregated market data across platforms."""
    kongfz: Optional[MarketDataPoint] = None
    xianyu: Optional[MarketDataPoint] = None
    duozhuayu_buy_price: Optional[float] = None
    duozhuayu_sell_price: Optional[float] = None

    def to_dict(self) -> dict:
        result = {}
        for k, v in asdict(self).items():
            if v is not None:
                result[k] = v
        return result


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------

class BookDataProvider(ABC):
    """Interface for book data providers."""

    @abstractmethod
    def lookup_isbn(self, isbn: str) -> Optional[BookInfo]:
        """Look up book metadata by ISBN. Returns None if not found."""
        ...

    @abstractmethod
    def get_market_data(self, isbn: str) -> MarketData:
        """Get current market pricing data for a book."""
        ...


# ---------------------------------------------------------------------------
# Mock provider (MVP / development)
# ---------------------------------------------------------------------------

_MOCK_BOOKS: dict[str, dict] = {
    "9787115380253": {
        "title": "Python编程：从入门到实践",
        "author": "Eric Matthes",
        "publisher": "人民邮电出版社",
        "pub_date": "2023-05",
        "original_price": 89.00,
        "cover_url": "",
        "summary": "零基础学Python入门教程，涵盖Python基础、项目实战",
        "pages": 456,
    },
    "9787115546082": {
        "title": "流畅的Python",
        "author": "Luciano Ramalho",
        "publisher": "人民邮电出版社",
        "pub_date": "2023-05",
        "original_price": 139.00,
        "cover_url": "",
        "summary": "Python进阶必备，深入理解Python语言特性",
        "pages": 768,
    },
    "9787115474884": {
        "title": "数据结构与算法：Python语言实现",
        "author": "Michael T. Goodrich",
        "publisher": "机械工业出版社",
        "pub_date": "2022-01",
        "original_price": 99.00,
        "cover_url": "",
        "summary": "经典数据结构教材的Python实现版",
        "pages": 592,
    },
    "9787544253994": {
        "title": "百年孤独",
        "author": "加西亚·马尔克斯",
        "publisher": "南海出版公司",
        "pub_date": "2011-06",
        "original_price": 39.50,
        "cover_url": "",
        "summary": "魔幻现实主义文学代表作，描写了布恩迪亚家族七代人的传奇故事",
        "pages": 360,
    },
    "9787544258975": {
        "title": "霍乱时期的爱情",
        "author": "加西亚·马尔克斯",
        "publisher": "南海出版公司",
        "pub_date": "2012-09",
        "original_price": 39.50,
        "cover_url": "",
        "summary": "讲述了一段跨越半个多世纪的爱情史诗",
        "pages": 401,
    },
}


class MockBookProvider(BookDataProvider):
    """Mock provider with hardcoded book data for MVP development."""

    def lookup_isbn(self, isbn: str) -> Optional[BookInfo]:
        clean = isbn.replace("-", "").strip()
        if clean in _MOCK_BOOKS:
            data = _MOCK_BOOKS[clean]
            return BookInfo(
                title=data["title"],
                author=data["author"],
                publisher=data["publisher"],
                pub_date=data["pub_date"],
                original_price=data["original_price"],
                isbn=clean,
                cover_url=data.get("cover_url", ""),
                summary=data.get("summary", ""),
                pages=data.get("pages", 0),
            )
        # Simulate a generic response for any ISBN in mock mode
        return BookInfo(
            title=f"图书 {clean}",
            author="未知作者",
            publisher="未知出版社",
            pub_date="未知",
            original_price=50.00,
            isbn=clean,
        )

    def get_market_data(self, isbn: str) -> MarketData:
        clean = isbn.replace("-", "").strip()
        # Simulate realistic market data based on book type
        if clean == "9787115380253":
            return MarketData(
                kongfz=MarketDataPoint(25.0, 65.0, 38.0, 127, 43),
                xianyu=MarketDataPoint(20.0, 55.0, 32.0, 89),
                duozhuayu_sell_price=35.0,
                duozhuayu_buy_price=12.0,
            )
        elif clean == "9787115546082":
            return MarketData(
                kongfz=MarketDataPoint(45.0, 120.0, 78.0, 83, 21),
                xianyu=MarketDataPoint(35.0, 95.0, 65.0, 56),
                duozhuayu_sell_price=60.0,
                duozhuayu_buy_price=25.0,
            )
        elif clean == "9787544253994":
            return MarketData(
                kongfz=MarketDataPoint(15.0, 35.0, 22.0, 312, 89),
                xianyu=MarketDataPoint(10.0, 28.0, 18.0, 245),
                duozhuayu_sell_price=22.0,
                duozhuayu_buy_price=6.0,
            )
        elif clean == "9787544258975":
            return MarketData(
                kongfz=MarketDataPoint(12.0, 30.0, 20.0, 256, 67),
                xianyu=MarketDataPoint(10.0, 25.0, 16.0, 189),
                duozhuayu_sell_price=20.0,
                duozhuayu_buy_price=5.0,
            )
        else:
            # Generic fallback
            return MarketData(
                kongfz=MarketDataPoint(
                    round(clean[-3:], 1),
                    round(float(clean[-3:]) * 3, 1),
                    round(float(clean[-3:]) * 1.5, 1),
                    50, 15),
            )


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def get_book_provider() -> BookDataProvider:
    """
    Returns the best available book data provider based on configuration.
    
    Priority:
    1. If JISU_API_KEY is set → JisuISBNProvider
    2. If KONGFZ_API_KEY is set → KongfzAPIProvider  
    3. Otherwise → MockBookProvider (MVP mode)
    
    For MVP, returns MockBookProvider by default.
    """
    # TODO: Phase 2 — wire up real providers when API keys are configured
    # jisu_key = os.environ.get("JISU_API_KEY")
    # if jisu_key:
    #     return JisuISBNProvider(api_key=jisu_key)
    
    return MockBookProvider()


# ---------------------------------------------------------------------------
# Cache helper (for Redis/future caching)
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, any]] = {}
CACHE_TTL = 86400  # 24 hours


def cached_lookup(provider: BookDataProvider, isbn: str) -> Optional[BookInfo]:
    """Cached ISBN lookup to reduce API costs."""
    now = time.time()
    if isbn in _CACHE and (now - _CACHE[isbn][0]) < CACHE_TTL:
        return _CACHE[isbn][1]
    result = provider.lookup_isbn(isbn)
    if result:
        _CACHE[isbn] = (now, result)
    return result
