"""Conservative static metadata. Capability flags are tri-state hypotheses."""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

CATEGORY_RULES = {
    "AI Agents": r"langchain.agent|ai.?agent", "RAG": r"\brag\b|retriev|vectorstore|embeddings",
    "Ollama": r"ollama", "Local AI": r"ollama|llamacpp|lmstudio|localai", "MCP": r"\bmcp\b",
    "Research": r"research|arxiv|pubmed|wikipedia", "Scraping": r"scrap|firecrawl|browserless|puppeteer|crawl",
    "GitHub": r"github", "Gmail": r"gmail", "Google": r"google|gmail|gemini",
    "Telegram": r"telegram", "Discord": r"discord", "Slack": r"slack", "Postgres": r"postgres",
    "Supabase": r"supabase", "Vector DB": r"vectorstore|qdrant|pinecone|weaviate|chroma|milvus|pgvector",
    "Documents": r"document|\bpdf\b|extractfromfile|invoice|notion|googledocs",
    "DevOps": r"docker|kubernetes|jenkins|deployment|gitlab", "Monitoring": r"monitor|uptime|grafana|prometheus|alert",
    "Security": r"security|threat|malware|\bioc\b|vulnerability|virustotal|\bcti\b",
    "Notifications": r"notification|telegram|discord|slack|emailsend", "Backup": r"backup|restore",
    "API": r"httprequest|webhook|graphql", "Webhooks": r"webhook", "CRM": r"\bcrm\b|salesforce|hubspot|twenty|pipedrive|lead",
    "E-Commerce": r"shopify|woocommerce|stripe|e.?commerce",
}
LOCAL = {"ollama", "postgres", "mysql", "mariadb", "mongodb", "redis", "qdrant", "weaviate", "chroma", "milvus", "supabase", "minio", "n8n", "localhost"}
CLOUD = {"openai", "anthropic", "gemini", "openrouter", "cohere", "groq", "deepseek", "mistral", "huggingface", "pinecone", "google", "gmail", "slack", "discord", "telegram", "salesforce", "hubspot", "notion", "airtable", "dropbox", "shopify", "stripe", "twilio", "serpapi", "firecrawl"}
PROVIDERS = {"ollama", "openai", "anthropic", "gemini", "openrouter", "cohere", "groq", "deepseek", "mistral", "huggingface", "lmstudio", "localai"}
KNOWN_DOMAINS = {"api.openai.com", "api.anthropic.com", "openrouter.ai", "api.github.com", "api.telegram.org", "slack.com", "discord.com", "googleapis.com", "api.notion.com"}
CLOUD |= {"github", "asana", "trello", "microsoft", "outlook", "zoom", "clickup", "calendly", "mailchimp", "sendgrid"}
SAFE_BASE = {"manualtrigger", "set", "editfields", "if", "switch", "merge", "splitout", "splitinbatches", "limit", "sort", "filter", "aggregate", "noop", "wait", "webhook", "respondtowebhook", "scheduletrigger", "cron", "errortrigger", "stickynote", "stopanderror", "datetime", "crypto", "html", "markdown", "xml", "compression", "extractfromfile", "converttofile", "summarize", "removeduplicates", "renamekeys"}
SECRET_NAME = r"(?i)password|secret|api.?key|access.?token|authorization|cookie|private.?key|x-auth-token"


def contains_named_secret(value, depth=0) -> bool:
    if depth > 16:
        return False
    def literal(item):
        return bool(item) and not str(item).lstrip().startswith(("=", "{", "$", "[", "YOUR", "REPLACE"))
    if isinstance(value, dict):
        if isinstance(value.get("name"), str) and re.search(SECRET_NAME, value["name"]) and literal(value.get("value")):
            return True
        return any((re.search(SECRET_NAME, key) and literal(child)) or contains_named_secret(child, depth + 1)
                   for key, child in value.items())
    if isinstance(value, list):
        return any(contains_named_secret(child, depth + 1) for child in value)
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return contains_named_secret(json.loads(value), depth + 1)
        except (ValueError, RecursionError):
            pass
    return False


