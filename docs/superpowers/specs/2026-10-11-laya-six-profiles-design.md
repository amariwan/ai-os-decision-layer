# Laya: sechs Entscheidungsprofile im bestehenden AI-OS

Datum: 2026-10-11. Status: Entwurf zur Prüfung; keine Implementierungsfreigabe dieses Dokuments vorausgesetzt.

## Ziel und bestätigter Umfang

Der Nutzer möchte Laya über das bestehende AI-OS für Modellwahl, Tool-Risiken,
Intent und Domain, Loop-Entscheidungen, RAG-Reranking und Guardrails verwenden.
Die sechs Profile sollen tatsächlich aufrufbare, strukturierte Empfehlungen
liefern. Die bereits besprochene Grenze bleibt bestehen: AI-OS erzwingt Policy,
Berechtigungen und Limits. Eine Modellantwort erteilt keine Ausführungsfreigabe.

Erfolg bedeutet sechs lokal nutzbare Profile mit validierten Eingaben,
sichtbaren Fehlern, deterministischen Grenzen, Tests und echten lokalen
Laya-Proben. Ein Modellaufruf allein belegt keine fachliche Qualität.

## Bestehender Stand und Wiederverwendung

EXISTING: `DecisionState`, `DecisionQuestion`, `DecisionAnswer`, `PolicyEngine`,
`IsolatedLayaDecisionEngine` und der begrenzte Worker mit Prozessdeadline.
`ai-os task` liefert eine deterministische Route und eine Laya-Beobachtung.
`ShadowRuntime` hält Modellantwort und verbindliche Baseline auseinander.

EXTEND: vorhandenes CLI und lokaler Adapter um typisierte Profilanfragen.
NEW: ein kleines Profilmodul mit reinen Validierungs-, Fragebildungs- und
Ergebnisfunktionen sowie gezielte Tests und JSON-Beispiele. Keine neuen Dienste,
Datenbanken, Abhängigkeiten oder permanenten Modellprozesse.

Die bestehende Ausgabe `ai-os-task/v1` und die bisherigen Befehle bleiben
kompatibel. Die sechs Profile erhalten einen eigenen versionierten Vertrag.

## Ansätze und Entscheidung

1. **Gemeinsame Profile im vorhandenen Runtime:** ein Aufrufvertrag, vorhandener
   Worker, explizite Grenzen je Profil. Empfohlen wegen geringer zusätzlicher
   Infrastruktur und gezielter Testbarkeit.
2. Sechs eigenständige Dienste: zusätzliche Laufzeit-, Betriebs- und
   Integrationskosten ohne derzeit nachgewiesenen Bedarf.
3. Laya als alleinige Instanz für Ausführung und Sicherheit: verworfen. Die
   Modellantwort kann Policy nicht ersetzen; die vorangegangene Rollenprobe
   wählte mehrfach alleinige Modellautorität und zeigte damit einen konkreten
   Grund für externe Grenzen.

## Aufruf und gemeinsame Verträge

Vorgesehen ist `ai-os recommend PROFILE REQUEST.json` mit Profilen
`model-routing`, `tool-risk`, `intent-domain`, `loop`, `rag-rerank`, `guardrails`.
Konfigurationsauswahl und Flags `--config`, `--model-dir`, `--timeout-ms`,
`--require-laya` folgen `ai-os task`. Profilanfragen sind lokale strukturierte
Daten, keine Programme oder Tool-Aufrufe. Die Bibliotheksfunktion verwendet
denselben Validierungs- und Policy-Pfad wie das CLI.

Gemeinsame Eingaben: `schema: ai-os-recommendation-request/v1`, `text`,
`environment` und ein profilspezifisches `context`-Objekt. Unbekannte Felder,
falsche Typen, nicht endliche Zahlen und doppelte JSON-Schlüssel werden
abgelehnt. Maximal 64 KiB UTF-8 pro Anfrage, Text maximal 8192 Zeichen,
Environment maximal 128 Zeichen, IDs maximal 128 Zeichen. Boolesche Werte
werden niemals aus Strings oder Zahlen abgeleitet. Größenbegrenzung gilt
bereits vor vollständigem Einlesen der Datei.

