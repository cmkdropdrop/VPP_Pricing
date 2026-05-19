# Literaturvergleich: VPP-, Flexibilitaets- und Speicherbewertung

Dieses Dokument vergleicht die im Repo implementierten Methoden mit
wissenschaftlichen Veroeffentlichungen aus Deutschland bzw. mit direktem
deutschem Strommarktbezug. Der Vergleich ist bewusst methodisch formuliert:
Die Beispielergebnisse in `docs/analysis_results.json` sind synthetische
Szenario-Analysen und keine kalibrierte Backtest-Studie historischer EPEX- oder
Regelleistungsdaten.

## Einordnung der Repo-Ergebnisse

Die folgenden Zahlen stammen aus dem reproduzierbaren Lauf
`PYTHONPATH=src python examples/run_analyses.py`:

| Repo-Fall | Kernergebnis | Vergleichbare Kennzahl |
|---|---:|---|
| Demo VPP | Intrinsic 3,117 EUR/Tag, Rolling 83.6% Capture | Gemischtes Portfolio aus Erneuerbaren, Last, Flex-Last, Generator und Speicher |
| Renewable Hybrid | Intrinsic 15,892 EUR/Tag, Rolling 99.8% | Asset-Mix aus RES und Speicher mit geringer Look-ahead-Suboptimalitaet |
| Summer Renewable Hybrid | Intrinsic 9,033 EUR/Tag, Rolling 96.3% | Duck-curve-artiger Sommertag mit Negativpreis-Exposure |
| Quarter-hourly Portfolio | Rolling 70.7%, MC 109.5% | Sub-hourly-Fensterlaenge hat grossen Einfluss auf Dispatch-Wert |
| Demand Response | Intrinsic -8,512 EUR/Tag, Rolling 84.9% | Lastdominierter VPP-Fall; Capture Ratio ist sign-aware fuer Kostenportfolios |
| Merchant BESS, 100 MWh / 50 MW | Intrinsic 9,213 EUR/Tag | Speicher-Stressfall, ca. 67,257 EUR/MW-Jahr annualisiert, wenn dieser Beispieltag repraesentativ waere |
| Merchant BESS | MC 12,162 EUR/Tag, 132.0% Capture | Sensitivitaet gegen synthetische Pfadvolatilitaet, kein executable uplift |
| RL-Baseline | Batterie-only tabellarisches Q-Learning | Zusatzbaseline fuer eine Flex-Komponente, kein VPP-weites Steuerungsmodell |

Die annualisierte Merchant-BESS-Zahl ist nur eine Skalierung des Speicher-
Stressfalls:

```text
9,213 EUR/day / 50 MW * 365 = 67,257 EUR/MW-year
```

Sie darf nicht als Investment-Case gelesen werden, weil das Beispiel nur wenige
synthetische Szenarien, keine echten 365 Tage, keine Markttiefe, keine CAPEX,
keine Grid Fees und keine Revenue-Stacking-Restriktionen enthaelt.

## Direkter Ergebnisabgleich

