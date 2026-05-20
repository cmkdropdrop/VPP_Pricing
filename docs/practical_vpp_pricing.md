# Practical VPP Pricing Framework

This repo is organised around practical VPP pricing archetypes rather than
around isolated algorithms.  The numerical methods are useful only insofar as
they answer an economic question: which revenue stack is being priced, who uses
the approach, and which mispricing risk can create real losses.

## Market Context

VPPs aggregate distributed energy resources such as renewables, EV chargers,
smart buildings, flexible C&I loads, behind-the-meter storage, and dispatchable
backup assets so they can deliver grid services comparable to larger plants.
The economic relevance is material:
the US DOE estimates that 80-160 GW of VPPs by 2030 could reduce US grid costs
by about USD 10 billion per year.  RMI frames VPPs as a reliability,
affordability, decarbonisation, electrification, and consumer-empowerment
resource.

In Europe, day-ahead and intraday markets are physical markets.  Intraday
trading is used to adjust positions close to delivery and reduce imbalance
exposure.  In the US, FERC Order 2222 is the key market-access reference: it
requires RTO/ISO rules that allow DER aggregations to participate in wholesale
markets, subject to size, telemetry, metering, and coordination rules.

## Practical Approaches

| Approach | Economic role | Typical users | Repo status |
|---|---|---|---|
| Intrinsic benchmark | Upper bound and opportunity-cost benchmark | asset owners, lenders, analysts | implemented as `intrinsic` |
| Rolling forecast dispatch | Executable short-term optimisation and balancing-group management | VPP aggregators, BRPs, hybrid/flex portfolio operators | implemented as `rolling_intrinsic` |
| Stochastic VPP scenario pricing | Scenario-based valuation for portfolio cashflows and tails | aggregators, optimisation vendors, trading/risk teams | implemented baseline as `monte_carlo` |
| GAN scenario generation | ML-based scenario expansion and stress testing | quant desks, route-to-market analysts, VPP researchers | implemented research baseline as `gan` |
| Tabular RL dispatch baseline | Technical policy baseline for battery assets inside a VPP | research analysts, methodology reviewers | implemented appendix as `rl` |
| Historical settlement backtest | Compare valuation-time schedules with realized settlement cashflows | route-to-market analysts, model validation, risk control | implemented baseline as `backtest` CLI/API |
| Balancing / ancillary services | Prequalified capacity and activation revenue | VPP aggregators, BSPs, C&I DR providers | planned |
| Retail tariff flex | Customer device orchestration for retail and grid value | retailers, utilities, residential VPP platforms | planned |
| Hedged route-to-market | PPA/direct-marketing value plus residual balancing risk | renewables, PPAs, utility desks | planned |
| Network flex / non-wires | Locational flexibility and congestion management | DSOs, utilities, local flex platforms | planned |

## Who Uses What

- Next Kraftwerke markets VPP-based trading and balancing services across
  European power exchanges and TSO areas; this maps to rolling dispatch,
  balancing services, and route-to-market management.
- Statkraft describes a VPP of more than 10 GW and uses it in market access,
  PPAs, and scheduling for renewable generators; this maps to route-to-market,
  rolling dispatch, and cross-market flexibility management.
- Tesla Autobidder and Fluence Mosaic are examples of automated optimisation for
  storage and hybrid assets.  In this repo they map to scenario-based valuation
  and method stress-testing, not to full VPP market participation.
- Enel X operates C&I demand-response VPPs that receive availability and
  activation-style revenues; this maps to balancing/ancillary and interruptible
  load pricing.
- Octopus/KrakenFlex connects EVs, batteries, UPS, heating/cooling systems, and
  C&I/domestic assets for demand flexibility; this maps to retail tariff flex,
  residential VPPs, and grid-scale battery route-to-market.

## Mispricing Risks

| Risk | Where it appears | Economic loss mechanism |
|---|---|---|
| Perfect-foresight bias | Intrinsic benchmark used as executable value | inflated NPV, underpriced guarantees, excessive revenue-share offers |
| Forecast and imbalance risk | Rolling dispatch, renewables, flexible load | imbalance settlement, emergency intraday buys, missed dispatch |
| Tail-price model error | Stochastic merchant bidding | wrong scarcity option value, wrong CVaR, poor collateral planning |
| ML overfitting / mode collapse | GAN scenario generation | generated paths overstate upside, smooth away scarcity, or understate drawdown risk |
| Revenue-stack double counting | Storage and ancillary service optimisation | capacity sold twice, unavailable energy for activation, penalty exposure |
| Non-delivery and baseline error | Demand response and balancing services | penalties, clawbacks, customer disputes, failed prequalification |
| Degradation and warranty error | Batteries and EVs | overcycling, hidden capex replacement cost, warranty breach |
| Telemetry/control/cyber risk | Aggregated fleets | failed dispatch, correlated fleet trip, operational and compliance risk |
| Locational deliverability | Network flexibility and congestion products | paid flexibility cannot relieve the constraint actually priced |
| Retail product leakage | Customer tariffs and smart charging | customers arbitrage tariff rules faster than the aggregator captures grid value |

