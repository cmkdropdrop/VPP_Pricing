# Eingabevertrag fuer VPP-Bewertungen

Dieses Dokument beschreibt die Eingaben, die das Toolkit als belastbare
Bewertungsbasis erwartet. Es ist bewusst enger als ein beliebiges Demo-JSON:
Portfolios und Marktdaten sollen vor dem Pricing mit `vpp-price validate`
geprueft werden.

## Vorzeichen und Einheiten

- Leistung ist aus Portfoliosicht definiert: positive MW sind Export/Einspeisung,
  negative MW sind Import/Verbrauch.
- Preise sind in `EUR/MWh`.
- Cashflows sind positiv, wenn das Portfolio Geld verdient, und negativ, wenn es
  Energie oder Flexibilitaet einkauft.
- `timestep_hours` beschreibt die Dauer eines Intervalls. Beispiel: 1.0 fuer
  Stundenwerte, 0.25 fuer 15-Minuten-Werte.
- Energie ergibt sich aus `power_mw * timestep_hours`.

## Market CSV

Pflichtspalten:

| Spalte | Bedeutung |
|---|---|
| `timestamp` | Zeitindex je Intervall. Muss ueber Szenarien identisch sein. |
| `price_eur_per_mwh` | Strompreis je Intervall. Muss endlich numerisch sein. |

Optionale Spalten:

| Spalte | Bedeutung |
|---|---|
| `scenario` | Szenarioname. Zeilen mit gleichem Namen bilden eine Preisbahn. |
| `probability` | Szenariogewicht. Innerhalb eines Szenarios muss es konstant sein. |

Wenn Wahrscheinlichkeiten nicht auf 1.0 summieren, werden sie fuer die
Risikometriken normalisiert. Wenn alle Gewichte null sind, wird gleichgewichtet.

## Portfolio JSON

Root-Objekt:

```json
{
  "name": "Portfolio name",
  "assets": []
}
```

Jedes Asset braucht `type` und `name`. Nicht unterstuetzte Felder werden beim
Laden abgewiesen, damit Tippfehler nicht stillschweigend ignoriert werden.

### `renewable`

| Feld | Typ | Bedeutung |
|---|---|---|
| `capacity_mw` | number | Installierte Leistung. |
| `availability` | number oder list | Verfuegbarkeit 0..1 je Intervall. |
| `profile_mw` | number oder list | Optionales Leistungsprofil in MW. Ueberschreibt `availability`. |
| `variable_om_eur_per_mwh` | number | Variable Kosten je erzeugter MWh. |
| `curtail_below_price_eur_per_mwh` | number/null | Optionaler Preis, unter dem abgeregelt wird. |

### `battery`

| Feld | Typ | Bedeutung |
|---|---|---|
| `capacity_mwh` | number | Energieinhalt. Muss positiv sein. |
| `power_mw` | number | Lade-/Entladeleistung. |
| `round_trip_efficiency` | number | Round-trip-Wirkungsgrad in `(0, 1]`. |
| `initial_soc_mwh` | number | Start-SOC. |
| `terminal_soc_mwh` | number/null | Ziel-SOC. Default ist Start-SOC. |
| `cycle_cost_eur_per_mwh` | number | Durchsatzkosten fuer Degradation/Warranty. |
| `grid_points` | integer | SOC-Gitter fuer die dynamische Optimierung. |

### `fixed_load`

| Feld | Typ | Bedeutung |
|---|---|---|
| `profile_mw` | number oder list | Verbrauchsprofil in MW. Positive Werte werden als Import modelliert. |

### `flexible_load`

| Feld | Typ | Bedeutung |
|---|---|---|
| `energy_mwh` | number | Gesamtenergie ueber den Horizont. |
| `min_power_mw` | number | Mindestverbrauch je Intervall. |
| `max_power_mw` | number | Maximalverbrauch je Intervall. |
| `value_eur_per_mwh` | number | Nutzwert je verbrauchter MWh. |

### `generator`

| Feld | Typ | Bedeutung |
|---|---|---|
| `max_power_mw` | number | Maximale Einspeiseleistung. |
| `marginal_cost_eur_per_mwh` | number | Grenzkosten. |
| `min_margin_eur_per_mwh` | number | Mindestmarge ueber Grenzkosten. |

## Vor dem Pricing validieren

```bash
vpp-price validate examples/merchant_bess.json examples/data/extended_scenarios.csv \
    --scenario-column scenario \
    --probability-column probability
```

Die Validierung prueft unter anderem:

- identische Zeitachsen und Timesteps ueber Szenarien,
- sinnvolle Szenariowahrscheinlichkeiten,
- unbekannte Asset-Felder und numerische Profilwerte,
- Dispatch-Feasibility je Szenario,
- Warnungen zu Single-Szenario-Risiko, fehlenden Batterie-Cycle-Costs,
  geringer SOC-Gitteraufloesung und Erneuerbaren-Export bei Negativpreisen.