| Vergleichsgroesse | Literaturbefund | Repo-Ergebnis | Einordnung |
|---|---|---:|---|
| VPP-Bidding und Portfolio-Koordination | Wozabal/Rameseder sowie Finnah et al. zeigen, dass stochastische, koordinierte DA-/ID-Entscheidungen deterministische Benchmarks schlagen koennen. | Demo VPP und Renewable Hybrid zeigen Portfolio-Cashflows, Asset-Typ-Beitraege und Rolling/MC/GAN-Unterschiede, aber noch keine Gebotskurven. | Das Repo ist bisher Dispatch- und Szenario-Bewertung. Fuer wissenschaftliche Gleichwertigkeit braucht es ein explizites Multi-Market-Bidding-Modul. |
| Erneuerbare VPP-Konfiguration | Candra et al. berichten saisonale Unterschiede und positive sommerliche Day-Ahead-Contribution-Margins fuer geeignete VPP-Konfigurationen. | Summer Renewable Hybrid: 9,033 EUR/Tag Intrinsic, Capture Price 53.93 EUR/MWh, Duck-Curve-/Negativpreis-Exposure. | Richtung und Saisonalitaet passen, die Kennzahl aber nicht: Repo-Cashflow je Export-MWh ist keine produktbezogene Contribution Margin. |
| Risiko-Pooling von RES | Gersema/Wozabal zeigen bessere Risk/Return-Profile durch Technologie-/Standort-Pooling. | Das Repo berichtet Cashflow-Verteilungen, CVaR und Asset-Typ-Diagnostics fuer feste VPP-Portfolios. | Noch keine Optimierung von Portfolio-Gewichten, aber die Diagnoseebene ist jetzt auf Asset-Mix statt Einzel-BESS ausgerichtet. |
| Speicherarbitrage als Flex-Baustein | Metz & Saraiva finden fuer deutsche 15-/60-min-Intraday-Arbitrage, dass historische Arbitrage allein die Investition nicht rechtfertigt. | Merchant BESS Intrinsic: 67,257 EUR/MW-Jahr, wenn der synthetische Beispieltag annualisiert wuerde. | Die Repo-Zahl ist eine obere Dispatch-Schranke ohne CAPEX, Lebensdauer und Markttiefe. Sie darf die Literatur nicht als Profitabilitaetsnachweis ersetzen. |
| State-basierte Speicherpolicy | Finnah et al. nutzen Approximate Dynamic Programming; Loehndorf/Wozabal nutzen Multistage Stochastic Programming fuer koordinierte Maerkte. | `rl` ist nur tabellarisches Q-Learning auf diskreten SOC-/Preis-Bins fuer Batterie-Dispatch. | Die RL-Baseline ist eine Appendix-Methode fuer eine Flex-Komponente, kein VPP-weites Bidding- oder Aggregationsmodell. |
| Hohe Peak-Power-Nutzung bei Arbitrage | Schmidtke beobachtet bei Arbitrage-Betrieb von BESS haeufige Nutzung von 95-100% der Peak Power. | Merchant BESS entlaedt in Scarcity-/Spread-Stunden am 50-MW-Leistungslimit. | Qualitativ konsistent; fuer wissenschaftliche Gleichwertigkeit fehlen FCR, Multi-Use-Regeln und lokale Netzrestriktionen. |

## Vergleichsmatrix

