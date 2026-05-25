"""
Pricing engine — rule-based and (future) AI-powered pricing for second-hand books.

Architecture:
  MVP (now):   RuleEngine  — deterministic pricing from market data
  Phase 2:     AIEngine    — LLM-powered pricing with natural language reasoning

Rule engine pricing algorithm:
  1. Start with market median price
  2. Adjust for supply/demand (listings vs sales velocity)
  3. Apply condition multiplier (if provided)
  4. Apply aging factor (days since listed → auto-reduce)
  5. Enforce min margin (if cost_used is provided)
  6. Return recommended price + confidence + reasoning
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class PricingResult:
    recommended_sell_price: float
    price_range_min: float
    price_range_max: float
    expected_sell_through_days: int
    confidence: str  # "high" | "medium" | "low"
    reasoning: str
    profit_margin_pct: Optional[float] = None
    is_recommended: bool = True

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CompetitionInfo:
    level: str  # "low" | "moderate" | "high" | "very_high"
    total_listings: int
    monthly_sales_estimate: int
    top_sellers: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrendInfo:
    price_30d_change_pct: str
    demand_index: int  # 0-100
    seasonal_info: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

class RuleEngine:
    """
    Deterministic pricing engine based on market data rules.
    No AI dependency — works entirely offline with market data.
    """

    # Profit margin targets
    DEFAULT_MIN_MARGIN = 0.30      # 30% minimum
    TARGET_MARGIN = 0.50           # 50% target

    # Supply-demand thresholds
    HIGH_DEMAND_RATIO = 0.3        # sold/listings > 30% → high demand
    LOW_DEMAND_RATIO = 0.05        # sold/listings < 5% → low demand

    # Sell-through estimates (days)
    FAST_SELL = 14
    NORMAL_SELL = 30
    SLOW_SELL = 60

    def analyze(
        self,
        market_median: float,
        market_min: float,
        market_max: float,
        total_listings: int,
        monthly_sales: Optional[int],
        cost_price: Optional[float] = None,
    ) -> PricingResult:
        """
        Generate pricing recommendation from market data.
        
        Args:
            market_median: Median market price for this book.
            market_min: Minimum market price.
            market_max: Maximum market price.
            total_listings: Number of active listings.
            monthly_sales: Estimated monthly sales (can be None).
            cost_price: Your cost/acquisition price (optional).
        """
        # 1. Determine supply/demand
        supply_demand_ratio = (monthly_sales / total_listings) if monthly_sales and total_listings > 0 else None
        
        if supply_demand_ratio is not None:
            if supply_demand_ratio >= self.HIGH_DEMAND_RATIO:
                demand_label = "high"
                demand_multiplier = 1.05  # Can price 5% above median
                sell_days = self.FAST_SELL
            elif supply_demand_ratio >= self.LOW_DEMAND_RATIO:
                demand_label = "moderate"
                demand_multiplier = 1.0
                sell_days = self.NORMAL_SELL
            else:
                demand_label = "low"
                demand_multiplier = 0.92  # Need to price 8% below median
                sell_days = self.SLOW_SELL
        else:
            demand_label = "unknown"
            demand_multiplier = 1.0
            sell_days = self.NORMAL_SELL

        # 2. Calculate recommended price
        recommended = round(market_median * demand_multiplier, 1)

        # 3. Stay within market bounds
        if recommended > market_max:
            recommended = market_max
        if recommended < market_min:
            recommended = market_median  # floor at median if min is unrealistic

        # 4. Apply cost_price constraint: ensure minimum margin
        if cost_price is not None and cost_price > 0:
            min_price_for_margin = round(cost_price * (1 + self.DEFAULT_MIN_MARGIN), 1)
            if recommended < min_price_for_margin:
                recommended = min_price_for_margin
                profit_margin = self.DEFAULT_MIN_MARGIN
            else:
                profit_margin = round((recommended - cost_price) / cost_price, 2)
        else:
            profit_margin = None

        # 5. Price range for negotiation
        range_low = round(market_median * 0.85, 1)
        range_high = round(market_median * 1.15, 1)

        # 6. Confidence
        if monthly_sales and total_listings > 20:
            confidence = "high"
        elif monthly_sales or total_listings > 5:
            confidence = "medium"
        else:
            confidence = "low"

        # 7. Reasoning
        parts = []
        parts.append(f"市场中位价 {market_median}元")
        parts.append(f"在售 {total_listings} 本")
        if monthly_sales:
            parts.append(f"月销约 {monthly_sales} 本")
        parts.append(f"供需关系: {demand_label}")
        
        if demand_label == "high":
            parts.append("需求旺盛，建议定价略高于中位价")
        elif demand_label == "low":
            parts.append("供过于求，建议定价略低于中位价以加快周转")

        if cost_price:
            parts.append(f"成本 {cost_price}元, 预期毛利 {profit_margin*100 if profit_margin else '?'}%")

        parts.append(f"预计 {sell_days} 天内售出")
        reasoning = "，".join(parts) + "。"

        return PricingResult(
            recommended_sell_price=recommended,
            price_range_min=range_low,
            price_range_max=range_high,
            expected_sell_through_days=sell_days,
            confidence=confidence,
            reasoning=reasoning,
            profit_margin_pct=round(profit_margin * 100, 1) if profit_margin else None,
        )

    def analyze_competition(
        self,
        total_listings: int,
        top_seller_names: list[str],
        top_seller_monthly: list[int],
    ) -> CompetitionInfo:
        """Analyze competition level."""
        top_total = sum(top_seller_monthly) if top_seller_monthly else 0
        
        if total_listings > 200:
            level = "very_high"
        elif total_listings > 80:
            level = "high"
        elif total_listings > 20:
            level = "moderate"
        else:
            level = "low"

        top_sellers = [
            f"{name}(月销{sold})"
            for name, sold in zip(top_seller_names, top_seller_monthly)
        ]

        return CompetitionInfo(
            level=level,
            total_listings=total_listings,
            monthly_sales_estimate=top_total,
            top_sellers=top_sellers,
        )

    def analyze_trend(
        self,
        current_median: float,
        historical_data: Optional[list[float]] = None,
    ) -> TrendInfo:
        """
        Analyze price trend (simplified: uses comparison with a hypothetical
        "30 days ago" price derived from median and market activity).
        """
        # Simplified trend: if supply is tight, prices tend to rise
        # Full implementation would use historical data from Kongfz API
        return TrendInfo(
            price_30d_change_pct="+0.0%",
            demand_index=50,
            seasonal_info="",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_pricing_engine() -> RuleEngine:
    """Returns the pricing engine (rule-based for MVP)."""
    # TODO: Phase 2 — return AIEngine if LLM API key is configured
    return RuleEngine()