def local_host(host: str) -> bool:
    host = host.lower()
    if host in LOCAL or host in {"host.docker.internal", "umbrel.local"} or host.endswith((".local", ".localhost")):
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def redact(value, depth=0):
    """Strip account identities, secret-like fields and URL credentials/query."""
    if depth > 32:
        return "[REDACTED_DEPTH_LIMIT]"
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, dict):
        pair = isinstance(value.get("name"), str) and re.search(SECRET_NAME, value["name"])
        return {k: ("[REDACTED]" if re.search(SECRET_NAME, k) or (pair and k == "value")
                    else redact(v, depth + 1)) for k, v in value.items() if k not in {"credentials", "pinData", "staticData"}}
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(redact(json.loads(value), depth + 1), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        if re.search(r"(?i)bearer\s+\S+|\bsk-[a-zA-Z0-9_-]{12,}|-----BEGIN .*PRIVATE KEY", value):
            return "[REDACTED]"
        return re.sub(r"https?://[^\s\"'<>]+", lambda m: safe_url(m[0]), value)
    return value


def safe_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.hostname or ''}" + (f":{parts.port}" if parts.port else "") + parts.path
    except ValueError:
        return "[INVALID_URL]"


def analyze(workflow: dict) -> dict:
    nodes = workflow["nodes"]
    types = sorted({n["type"] for n in nodes})
    integrations = sorted({t.split(".")[-1] for t in types})
    name = str(workflow.get("name") or "Unnamed workflow")
    description = str(workflow.get("description") or "")[:2000]
    # Category text may include the title; locality must use executable nodes.
    executable = json.dumps([{k: n.get(k) for k in ("type", "parameters")} for n in nodes], ensure_ascii=False).lower()
    text = " ".join([name, description, *types]).lower()
    categories = sorted(k for k, pattern in CATEGORY_RULES.items() if re.search(pattern, text))
    credentials = sorted({k for n in nodes for k in (n.get("credentials") or {})})
    node_text = " ".join(types).lower()
    services = {s for s in CLOUD if s in node_text}
    providers = {s for s in PROVIDERS if s in executable}
    databases = {s for s in LOCAL - {"ollama", "n8n", "localhost"} if s in node_text}
    domains = set()
    dynamic = False
    findings = set()
    code_nodes, http_nodes, webhooks, shell_nodes, filesystem = [], [], [], [], []
    unsupported = []
    for n in nodes:
        typ = n["type"].lower()
        leaf = typ.split(".")[-1]
        trusted_namespace = typ.startswith(("n8n-nodes-base.", "@n8n/n8n-nodes-langchain."))
        recognized_local = trusted_namespace and (leaf in SAFE_BASE or any(s in typ for s in LOCAL - {"n8n", "localhost"})
                            or any(s in leaf for s in ("chainllm", "textclassifier", "outputparser", "memorybuffer", "agent", "toolcalculator")))
        recognized_other = trusted_namespace and (any(s in typ for s in CLOUD) or any(s in typ for s in ("httprequest", "code", "function", "executecommand", "ssh", "file")))
        if not recognized_local and not recognized_other:
            unsupported.append(n["type"])
        params = json.dumps(n.get("parameters", {}), ensure_ascii=False)
        if "code" in typ or "function" in typ:
            code_nodes.append(n["type"])
            findings.add("unreviewed_code")
        if "executecommand" in typ or "ssh" in typ:
            shell_nodes.append(n["type"])
            findings.add("command_execution")
        if any(s in typ for s in ["readwritefile", "readbinaryfile", "writebinaryfile", "localfiletrigger", "ftp"]):
            filesystem.append(n["type"])
            findings.add("filesystem_access")
        if "webhook" in typ:
            webhooks.append(n["type"])
            findings.add("webhook_input")
        if "httprequest" in typ:
            http_nodes.append(n["type"])
            url = str((n.get("parameters") or {}).get("url", ""))
            if not url or "{{" in url:
                dynamic = True
                findings.add("dynamic_http_destination")
            method = str((n.get("parameters") or {}).get("method", "GET")).upper()
            if method == "DELETE":
                findings.add("destructive_operation")
            elif method not in {"GET", "HEAD", "OPTIONS"}:
                findings.add("http_write_operation")
        for url in re.findall(r"https?://[^\s\"'<>]+", params):
            try:
                host = urlsplit(url).hostname
            except ValueError:
                host = None
            if host:
                domains.add(host.lower())
            else:
                dynamic = True
        if re.search(r"(?i)\b(delete|drop|truncate|destroy|remove)\b", str((n.get("parameters") or {}).get("operation", ""))) or re.search(r"(?i)\b(DROP\s+TABLE|TRUNCATE\s+|DELETE\s+FROM|rm\s+-rf)\b", params):
            findings.add("destructive_operation")
        if re.search(r"(?i)bearer\s+[^\s{\"']{8,}|\bsk-[a-zA-Z0-9_-]{12,}|\"(?:password|apiKey|secret|accessToken)\"\s*:\s*\"(?!\{|\$|\[|YOUR|REPLACE|example)[^\"]{8,}", params):
            findings.add("possible_embedded_secret")
        if re.search(r"(?i)\b(eval|exec)\s*\(|child_process|subprocess|os\.system", params):
            findings.add("dangerous_code_pattern")
        if contains_named_secret(n.get("parameters", {})):
            findings.add("possible_embedded_secret")
    external_domains = sorted(d for d in domains if not local_host(d))
    unknown_domains = [d for d in external_domains if not any(d == known or d.endswith("." + known) for known in KNOWN_DOMAINS)]
    if unknown_domains:
        findings.add("unreviewed_external_domain")
    if services or external_domains:
        findings.add("external_data_transfer")
    if providers - {"ollama", "lmstudio", "localai"}:
        findings.add("external_ai_provider")
    if re.search(r"(?i)email|gmail|contacts|customer|lead|invoice|crm|phone", text):
        findings.add("possible_personal_data")
    high = findings & {"command_execution", "dangerous_code_pattern", "possible_embedded_secret", "destructive_operation"}
    if unsupported:
        findings.add("unrecognized_integration")
    risk = "HIGH" if high else "UNKNOWN" if dynamic or unsupported else "MEDIUM" if findings or credentials else "LOW"
    requires_cloud = bool(services or external_domains)
    uncertain = bool(dynamic or code_nodes or unsupported or shell_nodes)
    external_api = True if services or external_domains else None if uncertain else False
    local = False if requires_cloud else None if uncertain else True
    tags = [t.get("name", "") if isinstance(t, dict) else str(t) for t in workflow.get("tags", []) or []]
    return {"name": redact(name), "description": redact(description), "nodes": types, "triggers": [t for t in types if "trigger" in t.lower() or "webhook" in t.lower() or t.endswith(".cron")],
            "integrations": integrations, "credentials": credentials, "requires_credentials": bool(credentials),
            "external_services": sorted(services | set(external_domains)), "external_domains": external_domains,
            "unknown_domains": unknown_domains, "webhooks": sorted(set(webhooks)), "code_nodes": sorted(set(code_nodes)),
            "http_requests": sorted(set(http_nodes)), "shell_nodes": sorted(set(shell_nodes)), "filesystem": sorted(set(filesystem)),
            "ai_providers": sorted(providers), "vector_stores": sorted({s for s in ("supabase", "qdrant", "pinecone", "weaviate", "chroma", "milvus", "pgvector") if s in node_text}),
            "databases": sorted(databases), "local_services": sorted({d for d in domains if local_host(d)} | (providers & {"ollama", "lmstudio", "localai"}) | databases),
            "tags": redact(tags), "categories": categories, "findings": sorted(findings), "risk": risk,
            "local_capable": local, "requires_cloud": requires_cloud if not uncertain else (True if requires_cloud else None),
            "requires_paid_service": None, "requires_external_api": external_api,
            "status": "UNSAFE" if high else "CANDIDATE", "analysis_version": "1", "verification": "STATIC_ONLY"}
