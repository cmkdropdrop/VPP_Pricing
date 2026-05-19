# VPP Pricing

Ein kleines Python-Setup, um Virtual Power Plants (VPPs) zu modellieren, Dispatch-Entscheidungen zu simulieren und ein Portfolio gegen Marktpreise zu bepreisen.

Der Fokus liegt auf einem sauberen, erweiterbaren Kern:

- Asset-Modelle fuer Batterie, erneuerbare Erzeugung, flexible Last, fixe Last und dispatchbare Erzeuger
- deterministische Dispatch-Optimierung fuer Batteriespeicher und flexible Lasten
- Portfolio-Aggregation mit Cashflows, Export/Import, Capture Prices und Peak-Metriken
- Szenario-Pricing mit Erwartungswert, 5%-Downside-Quantil und CVaR
- CLI fuer schnelle Reports aus JSON-Portfolio und CSV-Preisen

## Schnellstart

```powershell
$env:PYTHONPATH="src"
python -m vpp_pricing.cli price examples/sample_portfolio.json examples/data/day_ahead_prices.csv --output runner_outputs/vpp_report.json
```

Alternativ nach Installation im Editable-Modus:

```powershell
python -m pip install -e .
vpp-price price examples/sample_portfolio.json examples/data/day_ahead_prices.csv
```

Tests:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

## Datenformate

Portfolio-Dateien sind JSON. Ein Asset hat immer `type` und `name`; weitere Felder haengen vom Asset-Typ ab:

- `renewable`: `capacity_mw` plus `availability` oder `profile_mw`
- `battery`: `capacity_mwh`, `power_mw`, `round_trip_efficiency`, `initial_soc_mwh`
- `flexible_load`: `energy_mwh`, `min_power_mw`, `max_power_mw`
- `fixed_load`: `profile_mw`
- `generator`: `max_power_mw`, `marginal_cost_eur_per_mwh`

Preisdateien sind CSV mit mindestens:

```csv
timestamp,price_eur_per_mwh
2026-01-01T00:00:00Z,52
```

Optional kann eine Spalte `scenario` genutzt werden. Dann erstellt die CLI mehrere Marktszenarien:

```powershell
python -m vpp_pricing.cli price portfolio.json prices.csv --scenario-column scenario
```

## Architektur

- `src/vpp_pricing/assets.py`: Asset-Dispatch-Logik
- `src/vpp_pricing/portfolio.py`: Portfolio-Laden und Aggregation
- `src/vpp_pricing/market.py`: CSV-Marktdaten und Szenarien
- `src/vpp_pricing/pricing.py`: Risiko- und Szenario-Bewertung
- `src/vpp_pricing/cli.py`: Kommandozeileninterface

## Modellannahmen

Dieses Setup ist ein bewusst pragmatisches Basismodell. Es modelliert Energie-Cashflows gegen exogene Preise. Nicht enthalten sind Netzrestriktionen, Bilanzkreisabweichungen, Intraday-Liquiditaet, Redispatch, Garantieprodukte, Nichtlinearitaeten, Startkosten oder regulatorische Abgaben. Diese Punkte koennen spaeter als neue Asset-Klassen, Nebenbedingungen oder Pricing-Layer ergaenzt werden.
