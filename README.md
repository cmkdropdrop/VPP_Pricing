# VPP Pricing Research Toolkit

Forschungs-Framework zum systematischen Vergleich von Bewertungsmethoden fuer Virtual Power Plants (VPPs).

## Motivation

Die Bewertung eines VPP-Portfolios haengt stark von der gewaehlten Methodik ab. Dieses Toolkit implementiert drei gaengige Ansaetze als austauschbare Module und stellt ein Vergleichs-Framework bereit, um die Unterschiede quantitativ zu analysieren.

## Implementierte Pricing-Methoden

| Methode | Beschreibung | Staerken | Grenzen |
|---|---|---|---|
| **Intrinsic Value** | Perfekte Voraussicht ueber den gesamten Lieferzeitraum. Jedes Asset optimiert gegen die vollstaendige Preiskurve. | Obere Schranke, deterministisch, schnell | Ueberschaetzt realisierbaren Wert |
| **Rolling Intrinsic** | Rollierende Optimierung mit begrenztem Vorhersagefenster. Nur die naechsten *n* Stunden sind bekannt, Commit nur fuer die aktuelle Stunde. | Realistischer als Full-Horizon, zeigt Informationsverlust | Innerhalb des Fensters weiterhin perfekte Voraussicht |
| **Monte-Carlo Extrinsic** | Preispfad-Simulation (log-normal um Basiskurve), Dispatch gegen jeden Pfad, Verteilung der Ergebnisse. | Erfasst Optionswert und Streuung, volle Outcome-Distribution | Vereinfachtes Preismodell, rechenintensiver |

## Projektstruktur

```
src/vpp_pricing/
    __init__.py              # Public API
    assets.py                # Asset-Modelle (Solar, Wind, Batterie, Last, Generator)
    market.py                # Marktdaten und CSV-Import
    portfolio.py             # Portfolio-Aggregation
    results.py               # Dispatch- und Ergebnis-Datenstrukturen
    pricing.py               # Legacy-API (delegiert an Intrinsic)
    comparison.py            # Side-by-side Methodenvergleich
    methods/
        __init__.py          # Registry und get_method()
        base.py              # PricingMethod Protocol, PricingResult
        intrinsic.py         # Intrinsic Value
        rolling_intrinsic.py # Rolling Intrinsic
        monte_carlo.py       # Monte-Carlo Extrinsic
tests/
    test_assets.py
    test_pricing.py
examples/
    sample_portfolio.json
    data/
        day_ahead_prices.csv
        scenario_prices.csv
```

## Schnellstart

```bash
# Installation
pip install -e ".[dev]"

# Einzelbewertung (Intrinsic)
vpp-price price examples/sample_portfolio.json examples/data/day_ahead_prices.csv

# Methodenvergleich
vpp-price compare examples/sample_portfolio.json examples/data/scenario_prices.csv \
    --scenario-column scenario \
    --probability-column probability

# Vergleich mit Parametern
vpp-price compare examples/sample_portfolio.json examples/data/scenario_prices.csv \
    --scenario-column scenario \
    --methods intrinsic rolling_intrinsic monte_carlo \
    --window-hours 4 \
    --mc-paths 500 \
    --mc-volatility 0.20 \
    --output runner_outputs/comparison.json

# Tests
pytest
```

## CLI-Befehle

### `vpp-price price`
Klassische Einzelbewertung mit Intrinsic-Methode. Abwaertskompatibel zur vorherigen Version.

### `vpp-price compare`
Fuehrt mehrere Pricing-Methoden gegen dasselbe Portfolio aus und gibt eine Vergleichstabelle aus:

```
========================================================================
  VPP PRICING METHOD COMPARISON -- Demo VPP
========================================================================
  Base scenarios: 3

  Method                   E[V] EUR      CaR EUR     CVaR EUR  RiskAdj EUR
  ----------------------------------------------------------------------
  intrinsic                 1234.56       890.12       845.67      1234.56
  rolling_intrinsic         1180.23       870.45       830.12      1180.23
  monte_carlo               1210.89       780.34       720.56      1210.89

  Delta vs. intrinsic (perfect foresight):
    rolling_intrinsic              -54.33 EUR  (-4.4%)
    monte_carlo                    -23.67 EUR  (-1.9%)
========================================================================
```

## Programmatische Nutzung

```python
from vpp_pricing import (
    VirtualPowerPlant,
    load_market_csv,
    compare_methods,
    IntrinsicPricing,
    RollingIntrinsicPricing,
    MonteCarloPricing,
)

portfolio = VirtualPowerPlant.from_json("examples/sample_portfolio.json")
markets = load_market_csv(
    "examples/data/scenario_prices.csv",
    scenario_column="scenario",
    probability_column="probability",
)

result = compare_methods(
    portfolio,
    markets,
    methods=[
        IntrinsicPricing(),
        RollingIntrinsicPricing(window_hours=4),
        MonteCarloPricing(num_paths=500, volatility=0.20, seed=42),
    ],
    risk_aversion=0.5,
    alpha=0.05,
)

for row in result.summary_table():
    print(f"{row['method']}: E[V]={row['expected_value_eur']:.2f} EUR")
```

## Eigene Pricing-Methode hinzufuegen

Jede Klasse, die das `PricingMethod`-Protocol implementiert, ist kompatibel:

```python
from dataclasses import dataclass
from vpp_pricing.methods.base import PricingMethod, PricingResult
from vpp_pricing.market import MarketData
from vpp_pricing.portfolio import VirtualPowerPlant

@dataclass
class MyCustomPricing:
    @property
    def name(self) -> str:
        return "my_custom"

    def price(
        self,
        portfolio: VirtualPowerPlant,
        markets: list[MarketData],
        *,
        risk_aversion: float = 0.0,
        alpha: float = 0.05,
    ) -> PricingResult:
        # Eigene Bewertungslogik hier
        ...
```

## Modellannahmen

Dieses Toolkit modelliert Energie-Cashflows gegen exogene Preise. Bewusst nicht enthalten (aber als Erweiterung moeglich):

- Netzrestriktionen und Engpassmanagement
- Bilanzkreisabweichungen und Ausgleichsenergie
- Intraday-Liquiditaet und Bid-Ask-Spreads
- Start-/Stoppkosten und Mindeststillstandszeiten
- Regulatorische Abgaben (EEG, Netzentgelte)
- Kalibrierte stochastische Preismodelle (Mean-Reversion, Spruenge)
