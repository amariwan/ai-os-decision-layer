# Laya Six Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Sechs tatsächlich aufrufbare lokale Laya-Empfehlungsprofile mit verbindlichen deterministischen Grenzen liefern.

**Architecture:** Ein gemeinsamer validierter Anfragevertrag führt über reine Profilfunktionen zum vorhandenen isolierten Laya-Adapter. Ergebnisse trennen Modellbeobachtung, Policy und Empfehlung. Bestehende Task-Verträge bleiben kompatibel.

**Tech Stack:** Python >=3.12, stdlib, bestehendes uv/pytest/Ruff; keine neuen Abhängigkeiten.

**Spec:** `docs/superpowers/specs/2026-10-11-laya-six-profiles-design.md`

## Global Constraints

- Ausschließlich bestehender lokaler Laya-Worker; keine Cloud-Umschaltung, Installation, Tool-Ausführung oder Brain-Schreiboperation.
- Maximal 64 KiB UTF-8 je Anfrage; Text maximal 8192 Zeichen; Environment und IDs maximal 128 Zeichen.
- Unbekannte Felder, doppelte JSON-Schlüssel, nicht endliche Zahlen und boolesche Strings/Zahlen ablehnen.
- Höchstens 16 Modellkandidaten, Labels je Kategorie oder RAG-Dokumente; Labelbeschreibungen maximal 256, Query maximal 2000, Auszüge maximal 512 Zeichen.
- Deny beendet vor Modellaufruf; Review und harte Limits können durch Laya nicht aufgehoben werden.
- Kein Rohtext oder internes Traceback in Logs/Ausgaben. Keine Interpretation der Modellkonfidenz als Sicherheitsfreigabe.
- `ai-os-task/v1` und bestehende CLI-Befehle bleiben kompatibel.

## Review Focus

- Rekursiv tiefe Tool-Argumente oder Steuerzeichen: begrenzt ablehnen, ohne Traceback oder Rohdatenausgabe (Task 1/3).
- Library-Aufrufe mit Bool als Zahl oder fremden Objekten: dieselbe strikte Validierung wie CLI (Task 1).
- Modell manipuliert Antworttyp, NaN oder erlaubte Kandidaten: konservativer Fallback, niemals Freigabe (Task 3).
- Modellkontext erreicht Tokenlimit: keine Behauptung vollständiger RAG-Verarbeitung bei abgeschnittenem Kontext (Task 3/4).
- Mehrere gleichzeitige Aufrufe einschließlich Timeout: bestehende Worker-Admission bleibt begrenzt und gibt Slots korrekt frei (Task 3).

---

## Dateiverantwortung

- `src/ai_os_decision/recommendation_validation.py`: strikte JSON-/Profilvalidierung und begrenztes Dateilesen.
- `src/ai_os_decision/recommendation_profiles.py`: reine Fragenbuilder, deterministische Grenzen, Fallbacks und Ergebnisabbildung.
- `src/ai_os_decision/recommendations.py`: Policy, lokaler Aufruf, Antwortprüfung und gemeinsamer Ergebnisvertrag.
- `src/ai_os_decision/cli.py`: ausschließlich neuer `recommend`-Zweig plus bestehende Konfigurationsauswahl wiederverwenden.
- `tests/test_recommendation_validation.py`, `tests/test_recommendation_profiles.py`, `tests/test_recommendations.py`, `tests/test_recommendation_cli.py`: jeweils Tests der genannten Verantwortung.
- `examples/recommendations/*.json`, `docs/laya-profiles.md`, `README.md`: synthetische nutzbare Beispiele, Grenzen, Aufruf und Prüfnachweise.

### Task 1: Validierter Anfragevertrag

**Interfaces:** `load_request(path: str) -> dict`, `validate_request(profile: str, request: object) -> dict` in `recommendation_validation.py`; beide werfen `ValueError` oder `TypeError` ohne Eingabeinhalte. `validate_request` gibt eine validierte tiefe Kopie zurück.