| Quelle | Markt-/Asset-Fokus | Relevante Aussage | Vergleich mit Repo |
|---|---|---|---|
| Wozabal & Rameseder (TUM, 2020), *European Journal of Operational Research* | VPP-Bidding auf Day-Ahead und mehreren Intraday-Auktionen | Stochastic Programming/MDP fuer VPPs mit Preis- und Windunsicherheit; die optimale stochastische Policy outperformt deterministische Planung und reine Day-Ahead-Benchmarks. | Unser VPP-Vergleich enthaelt Intrinsic, Rolling und MC/GAN-Szenarien, aber keine Gebotskurven und keine Out-of-sample Policy-Auswertung. Die methodische Konsequenz ist klar: naechster Schritt waere ein explizites Bidding-Modul statt reiner Dispatch-Bewertung. |
| Gersema & Wozabal (TUM, 2018), *Journal of Banking and Finance* | Risikoptimiertes Pooling von PV/Wind im deutschen VPP-Kontext | Optimale Technologie-/Standort-Pools haben ein klar besseres Risk/Return-Profil als Marktportfolios; Technologie-Diversifikation reduziert Risiko. | Das Repo zeigt Risk-Metriken je Portfolio, optimiert aber noch keine Portfolio-Gewichte. Die Renewable-Hybrid-Beispiele liefern einen Ausgangspunkt, aber kein wissenschaftlich gleichwertiges Pooling-Ergebnis. |
| Candra, Hartmann & Nelles (Rostock/Aschaffenburg/DBFZ, 2018), *Energies* | Wirtschaftliche VPP-Konfiguration im deutschen Power Market, PV/BESS/Biogas | Sommerliche Day-Ahead-Konfigurationen koennen positive Contribution Margins bis ca. 14 EUR/MWh erreichen; Winter- und Futures-Faelle bleiben oft negativ, teils bis ca. -105 EUR/MWh. | Unser Summer Renewable Hybrid ist positiv (9,033 EUR/Tag Intrinsic), aber nicht direkt vergleichbar: keine Biogas-Sicherungsleistung, keine Produkt-CM-Rechnung, kein Futures-Markt. Die Richtung stimmt: Saison und Asset-Mix treiben die Wirtschaftlichkeit stark. |
| Hirsch & Ziel (2024), *The Energy Journal* | Simulation-based Forecasting fuer deutschen Intraday-Markt | Intraday-Verteilung sollte Location, Scale und Shape modellieren; Tails werden besser, wenn Merit-Order-Regime, Time-to-delivery und Handelsaktivitaet beruecksichtigt werden. | Unser displaced-lognormaler AR(1)-MC-Prozess ist wissenschaftlich sauberer als ein Modellwechsel an der Nullpreisgrenze, aber weiterhin stilisiert. Die neu ergaenzten Bias-/RMSE- und Tail-Support-Diagnostiken sind Mindestkontrollen, kein Ersatz fuer GAMLSS-/Orderbuch-Kalibrierung. |
| Finnah, Goensch & Ziel (University of Duisburg-Essen, 2022), *European Journal of Operational Research* | Integriertes Day-Ahead-/Intraday-Self-Schedule-Bidding fuer Speicher in Deutschland | ADP fuer hochdimensionale Preisprognosen; integriertes Trading in beiden Auktionsmaerkten uebertrifft Einzelmarkt- und sequentielle Optimierung; Receding-Horizon-Erwartungsmodell ist ein starker Benchmark. | Relevant als naechste methodische Stufe fuer flexible Assets im VPP. Unser `rolling_intrinsic` ist nur ein Dispatch-Benchmark ohne Gebotsentscheidungen. |
| Loehndorf & Wozabal (TUM, 2023), *Operations Research* | Koordiniertes Multi-Market-Bidding fuer Speicher | Multistage Stochastic Programming mit DA-Auktion und kontinuierlichem Intraday; koordinierte Kapazitaetsreservierung ist besonders wertvoll bei hoher Intraday-Volatilitaet, Liquiditaet und Price Impact. | Relevant fuer VPPs mit speicherbarer Flexibilitaet. Unser MC-Uplift ist Volatilitaetssensitivitaet, kein Ersatz fuer Coordination Value. |
| Finhold, Heller & Leithaeuser (Fraunhofer ITWM, 2023), *Journal of Energy Markets* | Deutscher kontinuierlicher Intraday-Markt, 15-min Produkte, Orderbuch-Arbitrage | Ex-post Perfect Foresight erzeugt im 2020-2022 Datensatz im Mittel mehr als das Fuenffache des Pair-Trading-Gewinns; haeufigere Optimierung erhoeht Ex-post-Gewinne um ca. 25-40%. | Unser Rolling-vs-Intrinsic-Gap ist preiszeitreihenorientiert und ohne Orderbuch-Mikrostruktur. Die Aussage ist methodisch, nicht als Real-Trading-Ergebnis zu lesen. |
| Metz & Saraiva (2018), *Electric Power Systems Research* | Batteriespeicher-Arbitrage in deutschen 15- und 60-Minuten-Intraday-Auktionen | MIP-Dispatch mit 15-min Zeitschritten, negative Preise, parallele Maerkte und Zyklus-/Kalenderlebensdauer; historische Arbitrage allein reicht nach ihren Ergebnissen nicht zur Rechtfertigung der Investition. | Unser Batterie-DP ist fuer Energiearbitrage konsistent, aber einfacher. Die Speicherfaelle sind Stress-Tests fuer Flexibilitaet, kein zentraler Investment-Case. |
| Tabular RL-Baseline im Repo | Batterie-Dispatch auf diskreten Szenarien | Q-Learning kann eine einfache zustandsbasierte Policy als Vergleichspunkt liefern. | Methodischer Appendix: kein ADP mit reichhaltigem Forecast-State, kein Multistage Stochastic Programming, keine Marktkoordination und keine Gebotskurven. |
| Schmidtke (RWTH Aachen, 2025), Dissertation | Multi-Use-Betrieb von BESS, u.a. aggregierte Kleinspeicher im VPP | Arbitrage-fokussierter Betrieb nutzt Leistung haeufig im Bereich 95-100%; Multi-Use glattet Leistungsnutzung, FCR kann Erloese erhoehen, VPP-Synchronitaet kann lokale Netzlastspitzen verstaerken. | Unser Merchant BESS nutzt die volle 50-MW-Leistung in Scarcity-/Arbitragephasen und bestaetigt qualitativ die hohe Peak-Power-Nutzung. Das Repo bildet aber Netzrestriktionen, FCR und lokale Synchronitaetsrisiken noch nicht ab. |

## Ergebnisvergleich: Was ist belastbar?

**Belastbar vergleichbar**

- Perfect-Foresight-Intrinsic als obere Schranke: Die Fraunhofer- und
  TUM-Arbeiten nutzen ebenfalls ex-post bzw. obere Bounds als Referenz, machen
  aber deutlich, dass diese nicht executable sind.
