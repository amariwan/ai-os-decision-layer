# No-Match Safety Review (read-only)

## Entscheidungspfade (VERIFIED, `src/ai_os_decision/`)
Kette: Policy pre-check → Engine (laya/rule) → Confidence-Gate (`config.yaml`: auto_execute 0.90 / verify 0.70) → Safe Fallback (`DeterministicFallback`, rule-basiert, fail-closed bei Risiko). **Kein Pfad enthält eine No-Match-Frage** — bei unpassenden Optionen wird immer eine gewählt (Laya-`choice` per Konstruktion; Benchmark: forced-predict überall).

## Offizielle Abstentions-Mechanismen (alle bereits evaluiert)
- **Aurelio:** einziger nativer `None`-Abstain (12/12 No-Match bei Defaults; forced-choice 0.639). Nicht im Decision-Layer verdrahtet (lief nur im verlorenen /tmp-Venv) → für Prod-Pfad UNVERIFIED.
- **Laya:** `act_probability` konstant 1.0; Confidence invertiert (0.21 korrekt vs 0.34 falsch) → als Gate **kontraproduktiv**. `min_confidence`-Helfer existieren upstream, ändern nichts an fehlender No-Match-Semantik.
- **EmbeddingGemma-Score:** schwaches aber reales Signal (t≈0.30: Prec 0.78/Rec 0.58) — kein offizieller Mechanismus, nur Schwellwert-Policy.
- **ToolHive/no-registry:** Absence-String, keine Entscheidung.

## Risiko (wo Fehlwahl droht)
Überall, wo `choice`-Fragen ohne "none-of-the-above"-Pfad gestellt werden: Skill-/Tool-/Modell-/Workflow-Auswahl im Decision Layer und in allen vier Clients (kein Client erzwingt Discovery-vor-Antwort). Höchste Exposition: Modell- und Skill-Routing (Laya dort am schwächsten: 0.300 bzw. 0.531).

## Config-only Empfehlungen (priorisiert, NICHT implementiert — Freigabe nötig)
1. Laya-Antworten default auf `verify` routen (Gate so konfigurieren, dass `auto_execute` für Laya-Quellen nie greift) — reine Config-Änderung, schärfste Wirkung.
2. `verify`-Schwelle für Choice-Fragen anheben, bis Temperatur-Refit auf Echtdaten vorliegt.
3. Destruktive/risikobehaftete Aktionen dauerhaft auf deterministische Fallbacks zwingen (fail-closed bereits vorhanden — als Config-Policy explizit festschreiben).
4. Kein neues Routing, keine Schwellen-Logik, keine Adapter — alles obige ist Konfiguration bestehender Knöpfe.