- [x] Tests `test_rejects_duplicate_keys`, `test_size_limit_before_parse`, `test_rejects_bool_as_number`, `test_rejects_unknown_fields`, `test_rejects_deep_arguments` schreiben: je ungültiger Eingabe Exception; 65536 Bytes zulässig, 65537 abgelehnt.
- [x] `uv run --no-sync pytest tests/test_recommendation_validation.py -q` ausführen; fehlendes Modul als erwarteten roten Ausgang beobachten.
- [x] Begrenztes binäres Lesen mit 65537 Bytes, striktes UTF-8/JSON und doppelte Schlüssel über `object_pairs_hook` implementieren. Library-Daten vor JSON-Konvertierung rekursiv prüfen: ausschließlich dict mit String-Keys, list und JSON-Skalare; maximal 16 Ebenen; NUL/Steuerzeichen in Strings ablehnen. Endliche Zahlen, exakte bool-/int-Typen.
- [x] Gemeinsame Felder exakt `schema`, `text`, `environment`, `context`; Schema `ai-os-recommendation-request/v1`; nicht leere Text-/Environment-Werte. Profile und ihre exakten Context-Verträge aus Task 2 validieren; keine impliziten Defaults für Sicherheitsfelder.
- [x] Tests für alle sechs gültigen Beispielanfragen und je eine ungültige Variante ergänzen und grün ausführen.
- [x] Nur Validator und seine Tests mit `feat: validate bounded recommendation requests` committen.

### Task 2: Sechs reine Profile

**Interfaces:** `build_profile(profile: str, request: dict) -> ProfilePlan`, `resolve_profile(plan: ProfilePlan, observation: dict | None) -> dict` in `recommendation_profiles.py`. `ProfilePlan` ist eine frozen Dataclass mit `questions: list[DecisionQuestion]`, `state: DecisionState`, `fallback: dict`, `mandatory_review: bool`, `skip_reason: str | None` und validiertem Profilcontext. Ergebnis von `resolve_profile`: `recommendation` plus boolesches `review_required`; kein I/O.

**Exakte Context-Felder:**

- Model: `candidates`, `local_only`, `budget`; Kandidat `id`, `available`, `local`, `capable`, `estimated_cost`. 0..16 Kandidaten, eindeutige IDs; Kosten/Budget endlich >=0.
- Tool: `tool_id`, `action`, `arguments`, `permitted`; Aktion aus `read/write/delete/deploy/publish/message/permission/credential`. Argumente dict, `permitted` bool.
- Intent: `intents`, `domains`; jeweils Label-ID -> Beschreibung, 2..16 Einträge, zwingend `unknown`.
- Loop: `iteration`, `max_iterations`, `elapsed_seconds`, `timeout_seconds`, `cost`, `budget`, `goal_complete`, `verification_pending`; Grenzen gemäß Spec, exakte Zahlen-/Bool-Typen.
- RAG: `query`, `candidates`; Kandidat `id`, `source`, `excerpt`; 1..16 Einträge, eindeutige IDs, Quellenverweis nicht leer und maximal 1024 Zeichen.
- Guardrails: `content`, `origin`; Inhalt maximal 8192, Herkunft nicht leer maximal 128 Zeichen.

- [x] Tests `test_filters_unavailable_remote_over_budget`, `test_single_model_skips_choice`, `test_tool_write_requires_review`, `test_loop_each_limit_stops`, `test_pending_verification_wins`, `test_rag_stable_ties_preserve_sources`, `test_intent_fallback_unknown`, `test_guardrail_fallback_requires_review` schreiben.
- [x] `uv run --no-sync pytest tests/test_recommendation_profiles.py -q` ausführen und roten Ausgang beobachten.
- [x] Profile implementieren. Fragen-IDs: `model`, `risk`, `intent`/`domain`, `next_step`, `doc_0` bis `doc_15`, `guardrail`. Optionen und Skalen exakt aus Spec. RAG-Skala 0..4; Modell-Fallback billigste erlaubte ID, dann lexikographisch; RAG-Fallback Eingangsreihenfolge mit Score null.
- [x] Vollständigen validierten Aufgabencontext explizit in `DecisionState.extra['profile_context']` tragen; nicht allein vom auf 2000 Zeichen gekürzten `state.text` abhängig machen. Keine Quelle als Anweisung verwenden.
- [x] Keine erlaubten Modelle -> Review; genau eines -> deterministische Empfehlung. Tool ohne Berechtigung -> Deny vor Laya. Loop Stop/Verify durch harte Grenzen wird deterministisch ausgegeben und als `not_required` markiert.
- [x] Bei Laya-Ausfall Tool/Guardrails -> Review, Loop -> Stop; Modell/Intent/RAG behalten beschriebene sichtbare Fallbacks.
- [x] Profiltests grün ausführen; Modul und Tests mit `feat: add six bounded Laya decision profiles` committen.

