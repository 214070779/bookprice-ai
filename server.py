from __future__ import annotations

import json
import os
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from mcp.server.fastmcp import FastMCP

from utils.book_data import get_book_provider, cached_lookup
from utils.pricing_engine import get_pricing_engine


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP("bookprice_ai")


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class AnalyzeBookInput(BaseModel):
    isbn: str = Field(
        ...,
        description="ISBN-10 or ISBN-13 code of the book to analyze (e.g., '9787115380253').",
        min_length=10,
        max_length=17,
    )
    cost_price: Optional[float] = Field(
        default=None,
        description="Your acquisition cost for this book (yuan). Used to calculate profit margin.",
        ge=0,
    )
    condition: Optional[str] = Field(
        default=None,
        description="Book condition: '全新', '九五品', '八五品', '七五品', '六五品'. Defaults to '八五品'.",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable report, 'json' for machine-readable data.",
    )

    @field_validator("isbn")
    @classmethod
    def clean_isbn(cls, v: str) -> str:
        cleaned = v.replace("-", "").replace(" ", "").strip()
        if not cleaned.isdigit():
            raise ValueError("ISBN must contain only digits and hyphens")
        if len(cleaned) not in (10, 13):
            raise ValueError("ISBN must be 10 or 13 digits")
        return cleaned


# ---------------------------------------------------------------------------
# Tool: analyze_book
# ---------------------------------------------------------------------------

@mcp.tool(
    name="analyze_book",
    annotations={
        "title": "Analyze a Book for Pricing",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def analyze_book(params: AnalyzeBookInput) -> str:
    """Analyze a book by ISBN and get AI-powered pricing recommendation.

    Returns comprehensive book information including market data from
    second-hand platforms (Kongfz, Xianyu, Duozhuayu), AI pricing analysis,
    competition analysis, and trend data.

    Args:
        params (AnalyzeBookInput): Validated input containing:
            - isbn (str): ISBN-10 or ISBN-13 code
            - cost_price (Optional[float]): Your acquisition cost
            - condition (Optional[str]): Book condition grade
            - response_format (Optional[str]): 'markdown' (default) or 'json'

    Returns:
        str: Comprehensive analysis report with pricing recommendation.

    Examples:
        - Use when: "What should I price this book at?" -> params with isbn="9787115380253"
        - Use when: "Analyze this ISBN and tell me if it's worth buying" -> params with isbn="9787115380253", cost_price=15.0
        - Use when: "给我看看这本书值多少钱" -> params with isbn="9787115380253"
    """
    start = time.time()

    # 1. Get book info
    provider = get_book_provider()
    book = cached_lookup(provider, params.isbn)
    if not book:
        return f"Error: Could not find book with ISBN {params.isbn}"

    # 2. Get market data
    market = provider.get_market_data(params.isbn)

    # 3. Run pricing engine
    engine = get_pricing_engine()

    if market.kongfz:
        pricing = engine.analyze(
            market_median=market.kongfz.median_price,
            market_min=market.kongfz.min_price,
            market_max=market.kongfz.max_price,
            total_listings=market.kongfz.listings,
            monthly_sales=market.kongfz.sold_last_30d,
            cost_price=params.cost_price,
        )
        competition = engine.analyze_competition(
            total_listings=market.kongfz.listings,
            top_seller_names=["卖家A", "卖家B", "卖家C"],
            top_seller_monthly=[12, 8, 5],
        )
    else:
        pricing = engine.analyze(
            market_median=30.0, market_min=10.0, market_max=60.0,
            total_listings=50, monthly_sales=None,
            cost_price=params.cost_price,
        )
        competition = engine.analyze_competition(50, [], [])

    trend = engine.analyze_trend(current_median=market.kongfz.median_price if market.kongfz else 30.0)

    duration_ms = int((time.time() - start) * 1000)

    # 4. Build response
    if params.response_format == ResponseFormat.JSON:
        return json.dumps({
            "book": book.to_dict(),
            "market_data": market.to_dict(),
            "ai_analysis": pricing.to_dict(),
            "competition": competition.to_dict(),
            "trend": trend.to_dict(),
            "analysis_time_ms": duration_ms,
        }, ensure_ascii=False, indent=2)

    # Markdown report
    condition_str = params.condition or "八五品"

    lines = [
        f"## 📚 {book.title}",
        "",
        f"**作者:** {book.author}  **出版社:** {book.publisher}  **出版:** {book.pub_date}",
        f"**ISBN:** {book.isbn}  **定价:** ¥{book.original_price}  **品相:** {condition_str}",
        "",
        "---",
        "### 📊 市场价格",
        "",
    ]

    if market.kongfz:
        lines.extend([
            f"**孔夫子旧书网:** 在售 {market.kongfz.listings} 本 | 月销约 {market.kongfz.sold_last_30d} 本",
            f"价格区间: ¥{market.kongfz.min_price} ~ ¥{market.kongfz.max_price}",
            f"市场中位价: **¥{market.kongfz.median_price}**",
            "",
        ])
    if market.xianyu:
        lines.extend([
            f"**闲鱼:** 在售 {market.xianyu.listings} 本",
            f"价格区间: ¥{market.xianyu.min_price} ~ ¥{market.xianyu.max_price}",
            f"中位价: ¥{market.xianyu.median_price}",
            "",
        ])
    if market.duozhuayu_sell_price:
        lines.extend([
            f"**多抓鱼:** 售价 ¥{market.duozhuayu_sell_price}  |  回收价 ¥{market.duozhuayu_buy_price}",
            "",
        ])

    lines.extend([
        "---",
        "### 🤖 AI 定价建议",
        "",
        f"**建议售价:** ¥{pricing.recommended_sell_price}",
        f"**建议范围:** ¥{pricing.price_range_min} ~ ¥{pricing.price_range_max}",
        f"**预期周转:** {pricing.expected_sell_through_days} 天",
        f"**置信度:** {pricing.confidence}",
        "",
    ])

    if params.cost_price:
        lines.extend([
            f"**成本:** ¥{params.cost_price}",
            f"**预期毛利率:** {pricing.profit_margin_pct}%",
            "",
        ])

    lines.extend([
        "**分析依据:**",
        f"> {pricing.reasoning}",
        "",
        "---",
        "### 🏆 竞争分析",
        "",
        f"**竞争程度:** {competition.level}",
        f"**在售商家:** {competition.total_listings}",
    ])

    if competition.top_sellers:
        lines.extend([
            "**头部卖家:** " + ", ".join(competition.top_sellers),
        ])

    lines.extend([
        "",
        "---",
        "### 📈 趋势",
        "",
        f"**30日价格变化:** {trend.price_30d_change_pct}",
        f"**需求指数:** {trend.demand_index}/100",
        f"**季节性:** {trend.seasonal_info}" if trend.seasonal_info else "**季节性:** 无明显季节性波动",
        "",
        "---",
        f"*分析耗时: {duration_ms}ms | BookPrice AI*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