- Rolling/Receding Horizon als operativer Benchmark: Das Repo trifft hier den
  methodischen Kern der Literatur, ist aber in Marktstruktur und Forecast-State
  einfacher.
- Tail-Risiko und CVaR: Die Repo-Risk-Engine passt zu risk-aversen
  Stochastic-Programming-Ansaetzen, aber die empirische Tail-Stichprobe ist klein
  und wird jetzt explizit ausgewiesen.

**Nur qualitativ vergleichbar**

- Absolute Arbitrage-Erloese: Publikationen nutzen historische EPEX-/Orderbuch-
  Daten, ganze Jahre und konkrete Marktprodukte; das Repo nutzt synthetische
  Beispielkurven.
- Multi-Market Coordination Value: Die Literatur optimiert DA/ID gemeinsam;
  das Repo bewertet bisher eine Preisbahn je Szenario.
- VPP-Pooling und Diversifikation: Das Repo vergleicht feste Portfolios, optimiert
  aber keine Gewichtung von Assets, Standorten oder Technologien.
- Revenue stacking: FCR/aFRR, Netzflexibilitaet und Exklusivitaetsregeln fehlen
  derzeit.

## Konkrete methodische Anschlussarbeiten

1. **Historischer deutscher Backtest**
   EPEX Day-Ahead, Intraday Auction und Continuous Intraday laden und die
   Beispielportfolios auf echte 2020-2025-Zeitreihen anwenden.

2. **DA/ID-Multi-Market-Modul**
   Separate Preisprozesse, Gebotsentscheidungen und Kapazitaetsreservierung
   einfuehren. Das wuerde die Luecke zu Finnah et al. und Loehndorf/Wozabal
   schliessen.

3. **Forecast-State statt Perfect-Foresight-Fenster**
   Rolling Intrinsic um Prognosefehler und Forecast-Updates erweitern. Hirsch &
   Ziel liefern dafuer die relevante Preisprozess-Perspektive.

4. **Portfolio-Pooling-Optimierung**
   Asset-Gewichte nach Erwartungswert/CVaR optimieren, um Gersema/Wozabal
   methodisch direkt nachzubilden.

5. **Revenue-Stacking und Netzrestriktionen**
   FCR/aFRR, lokale Netzkapazitaeten, Transformer Loading und Produkt-
   Exklusivitaeten modellieren; das adressiert die RWTH-Multi-Use-Ergebnisse.

## Quellen

- Candra, Hartmann & Nelles (2018): [Economic Optimal Implementation of Virtual Power Plants in the German Power Market](https://www.mdpi.com/1996-1073/11/9/2365)
- Finnah, Goensch & Ziel (2022): [Integrated day-ahead and intraday self-schedule bidding for energy storage systems using approximate dynamic programming](https://www.sciencedirect.com/science/article/pii/S0377221721009565)
- Finhold, Heller & Leithaeuser (2023): [On the potential of arbitrage trading on the German intraday power market](https://www.itwm.fraunhofer.de/content/dam/itwm/de/documents/anwendungsfelder/202309012_On%20the%20potential%20of%20arbitrage%20trading%20on%20the_Leithaeuser%20et%20al.pdf)
- Gersema & Wozabal (2018): [Risk-optimized pooling of intermittent renewable energy sources](https://portal.fis.tum.de/en/publications/risk-optimized-pooling-of-intermittent-renewable-energy-sources/)
- Hirsch & Ziel (2024): [Simulation-based Forecasting for Intraday Power Markets](https://journals.sagepub.com/doi/10.5547/01956574.45.3.shir)
- Loehndorf & Wozabal (2023): [The Value of Coordination in Multimarket Bidding of Grid Energy Storage](https://portal.fis.tum.de/de/publications/the-value-of-coordination-in-multimarket-bidding-of-grid-energy-s/)
- Metz & Saraiva (2018): [Use of battery storage systems for price arbitrage operations in the 15- and 60-min German intraday markets](https://www.sciencedirect.com/science/article/pii/S0378779618300282)
- Schmidtke (2025): [Evaluating multi-use operation of battery energy storage systems in a cyber-physical energy system testbed](https://publications.rwth-aachen.de/record/1020343)
- Wozabal & Rameseder (2020): [Optimal bidding of a virtual power plant on the Spanish day-ahead and intraday market for electricity](https://portal.fis.tum.de/de/publications/optimal-bidding-of-a-virtual-power-plant-on-the-spanish-day-ahead/)