### Task 3: Policy und lokaler Runtime

**Interfaces:** `recommend(profile: str, request: object, runtime: ShadowRuntime) -> dict` in `recommendations.py`; Fehlerausgaben über `empty_result(profile: str, status: str) -> dict`; Bibliothek und CLI nutzen denselben Einstieg.

- [x] Tests parametrisiert je Profil schreiben: `test_success`, `test_deny_in_context_skips_engine`, `test_timeout_fallback`, `test_missing_checkpoint_fallback`, `test_invalid_answer_fallback`; `execution_enabled is False` immer prüfen.
- [x] Zusätzlich `test_wrong_kind_nan_and_extra_answers`, `test_policy_approval_survives_low_risk`, `test_full_context_reaches_engine`, `test_bounded_worker_admission` und `test_no_input_echo` schreiben. Engine-Spy muss Deny mit null Aufrufen beweisen; fremde IDs müssen Fallback ergeben.
- [x] `uv run --no-sync pytest tests/test_recommendations.py -q` ausführen; roten Ausgang beobachten.
- [x] Vollständige Eingabe validieren; Policy auf alle String-Keys/-Werte rekursiv und aggregierten Kontext anwenden; Gründe deduplizieren, Deny/Review logisch OR. Tool-Aktion zusätzlich als vertrauenswürdigen `action_hint` prüfen. Keine Speicherung der geprüften Inhalte.
- [x] Bestehenden `runtime.laya.decide` verwenden; `run_worker` hat bereits globale prozesslokale Admission mit vier Slots. Keine zweite unbeschränkte Queue hinzufügen. `decision_id` lokal erzeugen.
- [x] Antworten exakt auf Fragemenge, ID, Typ, Choice-Mitgliedschaft, endliche Konfidenz [0,1], Score [0,4] und echte bool prüfen. Modellbeobachtung erst nach vollständiger Prüfung übernehmen. Fehlercodes aus fester Liste: `timeout`, `unavailable`, `overloaded`, `invalid_answer`.
- [x] `ai-os-recommendation/v1` mit Policy, Empfehlung und Laya-Metadaten ausgeben. Review hat Vorrang vor Ready, Deny vor beiden. Workerfehler liefern keine internen Texte.
- [x] Kontext-Tokenisierung des lokalen Checkpoints prüfen: ein aufrufbarer Profilvertrag darf Größenlimits nicht mit garantiert vollständiger Tokenrepräsentation verwechseln. Für zu großen Modellcontext vor Inferenz explizit auf konservativen Fallback gehen; mindestens letztes RAG-Dokument muss nachweislich im Modellinput erhalten bleiben.
- [x] Runtime- und bestehende Audit-/Task-Tests grün ausführen; mit `feat: enforce policy around local profile recommendations` committen.

### Task 4: CLI, Beispiele, reale Proben und Review

**Interfaces:** `ai-os recommend PROFILE REQUEST.json [--config PATH] [--model-dir PATH] [--timeout-ms N] [--require-laya]`; `_runtime(..., require_policy=True)` wiederverwenden. Bestehende CLI-Schnittstellen unverändert.

