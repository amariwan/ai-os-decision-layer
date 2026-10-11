# Skill Inventory & Deduplication Report (read-only, 2026-10-11)

Method: SHA-256 over full dir trees (excl. `__pycache__/.git/node_modules`), frontmatter+body scan (first 6k chars/MD) for `github.com` provenance URLs and unsafe patterns. Nothing executed, nothing modified.

## Counts (VERIFIED)
| Client | Skills | No SKILL.md | No provenance |
|---|---|---|---|
| Claude Code (`~/.claude/skills`) | 369 | ~0 | massiv |
| .agents (`~/.agents/skills`) | 678 | ~0 | massiv |
| Codex (`~/.codex/skills`) | 55 | 0* | teilweise |
| OpenCode (`~/.config/opencode/skills`) | 8 | 0* | teilweise |
| Hermes browser-tools | 1 | 0 | VERIFIED (vendored) |
| Hermes otel-plugin | 1 | 0 | VERIFIED (vendored) |
| **Total** | **1.112** | **6** | **931 (84 %)** |

*stichprobenhaft; exakte Verteilung in `/tmp/skill_audit_data.json` (flüchtig — siehe Preservation-Hinweis).

## Duplikate (VERIFIED)
- 714 eindeutige Namen; **374 Namen in >1 Client**.
- **309 Gruppen byte-identisch** (gleicher SHA): fast immer claude↔agents und codex↔agents — reine Filesystem-Duplikate, kein unabhängiges Maintenance.
- **65 Gruppen gleicher Name, anderer Inhalt** (Konflikt-Versionen), z. B. `agentic-engineering`, `brain-*` (5×), `playwright`, `security-review`, `search-first`, `cavecrew`/`caveman*` (opencode vs claude/agents), `graphify` (4 Varianten, 8 KB–5 MB — Größenordnung deutet auf unterschiedliche Upstreams/Releases).
- Muster: codex↔agents meist identisch, claude weicht ab → **drei Pflegelinien** (codex/agents, claude, opencode-Nische).

## Dedup-Vorschlag (Approval-pflichtig, hier nur Vorschlag)
1. `.agents/skills` als kanonisch für alles, was dort byte-identisch mit Codex/Claude vorliegt (309 Gruppen) — Clients per Symlink/Config referenzieren statt kopieren (Details pro Client separat freigeben).
2. 65 Konflikte einzeln reviewen; Faustregel: neuere mtime + größere Vollständigkeit gewinnt, Upstream-URL entscheidet bei Gleichstand.
3. `graphify` (4 Varianten) und `caveman*` (2 Linien) zuerst — größte Divergenz, produktionsnah.
4. Upstream-Empfehlung: wo `github.com`-Provenienz fehlt (84 %), kein Auto-Dedup — Herkunft erst klären (siehe provenance-security.md).

## Client-Kompatibilität (VERIFIED)
Struktur überall `{name}/SKILL.md` + Referenzen — Formate kompatibel; Hermes nutzt zusätzlich `plugin.yaml`-Wrapper (otel) bzw. vendored skills (browser). Kein Client validiert Herkunft.
