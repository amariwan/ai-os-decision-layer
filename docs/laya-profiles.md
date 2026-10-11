# Sechs lokale Laya-Profile

Die Profile erweitern das bestehende AI-OS um strukturierte Empfehlungen.
Sie führen keine Tools aus, starten keinen autonomen Loop und schreiben keine
Brain-Daten. Bestehende Task-Routen bleiben unverändert. Andere Clients müssen
diesen Einstieg ausdrücklich aufrufen; es gibt keinen globalen Tool-Interceptor.

## Aufruf

Aus `/Users/snow/dev/ai-os/decision-layer`:

```sh
uv run --no-sync ai-os recommend model-routing examples/recommendations/model-routing.json --require-laya
uv run --no-sync ai-os recommend tool-risk examples/recommendations/tool-risk.json --require-laya
uv run --no-sync ai-os recommend intent-domain examples/recommendations/intent-domain.json --require-laya
uv run --no-sync ai-os recommend loop examples/recommendations/loop.json --require-laya
uv run --no-sync ai-os recommend rag-rerank examples/recommendations/rag-rerank.json --require-laya
uv run --no-sync ai-os recommend guardrails examples/recommendations/guardrails.json --require-laya
```

`--config`, `--model-dir` und `--timeout-ms` folgen `ai-os task`.
Explizite Konfiguration hat Vorrang vor `config.local.yaml`, dann `config.yaml`.
Eine explizite Policy ist erforderlich. Lokale Inferenz benötigt bei diesem
Checkpoint derzeit ungefähr 20 Sekunden einschließlich Laden; die vorhandene
lokale Konfiguration verwendet deshalb 60000 ms. Es werden keine Modelle oder
Abhängigkeiten heruntergeladen.

Bibliothek: `recommend(profile, request, runtime)` in
`ai_os_decision.recommendations`; `runtime` ist der vorhandene `ShadowRuntime`.
Sie verwendet dieselben Eingabeprüfungen und deterministischen Grenzen wie CLI.

## Anfrage und Ausgabe

Anfragen verwenden exakt `schema`, `text`, `environment`, `context`.
Schema ist `ai-os-recommendation-request/v1`. Vollständige synthetische Beispiele
stehen unter `examples/recommendations/`; die dortigen Modellnamen und Rechte
sind Beispieldaten, kein Betriebsinventar.

| Profil | Context-Felder | Modellantwort / Grenze |
|---|---|---|
| model-routing | candidates, local_only, budget | Wahl ausschließlich aus verfügbaren, fähigen, budgetkonformen Kandidaten |
| tool-risk | tool_id, action, arguments, permitted | low/medium/high/critical; fehlendes Host-Recht sperrt, jede Schreibaktion verlangt Prüfung |
| intent-domain | intents, domains | Jeweils vorgegebene Labels einschließlich unknown |
| loop | iteration, max_iterations, elapsed_seconds, timeout_seconds, cost, budget, goal_complete, verification_pending | continue/verify/replan/stop; Limits erzwingen Stop, offene Prüfung Verify |
| rag-rerank | query, candidates mit id/source/excerpt | Scores 0..4, stabile Sortierung, Quellenverweise bleiben erhalten |
| guardrails | content, origin | no_issue_detected/suspicious/policy_sensitive/unknown; Auffälligkeit oder Unsicherheit verlangt Prüfung |

Ausgaben verwenden `ai-os-recommendation/v1` und enthalten Status, Decision-ID,
Policy, Empfehlung, `execution_enabled: false` und Laya-Metadaten.
`laya.observation` enthält nur vollständig validierte Antworten. Keine
Konfidenzschwelle schaltet eine Aktion frei.

Exitcodes: 0 für eine verwertbare Empfehlung; 2 für Deny, Review oder ungültige
Eingabe/Konfiguration; 3 bei sonst verwertbarem Fallback mit `--require-laya`.
Code 2 hat Vorrang. Eine deterministisch eindeutige Modellwahl oder erzwungene
Loop-Grenze wird `not_required` und zählt nicht als Laya-Ausfall.

## Fehler und Limits