- [x] Tests `test_recommend_cli_success`, `test_require_laya_exit_3`, `test_review_precedes_strict_exit`, `test_invalid_config_json`, `test_duplicate_json_exit_2`, `test_task_contract_unchanged` schreiben; erwartete Schemas und Exitcodes 0/2/3 explizit prüfen.
- [x] `uv run --no-sync pytest tests/test_recommendation_cli.py -q` ausführen; fehlenden CLI-Zweig als roten Ausgang beobachten.
- [x] CLI-Zweig und sechs synthetische Dateien `examples/recommendations/{model-routing,tool-risk,intent-domain,loop,rag-rerank,guardrails}.json` ergänzen. Beispiele enthalten keine echten Zugangsdaten oder Betriebsinventare. Model-Beispiel enthält zwei zulässige lokale Optionen, Loop-Beispiel kein bereits erreichtes Limit, damit reale Laya-Aufrufe möglich sind.
- [x] `docs/laya-profiles.md` mit exakten Aufrufen, Grenzen, Fallbacks und Prüfergebnissen schreiben; README auf Einstieg verlinken.
- [x] `uv run --no-sync pytest -q`, `uv run --no-sync ruff check .` und `git diff --check` ausführen; alle müssen bestehen. Ausgangspunkt sind 194 bestehende Tests; finale Zahl aus tatsächlicher Ausgabe übernehmen.
- [x] Jede Beispieldatei mit `uv run --no-sync ai-os recommend PROFILE examples/recommendations/PROFILE.json --require-laya` lokal ausführen. `laya.status == 'ok'`, keine Fallbacks und Outputvertrag prüfen; Review-Exitcode 2 bei Sicherheitsprofilen ist fachlich zulässig und kein technischer Inferenzfehler.
- [x] Echte RAG-Probe mit maximaler Kandidatenzahl separat ausführen, Kontextgrenze und letzten Kandidaten prüfen. Fachliche Relevanzqualität getrennt von technischer Vollständigkeit dokumentieren.
- [x] Unabhängige Code-/Python-Sicherheitsreview des gesamten neuen Diffs beauftragen; Findings beheben und betroffene Checks erneut ausführen. Review bleibt read-only; ein Implementierer im aktuellen Chat.
- [x] ProjektAtlas nach Änderungen aktualisieren, finalen Diff auf Scope prüfen und ausschließlich eigene Dateien mit `feat: expose and verify six local Laya recommendation profiles` committen.
- [x] Abschluss berichtet implementierte Funktionen, beobachtete Tests und reale Inferenzresultate; keine produktive Genauigkeit oder externe Integration behaupten.

## Selbstprüfung und Ausführung

Alle sechs Spec-Profile sind Task 2 zugeordnet; gemeinsame Grenzen/Fehler Task 1/3;
CLI, Beispiele, Kompatibilität und Abnahme Task 4. Review-Fokus ist jeweils
durch benannte Tests abgedeckt. Funktionsnamen und Übergabetypen sind zwischen
Tasks konsistent. Keine Konfigurations-, Provider- oder Brain-Migration nötig.

Empfohlene Methode: native Umsetzung im aktuellen Chat durch einen
Implementierer, danach unabhängige Review. Die Tasks teilen eng gekoppelte
Verträge; parallele Implementierung würde hier Koordinationskosten erzeugen.

Status: umgesetzt und lokal verifiziert am 2026-10-11. 283 Tests, Ruff und Diff-Prüfung bestanden. Sechs reale Inferenzproben sowie RAG-Kontextgrenzen geprüft. Fachliche Modellqualität bleibt eingeschränkt; siehe docs/laya-profiles.md.

Ausführungsentscheidungen: Feature-Branch im bestehenden Checkout statt separater Worktree; dadurch bleibt das lokale CLI direkt nutzbar, Änderungen am Arbeitsverzeichnis bleiben jedoch gemeinsam sichtbar. Zusätzliches Fehlerlabel `context_too_large` unterscheidet Modellfenstergrenzen von Ausfällen; Verbraucher müssen dieses zusätzliche Label akzeptieren.
