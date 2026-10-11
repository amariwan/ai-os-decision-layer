# Gesamt-Audit Global AI OS (2026-10-11, read-only)

## 1. Inventur (gemessen)
- Modelle: `/Users/snow/dev/models/laya` 2,2 GB intakt (root + typed-decisions + multilingual). Ollama: 9 Modelle (~140 GB), `ollama serve` läuft; embeddinggemma:300m vorhanden.
- Runtimes: decision-layer `.venv` (torch 2.14.1, transformers 5.19.0) intakt; `pytest` 135/135 PASS. Hermes-Desktop + Gateway laufen (localhost), `hermes`/`gateway`-Prozesse aktiv.
- Agents unberührt: nur untracked Docs (`eval/mcp-routing/`) als Diff — keine Config geändert (git-status verifiziert).
- Skills: 371 (Claude) + 55 (Codex) + 8 (OpenCode) + 679 (.agents) = stark dupliziert, keine Deduplizierung, kein Besitzer.
- MCP: Codex 21 Refs, Claude 1, OpenCode-Schema abweichend (0 Treffer aufs Pattern — UNVERIFIED, separates Schema).

## 2. Vorbefunde — Stand
- Benchmark (BGE 0.796 / EmbedGemma 0.787 / Laya 0.639 / Aurelio 0.639): Messwerte stehen, **Rohartefakte (/tmp-Dataset, Venv, Runner) sind weg** — /tmp wurde gecleant. Repro nur per Re-Run. EVIDENCE-LÜCKE.
- ToolHive-PoC: NO-GO als Discovery (Keyword-only, Live-Start unter Colima BLOCKED), aufräumend entsorgt.
- Laya: Leaf-Rolle bestätigt; 0.00 bei 100 Optionen; Confidence invertiert — kein Gating darauf.
- Pflicht-Routing: in keinem Client ohne Custom-Code möglich (weiterhin).

## 3. Risiken (gewichtet)
1. **Skill-S sprawl (hoch):** ~1.100 Skill-Verzeichnisse, Mehrfachpflege, kein Provenance-Check vor Install (Policy §35 verletzt implizit durch Volumen).
2. **Keine Abstention im Prod-Pfad (hoch):** No-Match-Fälle werden überall erzwungen beantwortet.
3. **Evidenz-Volatilität (mittel):** Benchmark-Rohdaten lagen in /tmp — ab sofort persistente Pfade nötig.
4. **Plattenverbrauch (mittel):** ~140 GB Ollama + 2,2 GB Laya; kein Problem auf 48-GB-Host, aber unkuratiert.
5. **Gateway-Lücke (mittel):** kein adopted Discovery-Layer; Status quo = Modell rät.

## 4. Empfohlene nächste Schritte
1. Dataset + Runner nach `decision-layer/eval/mcp-routing/data/` persistieren (Freigabe nötig — einziger Schreibeingriff).
2. Skill-Dedup: identische Namen/IDs über Clients listen, Kandidaten zum Archivieren vorschlagen (read-only zuerst).
3. Aurelio-Schwellen-Tuning auf echten No-Match-Fällen als kleinste verletzungsfreie Verbesserung (nur .venv, keine Client-Config).
4. PoC-2 (ContextForge) oder Schlussstrich —ene Entscheidung, drei Optionen wie gehabt.