Maximal 64 KiB Anfrage, Text 8192 Zeichen, Environment und IDs 128 Zeichen,
bis zu 16 Kandidaten beziehungsweise Labels je Kategorie. Query maximal 2000,
Quellenauszug 512, Quellenverweis 1024 Zeichen. JSON-Schlüssel müssen eindeutig
sein; unbekannte Felder, Steuerzeichen, tiefe Verschachtelung, nicht endliche
Zahlen und Typumwandlungen bei Sicherheitsfeldern werden abgelehnt.

Die gesamte Anfrage durchläuft Policy vor Laya. Deny verhindert den Modellaufruf.
Tool-/Guardrail-Ausfall verlangt Review; Loop-Ausfall empfiehlt Stop;
Modellwahl verwendet die günstigste zulässige Option, Triage unknown und RAG
die ursprüngliche Reihenfolge mit Scores null. Fehler sind sichtbar; kein
Cloud-Fallback. Auch eine Low-Einstufung ist keine Ausführungserlaubnis.

Der installierte Checkpoint hat **512 Tokens Modellkontext**. Der Adapter prüft
mit dessen eigenem Tokenizer und Sequenzlayout, ob jede Frage den vollständigen
Context aufnehmen kann. Zu große Anfragen erhalten `context_too_large` und den
Profil-Fallback statt stiller Kürzung. Die erlaubten JSON-Maximalgrößen sind
keine Zusage, dass jeder gültige Inhalt in das Modell passt.

Die bestehende Worker-Admission begrenzt Inferenz auf vier gleichzeitige Worker
pro Host-Prozess. Mehrere unabhängige CLI-Prozesse teilen diesen Zähler nicht.
Timeout beendet und reapet den Worker. Rohtexte, Argumente und Quellenauszüge
werden nicht geloggt; notwendige Kandidaten-IDs und Quellenverweise sind Teil
der Empfehlungsausgabe und bleiben Daten des Aufrufers.

## Beobachtete Prüfung am 2026-10-11

Alle sechs Beispiele lieferten echte lokale Antworten ohne Fallback, ungefähr
19,4 bis 20,6 Sekunden pro Aufruf. Die Guardrail-Probe endete mit Code 2 wegen
der Modellklassifikation `suspicious`; die Inferenz selbst war erfolgreich.
Die synthetischen Resultate stehen in `laya-profiles-live-check.json`.
Eine zusätzliche echte RAG-Probe mit 16 kurzen Kandidaten lieferte alle
16 Scores ohne Fallback in 25,06 Sekunden; auch Quellenverweis `example:15`
blieb erhalten. Details: `laya-profiles-context-check.json`.
Bei 16 Auszügen mit jeweils 507 Zeichen griff der Kontextschutz vor der
Inferenz: `context_too_large`, sichtbarer Fallback, alle 16 Quellenverweise
erhalten. Details: `laya-profiles-overflow-check.json`.

**Fachliche Qualität ist damit nicht bestätigt:** Im RAG-Beispiel erhielt der
Kochtext 2,3121 und der passende Python-Testtext 2,1788; die Reihenfolge war
fachlich falsch. Auch der harmlose Guardrail-Text wurde als verdächtig markiert.
Diese Profile sind daher überprüfbare Entscheidungshilfen; die Proben liefern
keine Grundlage für autonome Sicherheitsentscheidungen oder verlässliche
Relevanzranglisten. Vor produktiver Nutzung braucht es aufgabenspezifische
Evaluation beziehungsweise ein geeigneteres oder trainiertes Checkpoint.

Die unabhängige Code- und Python-Review fand eine Rohwert-Typumwandlung im
Legacy-Adapter. Für Profilaufrufe werden erforderliche Felder und exakte
numerische Typen jetzt vor dieser Umwandlung geprüft. Regressionstests decken
Strings, boolesche Zahlen sowie fehlende Werte ab; Legacy-Aufrufe behalten
ihren bisherigen Vertrag.

Abschlussprüfung: 283 Tests bestanden, Ruff und `git diff --check` erfolgreich.
Die Worker-Protokollprüfung belegt außerdem, dass ungültige Rohantworten auch
über die echte Prozessgrenze als `invalid_answer` zurückkommen.

## Rücknahme

Der Feature-Branch `feat/laya-six-profiles` enthält die Änderung. Eine Rücknahme
beschränkt sich auf dessen Profilmodule, CLI-Zweig, profilbezogenen Adapterpfad,
Tests und Dokumentation. Keine Konfiguration, Checkpoints, Workflow-Registry
oder Brain-Daten wurden migriert.