Gemeinsame Ausgabe: `schema: ai-os-recommendation/v1`, `profile`, `status`,
`decision_id`, `execution_enabled: false`, `policy`, `recommendation`, `laya`.
`laya` enthält `attempted`, `status`, `fallback_used`, `latency_ms`, einen
bereinigten Fehlercode und die validierte Modellbeobachtung. Statuswerte sind
`ready`, `review_required`, `denied`, `invalid_request`, `invalid_config`.
Eine abgeschlossene Empfehlung ist keine Ausführungserlaubnis.

Exitcodes: 0 für eine verwertbare Empfehlung einschließlich sichtbarem
konservativem Fallback; 2 für ungültige, abgelehnte oder prüfpflichtige Anfragen;
3 bei `--require-laya`, wenn sonst eine verwertbare Fallback-Empfehlung vorliegt.
Status 2 hat Vorrang vor Status 3.

## Datenfluss und Autorität

1. Größe und Schema der vollständigen Anfrage prüfen.
2. Deterministische Policy auf die vollständigen relevanten Eingabefelder
   anwenden, einschließlich Tool-Argumenten und Quellenauszügen. Ein Deny
   beendet die Anfrage vor dem Modellaufruf. Bestehende Freigabepflicht bleibt
   sichtbar und kann durch Laya nicht entfernt werden.
3. Vertrauenswürdige Kandidatenfilter und harte Limits anwenden.
4. Kompakte, explizit begrenzte Fragen an den lokalen isolierten Adapter stellen.
5. Vollständigkeit, Antworttypen, Wertebereiche und erlaubte Optionen prüfen.
6. Empfehlung und Modellbeobachtung getrennt ausgeben. Modelloutput kann eine
   Empfehlung verschärfen, niemals verbindliche Grenzen lockern.

Inventare, Rechte, Kosten und Loop-Zähler kommen vom aufrufenden Host. Die
Profile können deren Wahrheit nicht selbst attestieren. Modellgenerierte
Inventare gelten nicht als verifizierte Verfügbarkeit oder Berechtigung.

## Die sechs Profile

### 1. Model Routing

Context: höchstens 16 eindeutige Modellkandidaten mit ID, verfügbar (bool),
lokal (bool), aufgabenfähig (bool), geschätzten Kosten (endliche Zahl >= 0);
zusätzlich lokaler Zwang (bool) und Budget (endliche Zahl >= 0).
AI-OS filtert verfügbare, aufgabenfähige und budgetkonforme Kandidaten vorab;
bei lokalem Zwang bleiben ausschließlich lokale Kandidaten.

Laya wählt eine erlaubte ID. Bei einem Kandidaten ist die Wahl deterministisch
und Laya wird als nicht erforderlich ausgewiesen; bei keinem Kandidaten folgt
`review_required`. Fallback ist der günstigste erlaubte Kandidat, bei
Gleichstand die lexikographisch erste ID. Es wird keine Modellinferenz beim
ausgewählten Provider gestartet und kein Cloud-Zugang aktiviert.

### 2. Tool-call Risk Gates

Context: Tool-ID, Aktion aus `read`, `write`, `delete`, `deploy`, `publish`,
`message`, `permission`, `credential`, strukturierte Argumente und ein
explizites boolesches Host-Berechtigungsmerkmal. Fehlende Berechtigung bedeutet
`denied`. Jede Aktion außer `read` bleibt `review_required`; das ist eine
konservative Profilgrenze zusätzlich zur bestehenden Policy.

Laya bewertet `low`, `medium`, `high` oder `critical`. Medium bis critical
verschärft auf `review_required`. Fehlendes oder ungültiges Modellergebnis
ergibt ebenfalls `review_required`. Auch ein positives Read-Ergebnis ist nur
eine Empfehlung: kein Dispatcher, keine Tokenweitergabe, kein Tool-Aufruf.

