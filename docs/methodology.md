# Methodik und wissenschaftliche Annahmen

Dieses Dokument beschreibt die mathematischen Definitionen, die in den
implementierten Methoden gelten. Ziel ist nicht, Marktmodelle als produktionsreif
zu verkaufen, sondern ihre Annahmen, Schaetzfehler und Interpretationsgrenzen
offen zu legen.

Der Abgleich mit wissenschaftlichen Arbeiten zu deutschen VPP-, Speicher- und
Intraday-Fragestellungen steht in `docs/literature_comparison.md`.

## Bewertungsobjekt

Ein Portfolio wird gegen eine Menge diskreter Preisszenarien bewertet:

- Szenarien `s = 1..S` haben normalisierte Wahrscheinlichkeiten `p_s`.
- Jedes Szenario hat dieselbe Zeitachse `t = 1..T` und Intervalllaenge `dt`.
- Preise sind `P_{s,t}` in `EUR/MWh`.
- Asset-Dispatch ist `q_{a,s,t}` in MW. Positive Werte exportieren, negative
  Werte importieren aus Portfoliosicht.

Der szenarioweise Cashflow ist:

```text
V_s = sum_t sum_a cashflow(a, s, t)
```

Der erwartete Wert ist:

```text
E[V] = sum_s p_s V_s
```

## Risikomasse

Das Toolkit nutzt eine gewichtete empirische Cashflow-Verteilung.

Cashflow-at-Risk bei Tail-Level `alpha` ist das linke gewichtete Quantil:

```text
CaR_alpha = inf {x : F_V(x) >= alpha}
```

Conditional Value-at-Risk ist der Erwartungswert der unteren `alpha`-Tailmasse
mit fractional boundary mass. Wenn das schlechteste Szenario bereits mehr
Wahrscheinlichkeit als `alpha` hat, entspricht CVaR diesem Szenariowert.

```text
CVaR_alpha = E[V | V in lower alpha tail]
```

Die Risk-Engine berichtet zusaetzlich:

- Kish effective sample size: `1 / sum_i p_i^2`
- effektive Stichprobengroesse in der unteren Tailmasse
- Tail-Wahrscheinlichkeitsmasse, die fuer CaR/CVaR genutzt wurde

Diese Werte sind wichtig, weil CVaR aus wenigen Szenarien numerisch korrekt,
aber statistisch grob sein kann.

## Intrinsic

Intrinsic ist ein deterministischer Perfect-Foresight-Benchmark. Jedes flexible
Asset sieht die komplette Preiskurve des Szenarios und optimiert ueber den
vollen Horizont. Das ist eine obere Schranke fuer ideale Energiearbitrage, aber
keine ausfuehrbare Handelsstrategie.

Wissenschaftliche Interpretation:

- geeignet als Benchmark fuer Opportunitaetskosten und theoretische Dispatch-
  Obergrenzen,
- ungeeignet als alleinige Prognose realisierbarer Trading-Erloese,
- sensitiv gegen Terminal-SOC, Degradation, Curtailment und Preiszeitreihe.

## Rolling Intrinsic

Rolling Intrinsic optimiert Batterien und flexible Lasten mit einem
receding-horizon Fenster. Bei jedem Zeitschritt wird ueber die naechsten
`window_hours` optimiert, aber nur die erste Entscheidung committed.

Wichtig: Das ist kein Forecast-Error-Modell. Innerhalb des Fensters sind Preise
weiterhin perfekt bekannt. Die Methode misst vor allem den Wertverlust durch
begrenzten Look-ahead und terminale Myopie.

## Monte Carlo

Monte Carlo generiert synthetische Preisbahnen um die gewichteten
Basisszenarien. Der Preisprozess ist ein displaced-lognormal AR(1)-Modell:

```text
X_t = rho X_{t-1} + eps_t
eps_t ~ N(0, sigma^2 dt)
Var[X_t] = sigma^2 dt * (1 - rho^(2t)) / (1 - rho^2)
M_t = exp(X_t - 0.5 Var[X_t])
P_sim,t = (P_base,t + shift) M_t - shift
```

`shift` wird je Basisszenario so gewaehlt, dass alle verschobenen Preise positiv
sind und mindestens `price_floor_eur_per_mwh` betragen. Dadurch werden
positive, nullnahe und negative Strompreise mit demselben Modell behandelt.
Wegen der Driftkorrektur gilt je Zeitschritt:

```text
E[P_sim,t] = P_base,t
```

Die Pfadanzahl wird proportional zu den Basisszenario-Wahrscheinlichkeiten
alloziert; jeder synthetische Pfad erbt `p_base / path_count` als Gewicht.

Diagnostisch werden gemeldet:

- empirischer Bias der simulierten mittleren Preiskurve gegen die Basiskurve,
- RMSE und maximaler Preis-Bias,
- verwendete Preis-Displacements je Basisszenario,
- Cashflow-Tail-Support und effektive Stichprobengroesse.

Grenzen:

- keine kalibrierten Jumps, Spikes, Regimewechsel oder Cross-Market-Korrelation,
- Default-Dispatch ist perfect foresight je synthetischem Pfad,
- MC-Uplift gegen Intrinsic ist eine Sensitivitaet, kein automatisch
  ausfuehrbarer Extrinsic Value.

## GAN-Szenariogenerator

Der GAN-Ansatz ist bewusst als dependency-freie Forschungsbaseline formuliert.
Er lernt normalisierte Vollhorizont-Preisvektoren und generiert synthetische
Kurven. Er ist kein Ersatz fuer ein validiertes Deep-Learning-Preismodell.

Zur wissenschaftlichen Kontrolle werden neben Trainingsverlusten auch
Kalibrierungsdiagnostiken berichtet:

- mittlerer Kurvenfehler und RMSE gegen die gewichtete Trainingskurve,
- Verhaeltnis generierter zu empirischer Schritt-Volatilitaet,
- Fehler in der Negativpreis-Haeufigkeit,
- paarweise Kurvendiversitaet gegen die Trainingsdaten,
- Preisrange-Abdeckung.

Vergleichsberichte warnen bei kleiner Trainingsmenge, low diversity, starkem
Volatilitaets-Mismatch oder perfect-foresight Dispatch auf generierten Pfaden.

## Batterie-Dispatch

Batterien werden ueber ein diskretes State-of-Charge-Gitter optimiert. Lade- und
Entladeeffizienz werden symmetrisch als Quadratwurzel der Round-trip Efficiency
modelliert. Leistungslimits gelten auf Grid-Seite:

```text
charge_grid_mwh <= power_mw * dt
discharge_grid_mwh <= power_mw * dt
```

Cycle Costs werden auf Grid-seitigen Durchsatz angewendet. Die ausgewiesenen
Equivalent Cycles nutzen:

```text
cycles = throughput_mwh / (2 * capacity_mwh)
```

Bei grobem `grid_points`-Gitter ist der Wert nur eine diskrete Approximation.

## Grenzen des aktuellen Forschungsmodells

- Keine Netzrestriktionen und keine gemeinsamen Anschlusskapazitaeten ueber
  Assets.
- Keine expliziten Intraday-Bid-Ask-Spreads, Marktliquiditaet oder Fill-Risiken.
- Keine Forecast-Error-Verteilung im Rolling Dispatch.
- Keine Revenue-Stacking-Exklusivitaeten ueber Energie, Regelenergie und
  Flexibilitaetsprodukte.
- Keine nichtlineare Batterie-Degradation oder Calendar Aging.
- Keine kalibrierte Out-of-sample Validierung historischer Preisregime.