## Repository Implications

The implemented methods are deliberately treated as stages:

1. `intrinsic` is a benchmark, not an executable business case.
2. `rolling_intrinsic` is the first executable dispatch approximation for
   batteries and flexible loads. It still assumes perfect prices inside the
   look-ahead window and does not model forecast error or intraday liquidity.
   Flexible loads preserve their required total energy; beyond the window the
   implementation enforces feasibility rather than a calibrated terminal value.
3. `monte_carlo` is a stochastic baseline for VPP cashflow optionality and tails.
   Its default full-path dispatch is an upper-bound sensitivity; setting a
   dispatch window applies the same rolling policy inside each simulated path.
4. `gan` is an ML scenario-generation research baseline. It learns normalised
   full-horizon electricity price curves with a small adversarial model, then
   prices the generated paths through the same dispatch and risk engine. It
   requires out-of-sample validation before any generated uplift is treated as
   executable value.
5. `rl` is an implemented appendix for a battery policy only. It is useful for
   comparing a simple state-based policy with the dispatch benchmarks, but it is
   not a VPP-wide orchestration or bidding model.
6. `backtest` is the first historical validation layer. It prices a product with
   valuation-time data, selects a fixed schedule, and settles that schedule on
   realized prices. It is a validation/reporting flow, not a strategy that
   re-optimises on realized prices.
7. Planned extensions should add explicit products, not generic algorithms:
   balancing availability/activation, customer baseline models, hedge/PPA
   shape risk, locational network flexibility, and revenue-stack exclusivity.

Use `vpp-price approaches --json` to inspect the machine-readable taxonomy used
by the code.

## Historical Backtest Result

`examples/run_analyses.py` now runs a synthetic two-product settlement backtest
for `examples/merchant_bess.json` against
`examples/data/historical_products.csv`. The result is intentionally small: it
tests the tradeable analysis plumbing before any claim about calibrated market
performance.

| Metric | Value |
|---|---:|
| Products | 2 |
| Mean valuation E[V] | 4,212 EUR |
| Mean settled cashflow | 3,916 EUR |
| Mean pricing error | -297 EUR |
| Mean absolute error | 627 EUR |
| RMSE | 693 EUR |

Per product:

| Product | Valuation E[V] | Settled cashflow | Error |
|---|---:|---:|---:|
| `day_ahead_2026_01_01` | 3,766 EUR | 2,843 EUR | -923 EUR |
| `day_ahead_2026_01_02` | 4,659 EUR | 4,989 EUR | +330 EUR |

The diagnostic point is that schedule quality is now measurable on a historical
product axis. The current fixture is synthetic and short, so these values
validate the analysis workflow rather than a production trading edge.

## Sources

- DOE, "Pathways to Commercial Liftoff for Virtual Power Plants":
  https://www.energy.gov/edf/articles/doe-releases-new-report-pathways-commercial-liftoff-virtual-power-plants
- RMI, "Virtual Power Plants, Real Benefits":
  https://rmi.org/insight/virtual-power-plants-real-benefits/
- EPEX SPOT, "Basics of the Power Market":
  https://www.epexspot.com/en/basicspowermarket
- FERC, "Order No. 2222 Explainer":
  https://www.ferc.gov/ferc-order-no-2222-explainer-facilitating-participation-electricity-markets-distributed-energy
- Next Kraftwerke, "Balancing Energy via our VPP":
  https://www.next-kraftwerke.com/products/balancing-energy
- Statkraft, "Virtual power plants":
  https://www.statkraft.com/solutions-for-industry/energy-flexibility-management/virtual-power-plants/
- Tesla, "Autobidder":
  https://www.tesla.com/en_GB/support/energy/tesla-software/autobidder
- Tesla, "Tesla Electric":
  https://www.tesla.com/electric
- Fluence, "Mosaic bidding software":
  https://fluenceenergy.com/mosaic-intelligent-bidding-software/
- Centrica Energy, "Battery Energy Storage System":
  https://centricaenergy.com/services/optimisation-flexibility/battery-energy-storage-system/
- Enel X, "Interruptible Load Program":
  https://www.enelx.com/sg/en/demand-response
- Octopus Energy Group, "KrakenFlex":
  https://octopusenergy.group/kraken-flex
- ACER, demand-response balancing prequalification:
  https://acer.europa.eu/news-and-events/news/acer-sees-scope-grid-operators-simplify-their-prequalification-processes-enable-small-scale-demand-response-provide-balancing-services
- NERC, "Distributed Energy Resource Aggregator Security Guideline" draft:
  https://www.nerc.com/globalassets/who-we-are/standing-committees/rstc/0-rstc-agenda-links/20260310_1_13_draft_sites_sg_dera.pdf
