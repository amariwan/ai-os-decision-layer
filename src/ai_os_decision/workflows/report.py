"""Generate reproducible measured coverage, not claims of runtime verification."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .analysis import CATEGORY_RULES


def write_report(registry, path: Path):
    stats = registry.stats()
    sources = registry.sources()
    group_risks = dict(registry.db.execute("""SELECT CASE level WHEN 4 THEN 'HIGH' WHEN 3 THEN 'UNKNOWN' WHEN 2 THEN 'MEDIUM' ELSE 'LOW' END,count(*)
        FROM (SELECT workflow_id,max(CASE risk WHEN 'HIGH' THEN 4 WHEN 'UNKNOWN' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END) level FROM variants GROUP BY workflow_id) GROUP BY level"""))
    group_status = dict(registry.db.execute("""SELECT status,count(*) FROM
        (SELECT workflow_id,CASE WHEN max(status='UNSAFE') THEN 'UNSAFE' WHEN min(status='VERIFIED') THEN 'VERIFIED' ELSE 'CANDIDATE' END status FROM variants GROUP BY workflow_id) GROUP BY status"""))
    local = registry.db.execute("SELECT count(DISTINCT workflow_id) FROM variants WHERE local_capable=1").fetchone()[0]
    def documents(source):
        scan = source.get("scan") or {}
        return scan.get("fetched_json_files", scan.get("json_files", 0) - (scan.get("errors", 0) if source["kind"] == "official" else 0))
    json_files = sum(documents(s) for s in sources)
    raw_unique = registry.db.execute("SELECT count(DISTINCT raw_hash) FROM occurrences").fetchone()[0]
    lines = ["# n8n Workflow Registry — Ergebnis", "", f"Stand: {datetime.now(UTC).isoformat()}", "",
             "Statische Wissensbasis im vorhandenen AI-OS-Host. Kein Workflow wurde ausgeführt, in n8n importiert oder aktiviert.", "",
             "## Umfang", "", "| Messwert | Anzahl |", "|---|---:|",
             f"| Registrierte Sources | {stats['sources']} |", f"| Sources KEEP | {sum(s['status']=='KEEP' for s in sources)} |",
             f"| Sources UNAVAILABLE | {sum(s['status']=='UNAVAILABLE' for s in sources)} |", f"| Sources DROP | {sum(s['status']=='DROP' for s in sources)} |",
             f"| Gefundene JSON-/JSONL-Quelldokumente inkl. ZIP-Mitglieder | {json_files} |",
             f"| Parsebare, strukturell akzeptierte Workflow-Vorkommen | {stats['occurrences']} |",
             f"| Unterschiedliche raw_hash | {raw_unique} |", f"| Verhaltensvarianten (normalized_hash) | {stats['variants']} |",
             f"| Einzigartige Strukturgruppen (structural_hash) | {stats['unique_workflows']} |",
             f"| Zusätzliche Vorkommen je Strukturgruppe | {stats['duplicates']} |",
             f"| Duplicate Ratio (1 − Strukturen / Vorkommen) | {stats['duplicate_ratio']:.2%} |",
             f"| Gruppen mit mindestens einer lokal geeigneten Variante | {local} |",
             f"| BROKEN-/Grenz-/Abruffehler in separater Issue-Tabelle | {stats['issues']} |", "",
             "Die Struktur-Duplicate-Ratio ist keine Quote semantisch identischer Automationen. Abweichende Parameter bleiben als Varianten erhalten. Statistik zählt gespeicherte Provenienz-Vorkommen einschließlich Versionen; Wiederholung desselben Snapshots fügt keine hinzu.", "",
             "## Quellen und Coverage", "", "| Quelle | SOURCE | Scan | Dokumente | Workflow-Vorkommen | Revision / Grenze |", "|---|---|---|---:|---:|---|"]
    for source in sources:
        scan = source.get("scan") or {}
        detail = source.get("revision") or source.get("availability_reason") or "public API snapshot"
        if "catalog_total" in scan:
            detail = f"{scan['discovered_ids']} IDs entdeckt / {scan['catalog_total']} gemeldet; {scan.get('errors',0)} Abruffehler"
        lines.append(f"| [{source['name']}]({source['url']}) | {source['status']} | {scan.get('status','NOT_SCANNED')} | {documents(source)} | {source['occurrences']} | {detail} |")
    lines += ["", "### Defekte Eingaben / Ablehnungsgründe", "", "| Grund | Issues |", "|---|---:|"]
    for reason, count in registry.db.execute("SELECT reason,count(*) FROM issues GROUP BY reason ORDER BY count(*) DESC LIMIT 12"):
        lines.append(f"| {reason} | {count} |")
    example = registry.search("RAG Ollama Postgres local", exclude_integration="openai", limit=1)
    local_ollama = registry.search("Ollama local", exclude_integration="openai", limit=1)
    lines += ["", "### Suchprobe", "", f"`RAG Ollama Postgres local` ohne OpenAI: **{example['total']} Strukturtreffer**. Allgemein `Ollama local` ohne OpenAI: **{local_ollama['total']}**. Null Treffer bleibt eine ehrliche Antwort; unbekannte Lokalität wird nicht zu `true` umgedeutet."]
    lines += ["", "## Bewertung", "", "Risikowerte auf Gruppenebene nehmen die riskanteste Variante (HIGH > UNKNOWN > MEDIUM > LOW). Ein UNSAFE-Vorkommen macht die Gruppenübersicht UNSAFE; Suchfilter und Detailberichte gelten immer für einzelne Varianten.", "", "| Risk | Strukturgruppen | Varianten |", "|---|---:|---:|"]
    for risk in ["LOW", "MEDIUM", "HIGH", "UNKNOWN"]:
        lines.append(f"| {risk} | {group_risks.get(risk,0)} | {stats['risk_variants'].get(risk,0)} |")
    lines += ["", "| WORKFLOW Status | Strukturgruppen | Varianten |", "|---|---:|---:|"]
    for status in ["VERIFIED", "CANDIDATE", "UNSAFE"]:
        lines.append(f"| {status} | {group_status.get(status,0)} | {stats['status_variants'].get(status,0)} |")
    lines += [f"| BROKEN (separate Quellobjekt-/Datei-Issues) | {stats['issues']} | — |",
              f"| DUPLICATE (zusätzliche normalisierte Vorkommen) | {registry.db.execute('SELECT count(*) FROM occurrences WHERE status=\'DUPLICATE\'').fetchone()[0]} | — |", "",
              "VERIFIED wird nicht durch Parsing oder statische Analyse vergeben. BROKEN-Dateien haben ggf. überhaupt keinen lesbaren Workflow; sie werden nicht künstlich als durchsuchbare Automation angelegt. DUPLICATE ist eine Vorkommensbeziehung, kein Sicherheitsurteil.", "",
              "## Kategorien", "", "Mehrfachkategorien pro Variante; gezählt werden unterschiedliche Strukturgruppen mit mindestens einer passenden Variante.", "", "| Kategorie | Gruppen |", "|---|---:|"]
    categories = {c["name"]: c["count"] for c in stats["categories"]}
    for category in CATEGORY_RULES:
        lines.append(f"| {category} | {categories.get(category,0)} |")
    lines += ["", "## Top Integrationen", "", "| Integration | Strukturgruppen |", "|---|---:|"]
    for integration in stats["integrations"][:25]:
        lines.append(f"| {integration['name']} | {integration['count']} |")
    lines += ["", "## AI / RAG / Ollama — prüfbare Kandidaten", "", "Auswahl über die tatsächliche Registry-Suche; keine Laufzeit- oder Qualitätsrangliste.", ""]
    for category in ["AI Agents", "RAG", "Ollama"]:
        lines += [f"### {category}", "", "| Kandidat | Risk | Local | Status | Quelle | ID |", "|---|---|---|---|---|---|"]
        for item in registry.search(category=category, status="CANDIDATE", limit=5)["items"]:
            source = next(s for s in item["sources"] if s["variant_id"] == item["normalized_hash"])
            name = item["name"].replace("|", "/").replace("\n", " ")[:100]
            lines.append(f"| {name} | {item['risk']} | {item['local_capable']} | {item['status']} | [{source['source_id']}]({source['source_url']}) | `{item['id']}` |")
        lines.append("")
    lines += ["## Nutzung", "", "From the repository root:", "", "```sh",
              'uv run ai-os workflows search "RAG Ollama Postgres local" --exclude-integration openai',
              'uv run ai-os workflows search --category Ollama --local-capable --risk LOW',
              'uv run ai-os workflows get WORKFLOW_ID',
              'uv run ai-os workflows export WORKFLOW_ID --variant VARIANT_ID --acknowledge-risk --output reviewed.json',
              'uv run ai-os workflows serve',
              'uv run --extra registry-mcp ai-os workflows mcp', "```", "",
              "Export erzeugt ausschließlich eine lokale, inaktive und bereinigte Vorlage. Mehrere Varianten verlangen explizite Auswahl. Export ist keine Ausführung und kein n8n-Import. Code kann beliebige Inhalte enthalten: Statische Erkennung und Bereinigung bieten keine vollständige Secret-/Sicherheitsgarantie.", "",
              "Read-only GET: /workflows, /workflows/{id}, /search, /categories, /integrations, /sources. HTTP bindet nur 127.0.0.1; kein dauerhafter Dienst wurde eingerichtet. MCP bietet sechs lesende Tools über den offiziellen optionalen Python-SDK-Adapter. Globale Client-Konfiguration unverändert.", "",
              "## Grenzen / offene Probleme", "",
              "- Lokale Eignung und Cloud-/API-Bedarf sind statische, teilweise unbekannte Einschätzungen. Ein lokales Modell reicht nicht für einen offline Workflow. Kostenpflicht bleibt UNKNOWN ohne belegte Entitlements/Tarife.",
              "- Node-Typen/-Versionen, Expressions, APIs und Lizenzrechte wurden nicht durch Live-Workflow-Ausführung validiert. CANDIDATE ist keine Funktionsfreigabe.",
              "- Große/symmetrische Graphen werden vorsichtig getrennt, statt unsichere Zusammenführungen zu erzwingen. Strukturen ignorieren Parameterwerte; Details und Filter verwenden Verhaltensvarianten.",
              "- Keine neue Vector-DB: Im Host existiert keine geeignete Embedding-Implementierung; FTS funktioniert ohne Modell/Cloud/MCP-Abhängigkeit.",
              "- Quelle mit ungeklärtem Commit bleibt UNAVAILABLE. Katalog-Repos ohne eigene JSON-Dateien bleiben KEEP und bringen zunächst nur Quellenwissen; verlinkte Ziel-Repos sind kein stillschweigender rekursiver Crawl.",
              "- Raw-Snapshots sind unveränderte öffentliche Upstream-Daten im ignorierten Datenverzeichnis. Registry/API enthalten keine Credential-Kontoidentitäten; Quellcode wird niemals ausgeführt.",
              "- Hash-/Analysemethode Version 1. Änderungen dieser Methoden erfordern einen bewusst neu aufgebauten Index; vorhandene Quelldaten bleiben wiederverwendbar.", ""]
    zero = [s["name"] for s in sources if s["status"] == "KEEP" and not s["occurrences"]]
    if zero:
        lines += ["Sources ohne akzeptierte Workflow-Definitionen im untersuchten Snapshot: " + ", ".join(zero) + ". Metadaten/Verlinkungen sind keine importierbaren Workflows.", ""]
    incomplete = [s["name"] for s in sources if s["status"] == "KEEP" and (s.get("scan") or {}).get("status") != "COMPLETE"]
    if incomplete:
        lines += ["Unvollständige Coverage: " + ", ".join(incomplete) + ". Siehe Source-Scan und Issues; kein Vollständigkeitsnachweis für diese Quellen.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