### 3. Intent + Domain Triage

Context: jeweils 2 bis 16 eindeutige Intent- und Domain-Labels, darunter
`unknown`; kurze Beschreibungen maximal 256 Zeichen. Laya beantwortet zwei
Choice-Fragen. Ergebnisse müssen zu den vorgegebenen Labels gehören.
Fallback ist für beide Felder `unknown`. Bestehende Task-Routen werden dadurch
nicht stillschweigend überschrieben.

### 4. LOOP Decisions

Context: Iterationszähler und Maximum (ganze Zahlen >= 0, Maximum >= 1),
verstrichene Zeit und Zeitlimit, Kosten und Budget (endliche Zahlen >= 0),
sowie boolesche Merkmale `goal_complete` und `verification_pending`.
Erreichtes Iterations-, Zeit- oder Kostenlimit sowie abgeschlossenes Ziel
erzwingen `stop`. Offene Verifikation erzwingt `verify`.

Nur sonst empfiehlt Laya `continue`, `verify`, `replan` oder `stop`.
Fallback ist `stop` mit explizitem Fehlergrund. Das Profil ist eine einzelne
Entscheidung, kein selbständig laufender Agent. Es führt keine Iteration aus.

### 5. RAG Reranking

Context: Query maximal 2000 Zeichen und 1 bis 16 bereits abgerufene Kandidaten
mit eindeutiger ID, nicht leerem Quellenverweis und Auszug maximal 512 Zeichen.
Query und Auszüge werden explizit in einem begrenzten strukturierten Feld
übertragen, sodass die Textkürzung des bestehenden Adapters keine Kandidaten
unbemerkt entfernt. Eine Score-Frage je Kandidat verwendet dieselbe feste
Relevanzskala mit fünf Kriterien: irrelevant (0), schwach (1), teilweise (2),
relevant (3), direkt passend (4). Der lokale Adapter liefert den gewichteten
Kriterienindex als endlichen Score in [0, 4]; Vertragsproben sichern das ab.

Ausgabe enthält ausschließlich ursprüngliche IDs, Quellenverweise und Scores;
absteigend nach Relevanz, bei Gleichstand ursprüngliche Reihenfolge. Fallback
behält die Eingangsreihenfolge und markiert Scores als nicht verfügbar.
Quelleninhalt bleibt untrusted data. Relevanz bedeutet weder Wahrheitsprüfung
noch Zitierfreigabe. Kein automatisches Graphiti-Retrieval oder Brain-Schreiben.

### 6. GUARDRAILS & Policy Checks

Context: zu prüfender Inhalt als begrenzter Text und Herkunftslabel. Die
vollständige Anfrage durchläuft zuerst die bestehende deterministische Policy.
Laya klassifiziert danach `no_issue_detected`, `suspicious`, `policy_sensitive`
oder `unknown`. Nur `no_issue_detected` lässt den bereits bestehenden Status
unverändert; alle anderen Werte verlangen Prüfung. Ausfall verlangt Prüfung.
Das Ergebnis behauptet weder Sicherheit noch vollständige Angriffserkennung.

## Fehler, Datenschutz und Laufzeit

Alle Profile verwenden ausschließlich den vorhandenen lokalen Laya-Worker.
Fehlendes Checkpoint, Timeout, Überlastung und fehlerhafte Modellantworten
werden sichtbar und nutzen den beschriebenen Fallback. Keine automatische
Provider-Umschaltung, Installation oder Erweiterung von Berechtigungen.

Antwortprüfung verlangt passenden Fragetyp, vollständige eindeutige Antworten,
Choice-Mitgliedschaft, RAG-Scores in [0, 4] sowie endliche Konfidenzen in [0, 1].
Boolesche Antworten müssen echte boolesche Werte sein. Konfidenz bleibt ein unkalibrierter Modellscore; daraus wird
keine Sicherheitsfreigabe abgeleitet. Profilaufrufe erhalten begrenzte
Admission, damit parallele Anfragen keine unbegrenzten Worker starten.

