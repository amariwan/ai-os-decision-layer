# Provenance & Security Findings (read-only scan, nichts ausgeführt)

## Provenienz (VERIFIED)
- 931/1.112 Skills (84 %) ohne `github.com`-Referenz in den ersten 6 KB aller MD-Dateien → Herkunft UNVERIFIED. Rest hinter Git-History? Nicht geprüft (tieferer Scan braucht Freigabe).
- 6 Skills ohne SKILL.md (UNVERIFIED ob defekt oder Alternativlayout).
- Hermes-Skills sind vendored (Tool-/Plugin-Baum) — VERIFIED, aber Versions-Pinning UNVERIFIED.

## Unsichere Muster — 67 Treffer, einzeln geprüft (Stichprobe, VERIFIED-Einordnung)
1. `codex/cloudflare-deploy` (zahlreich): **False Positives** — `.exec(` sind SQL-Calls in Referenz-Docs, kein Shell-Exec.
2. `codex/render-deploy/SKILL.md:111`: `curl -fsSL … | sh` — offizieller Vendor-Installer (render-oss). Legitim, aber Pipe-to-Shell → REVIEW: nur mit Pin/Hash akzeptieren, sonst ersetzen.
3. `codex/reverse-skill-router` (Pentest-Playbooks, u. a. file-upload/intranet-postexp): **Dual-Use by Design** — Angriffswissen als Skill-Content. Kein Verstoß-Fund per se, aber: needs owner + Freigabe-Kreis; Policy §35 (Provenienz reviewen) hier zuerst anwenden.
4. Restliche Treffer: überwiegend `exec(`/`eval(` in Code-Docs (JS/SQL) — UNVERIFIED im Einzelnen, kein akuter Fund.

## Upstream-Empfehlungen (kanonisch, updatefähig)
- Wo Byte-Identität vorliegt: Single Source in `.agents/skills`, Upstream-URL in ID-Gruppe nachtragen (Herkunft je Gruppe verifizieren lassen).
- Vendor-Skills (render, cloudflare): auf offizielle Installer + pinned Releases umstellen statt Curl-Pipes.
- Offensive-Security-Skills (`reverse-skill-router`, `src-hunter`, `pentest-tools`): in separaten, restriktiven Scope; kein Auto-Update ohne Review.
- Generell: Neuinstallationen nur mit Provenienz (Policy §35) — gilt ab sofort, kein Retro-Zwang ohne Freigabe.

## Klassifikation
- VERIFIED: Zählungen, Hash-Gruppen, 3 Einordnungen oben.
- UNVERIFIED: Einzel-Treffer jenseits Stichprobe; Upstream-Identität je Gruppe; Hermes-Pinning.
- UNSUPPORTED (ohne Custom-Code): automatische Herkunfts-Verifikation, erzwungenes Skill-Gating pro Client.
