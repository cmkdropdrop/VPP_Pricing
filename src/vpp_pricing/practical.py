"""Practical VPP pricing approach taxonomy.

The catalogue is intentionally separated from the numerical pricing
implementations.  It keeps the repository centred on economically relevant
VPP use cases and makes clear which methods are implemented versus planned.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PracticalPricingApproach:
    id: str
    name: str
    economic_role: str
    primary_users: tuple[str, ...]
    revenue_streams: tuple[str, ...]
    markets: tuple[str, ...]
    decision_style: str
    implementation_status: str
    implemented_method: str | None
    economic_relevance: str
    example_users: tuple[str, ...]
    mispricing_risks: tuple[str, ...]
    validation_focus: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "economic_role": self.economic_role,
            "primary_users": list(self.primary_users),
            "revenue_streams": list(self.revenue_streams),
            "markets": list(self.markets),
            "decision_style": self.decision_style,
            "implementation_status": self.implementation_status,
            "implemented_method": self.implemented_method,
            "economic_relevance": self.economic_relevance,
            "example_users": list(self.example_users),
            "mispricing_risks": list(self.mispricing_risks),
            "validation_focus": list(self.validation_focus),
        }


PRACTICAL_APPROACHES: tuple[PracticalPricingApproach, ...] = (
    PracticalPricingApproach(
        id="benchmark_intrinsic",
        name="Intrinsic benchmark / perfect-foresight dispatch",
        economic_role=(
            "Upper-bound valuation and opportunity-cost benchmark for flexible assets."
        ),
        primary_users=(
            "asset owners",
            "trading analysts",
            "lenders",
            "portfolio managers",
        ),
        revenue_streams=("energy arbitrage", "curtailment value", "dispatch value"),
        markets=("day-ahead", "intraday reference curves"),
        decision_style="full-horizon deterministic optimisation",
        implementation_status="implemented",
        implemented_method="intrinsic",
        economic_relevance="high as a benchmark, low as an executable strategy",
        example_users=("asset valuation teams", "route-to-market desks"),
        mispricing_risks=(
            "overvalues flexibility when forecast uncertainty is ignored",
            "ignores bid-ask spreads, market depth, and execution latency",
            "can understate imbalance exposure for renewables and loads",
            "can overcycle storage if degradation is too coarsely modelled",
        ),
        validation_focus=(
            "upper-bound gap versus rolling forecast dispatch",
            "sensitivity to terminal state-of-charge assumptions",
            "degradation and variable cost assumptions",
        ),
    ),
    PracticalPricingApproach(
        id="rolling_forecast_dispatch",
        name="Rolling forecast dispatch / balancing-group optimisation",
        economic_role=(
            "Executable short-term dispatch that re-optimises with updated forecasts."
        ),
        primary_users=(
            "VPP aggregators",
            "balance responsible parties",
            "renewable route-to-market providers",
            "battery optimisers",
        ),
        revenue_streams=(
            "day-ahead and intraday trading",
            "imbalance cost avoidance",
            "short-term flexibility value",
        ),
        markets=("day-ahead", "intraday continuous", "imbalance settlement"),
        decision_style="receding-horizon optimisation with committed first interval",
        implementation_status="implemented",
        implemented_method="rolling_intrinsic",
        economic_relevance="high",
        example_users=("Next Kraftwerke", "Statkraft", "Centrica Energy"),
        mispricing_risks=(
            "forecast error between optimisation and delivery",
            "intraday liquidity gaps in stressed intervals",
            "terminal-value myopia when the look-ahead window is too short",
            "basis risk between local asset constraints and exchange prices",
        ),
        validation_focus=(
            "value loss versus intrinsic benchmark",
            "forecast-window sensitivity",
            "imbalance stress against price spikes",
        ),
    ),
    PracticalPricingApproach(
        id="stochastic_merchant_bidding",
        name="Stochastic merchant bidding / automated optimiser",
        economic_role=(
            "Probabilistic bid optimisation for merchant batteries and hybrid assets."
        ),
        primary_users=(
            "battery storage owners",
            "renewable-plus-storage operators",
            "optimisation software vendors",
            "merchant trading desks",
        ),
        revenue_streams=(
            "energy arbitrage",
            "ancillary services",
            "capacity or resource adequacy",
            "scarcity-event optionality",
        ),
        markets=("day-ahead", "real-time", "ancillary services", "capacity"),
        decision_style="scenario-based valuation and risk-aware bidding",
        implementation_status="implemented baseline",
        implemented_method="monte_carlo",
        economic_relevance="high",
        example_users=("Tesla Autobidder", "Fluence Mosaic", "KrakenFlex"),
        mispricing_risks=(
            "wrong tail distribution for scarcity and negative-price events",
            "incorrect revenue stacking across mutually exclusive products",
            "underpriced degradation, warranty, and availability constraints",
            "model drift when market rules or participant behaviour changes",
        ),
        validation_focus=(
            "weighted scenario calibration",
            "tail CVaR and drawdown diagnostics",
            "cycle-cost and availability sensitivity",
        ),
    ),
    PracticalPricingApproach(
        id="balancing_ancillary_services",
        name="Balancing and ancillary-services aggregation",
        economic_role=(
            "Prequalified flexible capacity sold to TSOs/grid operators for system "
            "stability."
        ),
        primary_users=(
            "VPP aggregators",
            "C&I demand-response providers",
            "storage operators",
            "TSO-facing BSPs",
        ),
        revenue_streams=(
            "availability payments",
            "activation energy",
            "frequency response",
            "reserve products",
        ),
        markets=("FCR", "aFRR", "mFRR", "interruptible load", "local reserves"),
        decision_style="capacity reservation plus activation-response valuation",
        implementation_status="planned",
        implemented_method=None,
        economic_relevance="very high where prequalification is available",
        example_users=("Next Kraftwerke", "Enel X", "Statkraft"),
        mispricing_risks=(
            "non-delivery penalties and failed activation performance",
            "baseline and measurement error for demand response",
            "double-counting capacity already committed in spot markets",
            "telemetry or remote-control outages during activation",
        ),
        validation_focus=(
            "prequalification limits",
            "activation probability and duration distribution",
            "penalty and baseline methodology",
        ),
    ),
    PracticalPricingApproach(
        id="retail_tariff_flex",
        name="Retail tariff / residential demand-flex VPP",
        economic_role=(
            "Customer-sited device orchestration for retail margin, peak reduction, "
            "and grid services."
        ),
        primary_users=(
            "energy retailers",
            "utilities",
            "residential VPP platforms",
            "EV and home-battery aggregators",
        ),
        revenue_streams=(
            "retail load shaping",
            "wholesale procurement savings",
            "network flexibility",
            "customer incentive spread",
        ),
        markets=("retail tariffs", "demand response", "local flexibility", "balancing"),
        decision_style="customer-constrained device scheduling and event dispatch",
        implementation_status="planned",
        implemented_method=None,
        economic_relevance="high and growing",
        example_users=("Octopus Energy / KrakenFlex", "Tesla Electric"),
        mispricing_risks=(
            "customer opt-out and comfort constraints reduce delivered flexibility",
            "baseline gaming or inaccurate event measurement",
            "rebound load after dispatch creates hidden system cost",
            "retail tariff arbitrage can leak value if product rules are loose",
        ),
        validation_focus=(
            "participation and opt-out rates",
            "baseline estimation",
            "customer incentive versus system value",
        ),
    ),
    PracticalPricingApproach(
        id="hedged_route_to_market",
        name="Hedged route-to-market / PPA plus imbalance management",
        economic_role=(
            "Bankable commercial route for renewables and flexible portfolios with "
            "residual balancing risk."
        ),
        primary_users=(
            "renewable generators",
            "corporate PPA offtakers",
            "utilities",
            "route-to-market providers",
        ),
        revenue_streams=(
            "PPA or feed-in revenue",
            "shape and profile management",
            "imbalance cost mitigation",
            "curtailment optimisation",
        ),
        markets=("PPAs", "day-ahead", "intraday", "imbalance settlement"),
        decision_style="hedge valuation plus residual physical balancing",
        implementation_status="planned",
        implemented_method=None,
        economic_relevance="very high for financeable renewable portfolios",
        example_users=("Statkraft", "Next Kraftwerke", "utility trading desks"),
        mispricing_risks=(
            "shape risk between flat hedges and weather-driven generation",
            "negative-price and curtailment clauses are misvalued",
            "counterparty and collateral costs are omitted",
            "imbalance cost tails are hidden by average forecast-error assumptions",
        ),
        validation_focus=(
            "hedge shape versus generation profile",
            "negative-price clause sensitivity",
            "imbalance and collateral stress",
        ),
    ),
    PracticalPricingApproach(
        id="network_flex_non_wires",
        name="Network flexibility / non-wires alternative",
        economic_role=(
            "Location-specific flexibility used to defer grid reinforcement and "
            "manage congestion."
        ),
        primary_users=(
            "DSOs",
            "utilities",
            "local flexibility platforms",
            "aggregators with locational assets",
        ),
        revenue_streams=(
            "congestion management",
            "network capacity deferral",
            "local flexibility tenders",
        ),
        markets=("DSO flexibility", "local congestion markets", "non-wires tenders"),
        decision_style="locational availability and activation valuation",
        implementation_status="planned",
        implemented_method=None,
        economic_relevance="medium today, high in constrained grids",
        example_users=("DSOs", "EPEX Localflex-style markets", "KrakenFlex partners"),
        mispricing_risks=(
            "locational deliverability is priced as system-wide flexibility",
            "conflicting commitments across wholesale and network products",
            "activation scarcity and testing requirements are underestimated",
            "distribution constraints make portfolio aggregation non-fungible",
        ),
        validation_focus=(
            "node or feeder eligibility",
            "stacking rules across products",
            "activation conflict simulation",
        ),
    ),
)


def list_practical_approaches(
    *, implemented_only: bool = False
) -> tuple[PracticalPricingApproach, ...]:
    if not implemented_only:
        return PRACTICAL_APPROACHES
    return tuple(
        approach
        for approach in PRACTICAL_APPROACHES
        if approach.implemented_method is not None
    )


def get_practical_approach(approach_id: str) -> PracticalPricingApproach:
    for approach in PRACTICAL_APPROACHES:
        if approach.id == approach_id:
            return approach
    raise ValueError(f"unknown practical pricing approach: {approach_id!r}")


def approach_for_method(method_name: str) -> PracticalPricingApproach | None:
    for approach in PRACTICAL_APPROACHES:
        if approach.implemented_method == method_name:
            return approach
    return None