Keine Speicherung von Rohtexten, Tool-Argumenten oder Quellenauszügen in Logs.
CLI-Ausgaben enthalten nötige IDs und Empfehlungen, nicht Kopien vollständiger
Eingaben oder interne Tracebacks. Keine Konfigurationsänderung ist zur
Aktivierung neuer Provider notwendig.

## Änderungspunkte und Umsetzungsschritte

1. Profilverträge und reine Validatoren mit Tests im vorhandenen Paket ergänzen.
2. Sechs Fragenbuilder und deterministische Filter/Fallbacks implementieren.
3. Gemeinsamen begrenzten lokalen Aufruf und strikte Antwortprüfung ergänzen.
4. CLI `recommend` integrieren; `task`, `decide` und `system-one` erhalten
   Regressionstests auf ihre bisherigen Verträge.
5. Synthetische JSON-Beispiele, Benutzerdokumentation und lokale Laya-Proben
   für alle sechs Profile ergänzen.

## Abnahme und Prüfungen

- Pro Profil: gültiger Fall, ungültige Eingabe, echter Deny vor Modellaufruf,
  Timeout, fehlendes Checkpoint und ungültige Modellantwort.
- Modellrouting: nicht verfügbare, zu teure und verbotene Remote-Kandidaten
  bleiben auch bei absichtlich widersprechendem Modell ausgeschlossen.
- Tool/Guardrails: niedrige Modellrisikoeinstufung hebt Deny oder Review nie auf.
- Loop: jedes einzelne Limit erzwingt Stop; offene Prüfung erzwingt Verify.
- RAG: alle Kandidaten erreichen den Worker, Reihenfolge ist stabil, Quellen
  bleiben erhalten, NaN/Infinity und erfundene IDs werden abgelehnt.
- CLI: JSON-Grenzen, doppelte Schlüssel, Exitcodes, strikte Laya-Pflicht,
  sichtbarer Fallback und bestehende Task-Kompatibilität.
- Bestehende Testsuite, Ruff und Diff-Prüfung; unabhängige Sicherheitsreview
  der Profile vor Abschluss gemäß lokaler AI-OS-Policy.
- Je Profil mindestens eine echte lokale Inferenz. Getrennt dokumentieren:
  technische Vertragsprüfung versus fachliche Ergebnisqualität. Keine
  Behauptung produktiver Genauigkeit aus wenigen synthetischen Beispielen.

## Auslieferung und Rücknahme

Lieferumfang sind lokale Bibliotheks-/CLI-Profile, Beispiele, Tests und
Dokumentation. Kein Deployment, kein autonomer Loop und keine allgemeine
MCP-Interception. Externe Anwendungen müssen den neuen Einstieg ausdrücklich
aufrufen, bevor dort eine Integration behauptet werden kann.

Rücknahme entfernt ausschließlich die neuen Profile, ihren CLI-Zweig und ihre
Dokumentation/Tests anhand des finalen Diffs. Bestehende Task-Funktion,
Konfiguration, Checkpoints und Brain-Daten bleiben erhalten.

Nächster Prozessschritt nach Prüfung dieses Entwurfs: schriftlicher
Implementierungsplan nach Superpowers und Auswahl der Ausführung im aktuellen
Chat mit einem Implementierer und unabhängiger Review.

## Beobachtete Vorprüfungen

Am 2026-10-11: bestehende Testsuite `uv run --no-sync pytest -q`: 194 Tests
bestanden in 2,71 Sekunden. Lokale Architekturfrage über die geladene AI-OS-
Policy und `IsolatedLayaDecisionEngine`: Provider `laya`, Wahl `profiles`,
Latenz 19,924 Sekunden. Das bestätigt den erfolgreichen Aufruf und dokumentiert
die Modellpräferenz; es validiert keine der sechs noch zu implementierenden
Profilfunktionen. Für diesen Entwurf wurden keine Produktcodeänderungen gemacht.
