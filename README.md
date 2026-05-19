# VPP Pricing Research Toolkit

Forschungs-Framework zum systematischen Vergleich von Bewertungsmethoden fuer Virtual Power Plants (VPPs).

## Motivation

Die Bewertung eines VPP-Portfolios haengt stark davon ab, welcher reale
Erlosstrom gepreist wird: Spot-/Intraday-Arbitrage, Bilanzkreisoptimierung,
Regelenergie, Demand Response, Retail-Tarife, PPA/Route-to-Market oder lokale
Netzflexibilitaet. Dieses Toolkit stellt deshalb erst die praxisnahen
Pricing-Archetypen in den Mittelpunkt und ordnet die implementierten Methoden
diesen Archetypen zu.

Siehe auch: `docs/practical_vpp_pricing.md`.

## Praxis-Archetypen

| Archetyp | Oekonomische Rolle | Typische Nutzer | Repo-Status |
|---|---|---|---|
| Intrinsic Benchmark | Obere Schranke und Opportunitaetskosten | Asset Owner, Analysten, Kreditgeber | `intrinsic` |
| Rolling Forecast Dispatch | Ausfuehrbare Intraday-/Bilanzkreisoptimierung | Aggregatoren, BRPs, Batteriespeichervermarkter | `rolling_intrinsic` |
| Stochastic Merchant Bidding | Probabilistische Merchant- und Tail-Bewertung | Storage-Owner, Optimierer, Trading Desks | `monte_carlo` |
| Balancing / Ancillary Services | Praequalifizierte Leistung plus Aktivierung | BSPs, C&I-DR, VPP-Aggregatoren | geplant |
| Retail Tariff Flex | Kundengeraete fuer Retail- und Netzflexibilitaet | Retailer, Utilities, Residential-VPPs | geplant |
| Hedged Route-to-Market | PPA-/Direktvermarktung plus Rest-Bilanzrisiko | Erneuerbare, PPAs, Utility Desks | geplant |
| Network Flex / Non-Wires | Lokale Flexibilitaet gegen Netzengpaesse | DSOs, Utilities, lokale Flex-Plattformen | geplant |

## Implementierte Pricing-Methoden

| Methode | Beschreibung | Staerken | Grenzen |
|---|---|---|---|
| **Intrinsic Value** | Perfekte Voraussicht ueber den gesamten Lieferzeitraum. Jedes Asset optimiert gegen die vollstaendige Preiskurve. | Obere Schranke, deterministisch, schnell | Keine executable Trading-Strategie |
| **Rolling Intrinsic** | Rollierende Optimierung mit begrenztem Vorhersagefenster. Batterien werden je Fenster per dynamischem Programm optimiert, Commit nur fuer die aktuelle Stunde. | Naeher an operativer Bilanzkreis-/Intraday-Praxis | Innerhalb des Fensters weiterhin perfekte Voraussicht |
| **Monte-Carlo Extrinsic** | Preispfad-Simulation um Basiskurven, Dispatch gegen jeden Pfad, gewichtete Ergebnisverteilung. | Erfasst Optionswert, Tail-Risiko und Streuung | Noch kein vollstaendiges Multi-Market-Bidding |

## Projektstruktur

```
src/vpp_pricing/
    __init__.py              # Public API
    assets.py                # Asset-Modelle (Solar, Wind, Batterie, Last, Generator)
    market.py                # Marktdaten und CSV-Import
    portfolio.py             # Portfolio-Aggregation
    practical.py             # Praxis-Archetypen, Nutzergruppen, Mispricing-Risiken
    results.py               # Dispatch- und Ergebnis-Datenstrukturen
    risk.py                  # Gewichtete Erwartungs-, CaR-, CVaR- und Streuungsmetriken
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
    test_practical.py
docs/
    practical_vpp_pricing.md
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

# Praxis-Archetypen und Mispricing-Risiken anzeigen
vpp-price approaches --json

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

  Method                     E[V] EUR    Std EUR      CaR EUR     CVaR EUR  RiskAdj EUR
  ----------------------------------------------------------------------------------
  intrinsic                   2916.74    1267.50      1720.79      1720.79      2916.74
  rolling_intrinsic           2912.07    1270.28      1713.48      1713.48      2912.07
  monte_carlo                 3061.32    1258.60      1690.05      1416.40      3061.32

  Delta vs. intrinsic (perfect foresight):
    rolling_intrinsic             -4.67 EUR  (-0.2%)
    monte_carlo                 +144.58 EUR  (+5.0%)
========================================================================
```

### `vpp-price approaches`
Listet die praxisnahen Pricing-Archetypen mit Status. Mit `--json` werden
Nutzergruppen, Erlosstroeme, Maerkte, Beispielnutzer und Mispricing-Risiken
maschinenlesbar ausgegeben.

## Quantitative Methodik

- Alle Methoden nutzen dieselbe gewichtete Risk-Engine fuer Erwartungswert, Standardabweichung, CaR und CVaR.
- Szenariowahrscheinlichkeiten werden normalisiert; wenn alle Gewichte null sind, wird gleichgewichtet.
- Monte Carlo verteilt die Pfadanzahl proportional auf die Basisszenarien und erbt deren Wahrscheinlichkeiten.
- Marktdaten werden auf endliche Preise, konsistente Szenario-Wahrscheinlichkeiten und vergleichbare Zeitachsen geprueft.

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
    print(
        f"{row['method']} ({row['practical_approach']}): "
        f"E[V]={row['expected_value_eur']:.2f} EUR"
    )
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

- Explizite Regelenergieprodukte mit Verfuegbarkeits- und Aktivierungserloesen
- Netzrestriktionen, lokale Flexibilitaet und Engpassmanagement
- Bilanzkreisabweichungen, Ausgleichsenergie und Penalty-Mechaniken
- Intraday-Liquiditaet, Bid-Ask-Spreads und Orderbuch-Ausfuehrung
- Start-/Stoppkosten und Mindeststillstandszeiten
- PPA-/Hedge-Strukturen, Shape Risk und Collateral
- Demand-Response-Baselines, Opt-outs, Rebound und Kundennutzen
- Regulatorische Abgaben (EEG, Netzentgelte)
- Kalibrierte stochastische Preismodelle (Mean-Reversion, Spruenge)
