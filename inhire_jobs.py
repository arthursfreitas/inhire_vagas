#!/usr/bin/env python3
"""Descobre páginas públicas de vagas do InHire e disponibiliza um frontend local.

Uso rápido:
  python3 inhire_jobs.py --discover --collect --serve
  Abra http://127.0.0.1:8000

O script usa apenas a biblioteca padrão do Python. As páginas são públicas; ele
faz requisições com concorrência limitada, respeita retry/backoff e mantém cache
local em inhire_jobs.json.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_SITEMAP = "https://carreira.inhire.com.br/page-sitemap.xml"
DEFAULT_CACHE = Path("inhire_jobs.json")
USER_AGENT = "InHireJobsResearch/1.0 (+public-job-indexer)"

# Termos editáveis (sem acentos, minúsculos); a classificação é heurística e usa
# fronteiras de palavra para evitar falsos positivos (ex.: "ios" em "negócios").
DEV_TERMS = (
    "desenvolvedor", "desenvolvedora", "developer", "dev", "software engineer", "engenheiro de software",
    "engenheira de software", "programador", "programadora", "programming", "full stack",
    "fullstack", "full-stack", "front end", "frontend", "front-end", "back end", "backend",
    "back-end", "mobile", "android", "ios", "react", "node.js", "nodejs", "java", "python",
    "php", "ruby", "kotlin", "swift", "golang", "go developer", ".net", "c#", "typescript",
    "javascript", "devops", "devsecops", "sre", "qa automation", "automacao de testes", "sdet",
    "engenheiro de dados", "engenheira de dados", "data engineer", "machine learning engineer",
    "ml engineer", "cloud engineer", "arquiteto de software", "arquiteta de software",
    "arquitetura de software", "tech lead", "analista de sistemas", "analista desenvolvedor",
    "desenvolvimento de software", "qa", "quality assurance", "analista de qualidade de software",
    "cientista de dados", "data scientist", "engenheiro de machine learning",
)

DESIGN_TERMS = (
    "designer", "ux", "ui", "ui/ux", "ux/ui", "ui ux", "ux ui", "ux writer",
    "ux writing", "ux research", "ux researcher", "pesquisador ux", "pesquisadora ux",
    "product design", "design de produto", "design system", "design grafico", "design de interface",
    "design de experiencia", "designer de experiencia", "webdesigner", "web design", "motion", "ilustrador",
    "ilustradora", "diretor de arte", "diretora de arte", "direcao de arte", "figma",
    "identidade visual", "branding", "artista visual", "artista grafico",
)

# Linguagens e frameworks: rótulo -> padrões.
LANGUAGES = {
    "Python": ("python", "django", "flask", "fastapi"),
    "Java": ("java", "spring boot", "spring"),
    "JavaScript": ("javascript", "js", "node.js", "nodejs", "node"),
    "TypeScript": ("typescript", "ts"),
    "C# / .NET": ("c#", ".net", "dotnet", "csharp", "asp.net"),
    "C / C++": ("c++", "cpp"),
    "PHP": ("php", "laravel", "symfony"),
    "Ruby": ("ruby", "rails"),
    "Go": ("golang", "go developer", "go engineer", "go lang"),
    "Kotlin": ("kotlin",),
    "Swift / iOS": ("swift", "ios"),
    "Rust": ("rust",),
    "Scala": ("scala",),
    "SQL": ("sql",),
    "React": ("react", "react native", "reactjs", "next.js", "nextjs"),
    "Angular": ("angular",),
    "Vue": ("vue", "vue.js", "vuejs", "nuxt"),
    "Flutter / Dart": ("flutter", "dart"),
}

# Ordem de exibição dos filtros de senioridade.
SENIORITY_ORDER = ("Estágio", "Trainee", "Júnior", "Pleno", "Sênior", "Especialista", "Liderança")
SENIORITY_TERMS = {
    "Estágio": ("estagio", "estagiario", "estagiaria", "intern", "internship"),
    "Trainee": ("trainee",),
    "Júnior": ("junior", "jr", "jr.", "entry level"),
    "Pleno": ("pleno", "pl", "mid level", "mid-level", "middle"),
    "Sênior": ("senior", "sr", "sr."),
    "Especialista": ("especialista", "specialist", "staff", "principal", "arquiteto", "arquiteta"),
    "Liderança": ("lider", "lead", "tech lead", "coordenador", "coordenadora", "gerente",
                  "manager", "head", "diretor", "diretora", "supervisor", "supervisora"),
}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in value if not unicodedata.combining(c)).lower()


def _compile(terms: Iterable[str]) -> re.Pattern:
    alt = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9]){'(?:' + alt + ')'}(?![a-z0-9])")


DEV_RE = _compile(DEV_TERMS)
DESIGN_RE = _compile(DESIGN_TERMS)
LANG_RES = {label: _compile(terms) for label, terms in LANGUAGES.items()}
SENIORITY_RES = {label: _compile(terms) for label, terms in SENIORITY_TERMS.items()}


ROMAN_SENIORITY = re.compile(r"(?<![a-z0-9])(iii|ii|i)\s*(?:[-|(\[].*)?$")


def classify(title: str, description: str = "") -> dict:
    """Deriva área, senioridade e linguagens. Área/senioridade vêm só do título;
    a descrição (quando coletada) refina apenas as linguagens/stack."""
    t = norm(title)
    is_dev = bool(DEV_RE.search(t))
    seniority = [label for label in SENIORITY_ORDER if SENIORITY_RES[label].search(t)]
    if not seniority:  # "Desenvolvedor II": I=Júnior, II=Pleno, III=Sênior
        m = ROMAN_SENIORITY.search(t)
        if m and is_dev:
            seniority = [{"i": "Júnior", "ii": "Pleno", "iii": "Sênior"}[m.group(1)]]
    text = f"{t} {norm(description)}"
    languages = [label for label, rx in LANG_RES.items() if rx.search(text)] if is_dev else []
    return {
        "is_development": is_dev,
        "is_design": bool(DESIGN_RE.search(t)),
        "seniority": seniority,
        "languages": languages,
    }


@dataclass
class Job:
    id: str
    title: str
    url: str
    company: str
    domain: str
    location: str = ""
    model: str = ""
    description: str = ""
    is_development: bool = False
    is_design: bool = False
    seniority: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    collected_at: str = ""
    contract: list[str] = field(default_factory=list)
    published_at: str = ""
    logo: str = ""
    tenant: str = ""

    def __post_init__(self):
        info = classify(self.title, self.description)
        self.is_development = self.is_development or info["is_development"]
        self.is_design = self.is_design or info["is_design"]
        self.seniority = self.seniority or info["seniority"]
        self.languages = self.languages or info["languages"]


class PageParser(HTMLParser):
    """Extrai links e texto sem depender de BeautifulSoup."""
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._href = ""
        self._anchor_text: list[str] = []
        self._in_anchor = False
        self._in_script = False
        self.json_ld: list[str] = []
        self._script_type = ""
        self._script_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._href = urljoin(self.base_url, attrs.get("href", ""))
            self._anchor_text = []
            self._in_anchor = True
        if tag == "script":
            self._in_script = True
            self._script_type = attrs.get("type", "")
            self._script_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_anchor:
            text = clean_text(" ".join(self._anchor_text))
            if self._href:
                self.links.append((self._href, text))
            self._in_anchor = False
        if tag == "script" and self._in_script:
            if "ld+json" in self._script_type.lower():
                self.json_ld.append("".join(self._script_text))
            self._in_script = False
            self._script_type = ""

    def handle_data(self, data):
        if self._in_script:
            self._script_text.append(data)
        else:
            text = clean_text(data)
            if text:
                self.text_parts.append(text)
                if self._in_anchor:
                    self._anchor_text.append(text)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.append("\n• ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(value: str, limit: int = 8000) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in "".join(parser.parts).splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text[:limit]


def job_slug(value: str) -> str:
    """Converte o título para o slug usado nas URLs públicas de vagas."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower().replace("&", " e ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "vaga"


def fetch(url: str, timeout: int = 20, retries: int = 2) -> tuple[int, str, str]:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
            with urlopen(req, timeout=timeout) as response:
                body = response.read(4_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
                return response.status, body, response.geturl()
        except HTTPError as exc:
            if exc.code in (404, 410):
                return exc.code, "", url
            last_error = f"HTTP {exc.code}"
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(0.6 * (2 ** attempt))
    return 0, "", last_error


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> object:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(8_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
        return json.loads(raw)


def slug_from_url(url: str) -> str | None:
    host = urlparse(url).hostname or ""
    # Algumas páginas redirecionam de empresa.inhire.app para
    # empresa.inhire.com.br. Os dois hosts usam a mesma API pública.
    m = re.fullmatch(r"([a-z0-9][a-z0-9-]*)\.inhire\.(?:app|com\.br)", host.lower())
    return m.group(1) if m else None


def candidate_urls_from_text(text: str) -> list[str]:
    """Aceita sitemap XML/Markdown ou a lista gerada na tarefa anterior."""
    urls = re.findall(r"https?://[^\s<>\"']+", text)
    slugs: set[str] = set()
    for url in urls:
        url = url.rstrip(".,)")
        path = urlparse(url).path.strip("/")
        if path.startswith("carreiras/"):
            slug = path.split("/", 1)[1].split("/", 1)[0]
        elif path.startswith("carreiras-"):
            slug = path[len("carreiras-"):].split("/", 1)[0]
        elif path.startswith("exemplo/"):
            slug = path.split("/", 1)[1].split("/", 1)[0]
        else:
            continue
        slug = re.sub(r"[^a-z0-9-]", "", slug.lower())
        if slug and slug not in {"mockup", "addons", "partner"}:
            slugs.add(slug)
    return sorted(f"https://{slug}.inhire.app/vagas" for slug in slugs)


def discover_domains(source: str = DEFAULT_SITEMAP, local_source: Path | None = None, workers: int = 12) -> list[str]:
    if local_source:
        text = local_source.read_text(encoding="utf-8")
    else:
        status, text, _ = fetch(source)
        if status != 200:
            raise RuntimeError(f"Não foi possível ler o sitemap ({status}). Use --source ou --local-source.")
    candidates = candidate_urls_from_text(text)
    # O sitemap pode conter slugs antigos; a verificação HTTP remove os inexistentes.
    valid: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, url, 15, 1): url for url in candidates}
        for future in as_completed(futures):
            url = futures[future]
            try:
                status, body, final_url = future.result()
                if status == 200 and body and "vagas" in final_url.lower():
                    valid.append(final_url.rstrip("/"))
            except Exception as exc:
                print(f"[descoberta] erro em {url}: {exc}")
    return sorted(set(valid))


def development_match(title: str, description: str = "") -> bool:
    return classify(title, description)["is_development"]


def collect_api_page(page_url: str) -> list[Job] | None:
    """Consulta a API pública usada pelo app React, em vez do HTML vazio da SPA."""
    slug = slug_from_url(page_url)
    if not slug:
        return None
    try:
        config = fetch_json(f"https://api.inhire.app/tenants/public/config/resolve/{quote(slug)}")
        tenant_id = ((config or {}).get("tenant") or {}).get("id") if isinstance(config, dict) else None
        if not tenant_id:
            return None
        records = fetch_json(
            "https://api.inhire.app/job-posts/public/pages/lean",
            {"X-Tenant": str(tenant_id)},
        )
        if not isinstance(records, list):
            return []
        company = ((config or {}).get("tenant") or {}).get("name") or slug.replace("-", " ").title()
        result = []
        for item in records:
            if not isinstance(item, dict) or not item.get("jobId"):
                continue
            job_id = str(item["jobId"])
            # O portal .app e o domínio .com.br atendem a mesma vaga; o .app é
            # mantido porque é o formato solicitado e permite candidatura.
            url = f"https://{slug}.inhire.app/vagas/{job_id}"
            title = clean_text(str(item.get("displayName") or "Vaga"))
            url = f"{url}/{job_slug(title)}"
            result.append(Job(
                id=job_id,
                title=title,
                url=url,
                company=clean_text(str(company)),
                domain=f"{slug}.inhire.app",
                is_development=development_match(title),
                tenant=str(tenant_id),
            ))
        return result
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        return None


def parse_json_ld(parser: PageParser) -> list[dict]:
    records: list[dict] = []
    for raw in parser.json_ld:
        try:
            value = json.loads(raw)
            values = value if isinstance(value, list) else [value]
            records.extend(x for x in values if isinstance(x, dict))
        except json.JSONDecodeError:
            continue
    return records


def collect_page(page_url: str) -> list[Job]:
    api_jobs = collect_api_page(page_url)
    if api_jobs is not None:
        return api_jobs
    status, body, final_url = fetch(page_url)
    if status != 200 or not body:
        return []
    parser = PageParser(final_url)
    parser.feed(body)
    slug = slug_from_url(final_url) or (urlparse(page_url).hostname or "").split(".")[0]
    company = slug.replace("-", " ").title()
    jobs: dict[str, Job] = {}

    # O portal usa links em /vagas/<id>/<slug>. A regex evita capturar a própria página /vagas.
    for href, anchor_text in parser.links:
        parsed = urlparse(href)
        if parsed.hostname and parsed.hostname != urlparse(final_url).hostname:
            continue
        path = parsed.path.rstrip("/")
        if not re.search(r"/vagas/[^/]+(?:/[^/]+)?$", path, re.I):
            continue
        title = anchor_text or unquote(path.rsplit("/", 1)[-1]).replace("-", " ").title()
        job_id = path.split("/")[-2] if path.split("/")[-2] else path.rsplit("/", 1)[-1]
        jobs[href] = Job(job_id, clean_text(title), href, company, parsed.hostname or "", is_development=development_match(title))

    # Fallback para páginas que publicam JobPosting em JSON-LD.
    for record in parse_json_ld(parser):
        if record.get("@type") not in ("JobPosting", ["JobPosting"]):
            continue
        title = clean_text(str(record.get("title", "Vaga")))
        url = record.get("url") or final_url
        if url in jobs:
            continue
        location = record.get("jobLocation", "")
        if isinstance(location, dict):
            location = location.get("address", {}).get("addressLocality", "") if isinstance(location.get("address"), dict) else ""
        jobs[url] = Job(str(record.get("identifier", {}).get("value", "")) or url, title, url, company, urlparse(url).hostname or "", clean_text(str(location)), is_development=development_match(title, str(record.get("description", ""))))
    return list(jobs.values())


WORKPLACE_LABELS = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "on-site": "Presencial", "inoffice": "Presencial"}
TECH_HINTS = re.compile(r"(?<![a-z0-9])(analista|engenheir[oa]|arquitet[oa]|tech|dados|data|sistemas|qa|produto|product|ti|cientista|especialista)(?![a-z0-9])")


def fetch_details(job: Job) -> bool:
    """Completa a vaga com descrição, local, modelo de trabalho e logo (endpoint público)."""
    if not job.tenant:
        return False
    try:
        d = fetch_json(f"https://api.inhire.app/job-posts/public/pages/{quote(job.id)}", {"X-Tenant": job.tenant})
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False
    if not isinstance(d, dict):
        return False
    job.description = html_to_text(str(d.get("description") or ""))
    job.location = clean_text(str(d.get("location") or ""))
    wp = str(d.get("workplaceType") or "").lower().replace("_", "")
    job.model = WORKPLACE_LABELS.get(wp, "")
    contract = d.get("contractType")
    job.contract = [str(c) for c in contract] if isinstance(contract, list) else []
    job.published_at = str(d.get("publishedAt") or d.get("createdAt") or "")
    job.logo = str(d.get("logo") or "")
    info = classify(job.title, job.description)
    job.languages = info["languages"]
    return True


def enrich_jobs(jobs: list[Job], mode: str, workers: int) -> None:
    if mode == "none":
        return
    if mode == "all":
        targets = jobs
    else:  # "tech": dev, design e títulos que podem ser da área de tecnologia
        targets = [j for j in jobs if j.is_development or j.is_design or TECH_HINTS.search(norm(j.title))]
    print(f"[detalhes] buscando {len(targets)} vaga(s)...")
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers * 2)) as pool:
        for ok in pool.map(fetch_details, targets):
            done += 1
            if done % 200 == 0:
                print(f"[detalhes] {done}/{len(targets)}")


def collect_jobs(domains: Iterable[str], workers: int = 8, details: str = "tech") -> list[Job]:
    jobs: list[Job] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(collect_page, url): url for url in domains}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                jobs.extend(result)
                print(f"[coleta] {i}/{len(futures)} | {futures[future]} | {len(result)} vaga(s)")
            except Exception as exc:
                print(f"[coleta] erro em {futures[future]}: {exc}")
    unique: dict[str, Job] = {}
    for job in jobs:
        unique[job.url] = job
    result = list(unique.values())
    enrich_jobs(result, details, workers)
    return sorted(result, key=lambda j: (not (j.is_development or j.is_design), j.company.lower(), j.title.lower()))


def save_json(path: Path, domains: list[str], jobs: list[Job]) -> None:
    payload = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "domains": domains, "jobs": [asdict(j) for j in jobs]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


INDEX_HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vagas InHire</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:oklch(0.965 0.004 250);--surface:#fff;--surface-2:oklch(0.975 0.004 250);
  --ink:oklch(0.22 0.02 255);--muted:oklch(0.46 0.015 255);--faint:oklch(0.6 0.012 255);
  --line:oklch(0.91 0.006 250);--line-2:oklch(0.84 0.01 250);
  --accent:oklch(0.48 0.17 262);--accent-2:oklch(0.42 0.17 262);--accent-bg:oklch(0.955 0.03 262);
  --dev:oklch(0.45 0.12 165);--dev-bg:oklch(0.95 0.04 165);
  --design:oklch(0.47 0.16 330);--design-bg:oklch(0.955 0.035 330);
  --star:oklch(0.7 0.16 75);
  --r:10px;--hdr:132px;
  font-family:"Hanken Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg);
  font-variant-numeric:tabular-nums;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
button,input,select{font:inherit;color:inherit}
button{cursor:pointer}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
svg.i{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}

/* ---- topo ---- */
.top{position:sticky;top:0;z-index:20;background:var(--surface);border-bottom:1px solid var(--line)}
.nav{display:flex;align-items:center;gap:20px;height:68px;padding:0 24px;max-width:1500px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:-.02em;white-space:nowrap}
.logo{width:34px;height:34px;border-radius:9px;background:var(--accent);color:#fff;display:grid;place-items:center;font-weight:800;font-size:17px}
.search{position:relative;flex:1;max-width:620px}
.search .i{position:absolute;left:14px;top:13px;color:var(--faint)}
.search input{width:100%;height:44px;padding:0 44px 0 42px;border:1px solid var(--line-2);border-radius:99px;background:var(--surface-2);outline:none}
.search input:focus{background:#fff;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}
.search kbd{position:absolute;right:14px;top:11px;font:inherit;font-size:12px;border:1px solid var(--line-2);border-radius:6px;padding:1px 7px;color:var(--faint);background:#fff}
.views{margin-left:auto;display:flex;gap:4px;background:var(--bg);padding:4px;border-radius:12px}
.views button{border:0;background:none;border-radius:9px;padding:0 14px;min-height:36px;font-weight:600;color:var(--muted);display:flex;align-items:center;gap:7px}
.views button.on{background:#fff;color:var(--ink);box-shadow:0 1px 2px #1018281a}
.views .n{font-size:12px;color:var(--faint);font-weight:500}
.bar{display:flex;align-items:center;gap:8px;height:56px;padding:0 24px;max-width:1500px;margin:0 auto;border-top:1px solid var(--line)}
.dds{display:flex;gap:8px;align-items:center;min-width:0;overflow:visible}
.dd{position:relative}
.ddb{display:inline-flex;align-items:center;gap:7px;height:38px;padding:0 13px;border:1px solid var(--line-2);border-radius:99px;background:#fff;font-weight:500;white-space:nowrap}
.ddb:hover{border-color:var(--muted)}
.ddb.has{border-color:var(--accent);background:var(--accent-bg);color:var(--accent-2);font-weight:600}
.ddb.open{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}
.ddb .cnt{background:var(--accent);color:#fff;border-radius:99px;font-size:12px;min-width:20px;height:20px;display:grid;place-items:center;padding:0 6px}
.ddb .i{width:15px;height:15px;color:var(--faint)}
.panel{position:absolute;top:46px;left:0;z-index:30;width:290px;background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 32px #10182822,0 2px 6px #1018280d;padding:8px}
.panel .ps{width:100%;height:38px;border:1px solid var(--line-2);border-radius:9px;padding:0 12px;margin-bottom:6px;outline:none}
.panel .ps:focus{border-color:var(--accent)}
.opts{max-height:300px;overflow:auto}
.opt{display:flex;align-items:center;gap:10px;width:100%;min-height:40px;padding:0 10px;border:0;background:none;border-radius:8px;text-align:left}
.opt:hover{background:var(--surface-2)}
.opt .box{width:18px;height:18px;border:1.6px solid var(--line-2);border-radius:5px;display:grid;place-items:center;flex:none;color:#fff}
.opt .box.r{border-radius:50%}
.opt.on .box{background:var(--accent);border-color:var(--accent)}
.opt .box .i{width:12px;height:12px;stroke-width:3;opacity:0}.opt.on .box .i{opacity:1}
.opt .l{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.opt .c{color:var(--faint);font-size:13px}
.opt.zero{color:var(--faint)}
.pfoot{display:flex;justify-content:space-between;border-top:1px solid var(--line);margin-top:6px;padding:8px 6px 2px}
.pfoot button{border:0;background:none;color:var(--accent);font-weight:600;padding:4px}
.right{margin-left:auto;display:flex;align-items:center;gap:12px}
.clear{border:0;background:none;color:var(--muted);text-decoration:underline;white-space:nowrap}
.sort{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:14px;white-space:nowrap}
.sort select{height:38px;border:1px solid var(--line-2);border-radius:99px;padding:0 12px;background:#fff;font-weight:500}

/* ---- corpo ---- */
.main{display:grid;grid-template-columns:minmax(360px,440px) minmax(0,1fr);gap:0;max-width:1500px;margin:0 auto;height:calc(100vh - var(--hdr))}
.pane{overflow:auto;min-height:0}
.listpane{border-right:1px solid var(--line);background:var(--bg);padding:16px 16px 28px 24px}
.lhead{display:flex;justify-content:space-between;align-items:baseline;margin:0 2px 12px;color:var(--muted);font-size:14px}
.lhead b{color:var(--ink);font-size:15px}
.card{position:relative;display:grid;grid-template-columns:48px minmax(0,1fr) auto;gap:12px;padding:14px;margin-bottom:8px;background:#fff;border:1px solid var(--line);border-radius:12px;cursor:pointer}
.card:hover{border-color:var(--line-2);box-shadow:0 2px 8px #1018280d}
.card.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);background:oklch(0.985 0.012 262)}
.card.hid{opacity:.6}
.av{position:relative;width:48px;height:48px;border-radius:11px;display:grid;place-items:center;font-weight:700;font-size:17px;overflow:hidden;border:1px solid var(--line);background:#fff}
.av img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:6px;background:#fff}
.av.xl{width:68px;height:68px;border-radius:14px;font-size:24px}
.ct{font-weight:700;font-size:15.5px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card.seen .ct{color:var(--muted);font-weight:600}
.co{color:var(--ink);font-size:14px;margin-top:2px}
.cm{display:flex;align-items:center;gap:5px;color:var(--muted);font-size:13px;margin-top:2px;flex-wrap:wrap}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.tag{border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600;background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.tag.dev{background:var(--dev-bg);color:var(--dev);border-color:transparent}
.tag.design{background:var(--design-bg);color:var(--design);border-color:transparent}
.tag.lang{background:var(--accent-bg);color:var(--accent-2);border-color:transparent}
.tag.new{background:var(--accent);color:#fff;border-color:transparent}
.cside{display:flex;flex-direction:column;align-items:flex-end;gap:6px;font-size:12px;color:var(--faint);white-space:nowrap}
.iconbtn{width:36px;height:36px;display:grid;place-items:center;border:0;background:none;border-radius:9px;color:var(--faint)}
.iconbtn:hover{background:var(--bg);color:var(--ink)}
.iconbtn.on{color:var(--star)}.iconbtn.on .i{fill:var(--star)}
.more{display:block;width:100%;height:44px;border:1px solid var(--line-2);border-radius:var(--r);background:#fff;font-weight:600;margin-top:6px}
.more:hover{border-color:var(--accent);color:var(--accent)}

.detailpane{background:#fff;padding:0}
.det{max-width:860px;padding:32px 40px 60px}
.dh{display:flex;gap:18px;align-items:flex-start}
.dh h1{margin:0;font-size:26px;line-height:1.2;letter-spacing:-.02em;font-weight:800}
.dh .co2{margin-top:6px;font-size:16px;font-weight:600}
.dh .co2 button{border:0;background:none;padding:0;color:var(--accent);font-weight:600}
.dh .co2 button:hover{text-decoration:underline}
.facts{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;color:var(--muted);font-size:14px}
.facts span{display:inline-flex;align-items:center;gap:6px}
.facts .i{width:16px;height:16px;color:var(--faint)}
.acts{display:flex;gap:10px;margin:24px 0 0;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:8px;height:46px;padding:0 22px;border-radius:99px;font-weight:700;border:1.5px solid var(--line-2);background:#fff;white-space:nowrap}
.btn:hover{border-color:var(--ink);text-decoration:none}
.btn.pri{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.pri:hover{background:var(--accent-2);border-color:var(--accent-2)}
.btn.on{border-color:var(--star);color:oklch(0.5 0.12 75)}.btn.on .i{fill:var(--star);stroke:var(--star)}
.sec{margin-top:34px;padding-top:26px;border-top:1px solid var(--line)}
.sec h2{margin:0 0 14px;font-size:17px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px 20px}
.grid dt{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--faint);margin-bottom:4px}
.grid dd{margin:0;font-weight:500;display:flex;flex-wrap:wrap;gap:5px}
.desc{white-space:pre-line;font-size:15.5px;line-height:1.65;color:oklch(0.3 0.015 255);max-width:70ch}
.note{background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px;color:var(--muted);font-size:14px}
.sk{height:14px;border-radius:7px;margin:10px 0;background:linear-gradient(90deg,var(--line),var(--surface-2),var(--line));background-size:200% 100%;animation:sh 1.2s infinite}
@keyframes sh{to{background-position:-200% 0}}
.mini{display:flex;flex-direction:column}
.mini button{display:flex;justify-content:space-between;gap:12px;text-align:left;border:0;border-top:1px solid var(--line);background:none;padding:12px 4px;min-height:44px}
.mini button:first-child{border-top:0}
.mini button:hover{background:var(--surface-2)}
.mini b{font-weight:600}.mini span{color:var(--muted);font-size:13px;white-space:nowrap}
.empty{margin:60px auto;max-width:380px;text-align:center;color:var(--muted)}
.empty b{display:block;color:var(--ink);font-size:18px;margin-bottom:6px}
.empty button{margin-top:14px}
.back{display:none}
.banner{background:#fff8e6;border-bottom:1px solid #f1dfaa;padding:8px 24px;font-size:13px;color:#6b5200;text-align:center}

@media(max-width:980px){
  :root{--hdr:0px}
  html,body{height:auto}
  .nav{height:auto;flex-wrap:wrap;padding:12px 16px;gap:10px}
  .search{order:3;flex-basis:100%;max-width:none}
  .views{margin-left:auto}.views button{padding:0 10px}
  .bar{padding:8px 16px;height:auto;overflow-x:auto}
  .dds{flex-wrap:nowrap}
  .panel{position:fixed;left:12px;right:12px;top:auto;bottom:12px;width:auto;max-height:70vh}
  .right .sort span{display:none}
  .main{display:block;height:auto}
  .pane{overflow:visible}
  .listpane{border:0;padding:12px 12px 30px}
  .detailpane{display:none;position:fixed;inset:0;z-index:40;overflow:auto}
  body.showdet .detailpane{display:block}
  body.showdet{overflow:hidden}
  .det{padding:16px 18px 80px}
  .back{display:inline-flex;align-items:center;gap:6px;border:0;background:none;font-weight:600;color:var(--accent);height:44px;padding:0;margin-bottom:6px}
  .dh h1{font-size:21px}
  .acts .btn{flex:1;justify-content:center}
  .kb{display:none}
}
@media(prefers-reduced-motion:reduce){.sk{animation:none}}
</style>
</head>
<body>
<div class="top">
  <div id="banner"></div>
  <div class="nav">
    <div class="brand"><span class="logo">V</span>Vagas InHire</div>
    <label class="search"><svg class="i" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="search" placeholder="Buscar por cargo, empresa, local ou tecnologia" aria-label="Buscar vagas" autocomplete="off"><kbd class="kb">/</kbd></label>
    <div class="views" id="views" role="tablist"></div>
  </div>
  <div class="bar">
    <div class="dds" id="dds"></div>
    <div class="right">
      <button class="clear" id="clear" type="button" hidden>Limpar filtros</button>
      <label class="sort"><span>Ordenar</span><select id="sort" aria-label="Ordenar">
        <option value="new">Mais recentes</option><option value="company">Empresa (A–Z)</option><option value="title">Cargo (A–Z)</option></select></label>
    </div>
  </div>
</div>
<div class="main">
  <section class="pane listpane" id="listpane" aria-label="Lista de vagas"></section>
  <section class="pane detailpane" id="detail" aria-label="Detalhes da vaga"></section>
</div>
<script>
const $=id=>document.getElementById(id);
const SEN=['Estágio','Trainee','Júnior','Pleno','Sênior','Especialista','Liderança'], MODELS=['Remoto','Híbrido','Presencial'];
const AREAS=[['tech','Tecnologia e Design'],['dev','Desenvolvimento'],['design','Design / UX'],['all','Todas as áreas']];
const STEP=30;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
const store={get(k,d){try{return JSON.parse(localStorage.getItem(k))??d}catch(e){return d}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}};
const IC={
 search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',chev:'<path d="m6 9 6 6 6-6"/>',check:'<path d="m5 12 5 5L20 7"/>',
 star:'<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
 eyeoff:'<path d="M3 3l18 18M10.6 6.2A9.8 9.8 0 0 1 12 6c5 0 8.5 4 9.5 6a14 14 0 0 1-2.6 3.4M6.5 7.6A14 14 0 0 0 2.5 12C3.5 14 7 18 12 18c1.4 0 2.7-.3 3.8-.8"/>',
 undo:'<path d="M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3"/>',pin:'<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
 home:'<path d="M3 11l9-8 9 8M5 10v10h14V10"/>',doc:'<path d="M7 3h7l5 5v13H7zM14 3v5h5"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 ext:'<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',back:'<path d="M15 6l-6 6 6 6"/>'};
const ic=n=>`<svg class="i" viewBox="0 0 24 24">${IC[n]}</svg>`;
const store2={saved:new Set(store.get('inhire.saved',[])),hidden:new Set(store.get('inhire.hidden',[])),seen:new Set(store.get('inhire.seen',[]))};
const persist=()=>{for(const k in store2)store.set('inhire.'+k,[...store2[k]])};

let jobs=[],byId=new Map(),logos={},fresh=new Set(),descCache={};
let S={q:'',area:'tech',sen:[],lang:[],model:[],company:'',sort:'new',view:'all',job:''},limit=STEP,openDd=null,ddq='';

/* ---------- URL ---------- */
function readUrl(){const p=new URLSearchParams(location.search),l=k=>(p.get(k)||'').split('|').filter(Boolean);
 S.q=p.get('q')||'';S.area=p.get('area')||'tech';S.sen=l('sen');S.lang=l('lang');S.model=l('model');S.company=p.get('company')||'';S.sort=p.get('sort')||'new';S.view=p.get('view')||'all';S.job=p.get('job')||''}
function writeUrl(){const p=new URLSearchParams(),d={area:'tech',sort:'new',view:'all'};
 for(const k of ['q','area','company','sort','view','job'])if(S[k]&&S[k]!==d[k])p.set(k,S[k]);
 for(const k of ['sen','lang','model'])if(S[k].length)p.set(k,S[k].join('|'));
 try{history.replaceState(null,'',p.toString()?'?'+p:location.pathname)}catch(e){}}

/* ---------- filtros ---------- */
function match(j,skip){
 if(skip!=='area'){const a=S.area;if(!(a==='all'||(a==='tech'&&(j.is_development||j.is_design))||(a==='dev'&&j.is_development)||(a==='design'&&j.is_design)))return false}
 if(skip!=='sen'&&S.sen.length&&!S.sen.some(s=>(j.seniority||[]).includes(s)))return false;
 if(skip!=='lang'&&S.lang.length&&!S.lang.some(l=>(j.languages||[]).includes(l)))return false;
 if(skip!=='model'&&S.model.length&&!S.model.includes(j.model))return false;
 if(skip!=='company'&&S.company&&j.company!==S.company)return false;
 const q=norm(S.q.trim());if(q&&!(j._s||(j._s=norm(j.title+' '+j.company+' '+(j.location||'')+' '+(j.languages||[]).join(' ')))).includes(q))return false;
 return true}
const inView=j=>S.view==='saved'?store2.saved.has(j.id):S.view==='hidden'?store2.hidden.has(j.id):!store2.hidden.has(j.id);
const pool=skip=>jobs.filter(j=>inView(j)&&match(j,skip));
function counts(key,skip){const c={};pool(skip).forEach(j=>{(Array.isArray(j[key])?j[key]:[j[key]]).forEach(v=>{if(v)c[v]=(c[v]||0)+1})});return c}
function visible(){const xs=pool();const by=f=>(a,b)=>f(a).localeCompare(f(b),'pt-BR');
 if(S.sort==='company')xs.sort(by(j=>j.company+j.title));else if(S.sort==='title')xs.sort(by(j=>j.title+j.company));
 else xs.sort((a,b)=>(b.published_at||'').localeCompare(a.published_at||'')||(fresh.has(b.id)-fresh.has(a.id)));
 return xs}

/* ---------- util ---------- */
function ago(iso){if(!iso)return'';const d=(Date.now()-new Date(iso))/864e5;if(isNaN(d))return'';
 if(d<1)return'hoje';if(d<2)return'ontem';if(d<30)return`há ${Math.floor(d)} dias`;if(d<60)return'há 1 mês';if(d<365)return`há ${Math.floor(d/30)} meses`;return'há mais de 1 ano'}
const hue=s=>{let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))%360;return h};
function avatar(company,cls=''){const h=hue(company),ini=company.replace(/[^\p{L}\p{N} ]/gu,'').split(' ').filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()||'?',lg=logos[company];
 return `<div class="av ${cls}" style="background:oklch(0.95 0.035 ${h});color:oklch(0.4 0.1 ${h})">${ini}${lg?`<img src="${esc(lg)}" alt="" loading="lazy" onerror="this.remove()">`:''}</div>`}
const tagsOf=(j,max=4)=>{const t=[];if(fresh.has(j.id))t.push('<span class="tag new">Nova</span>');if(j.is_development)t.push('<span class="tag dev">Desenvolvimento</span>');if(j.is_design)t.push('<span class="tag design">Design / UX</span>');
 (j.seniority||[]).forEach(s=>t.push(`<span class="tag">${esc(s)}</span>`));(j.languages||[]).slice(0,max).forEach(l=>t.push(`<span class="tag lang">${esc(l)}</span>`));return t.join('')};

/* ---------- topo: views + dropdowns ---------- */
function renderViews(){const n={all:jobs.filter(j=>!store2.hidden.has(j.id)&&match(j)).length,saved:store2.saved.size,hidden:store2.hidden.size};
 $('views').innerHTML=[['all','Vagas'],['saved','Salvas'],['hidden','Ocultas']].map(([v,l])=>`<button type="button" role="tab" aria-selected="${S.view===v}" class="${S.view===v?'on':''}" data-view="${v}">${l}${v!=='all'?` <span class="n">${n[v]}</span>`:''}</button>`).join('')}
function ddDef(){
 const cs=counts('seniority','sen'),cl=counts('languages','lang'),cm=counts('model','model'),cc=counts('company','company');
 const ac={all:0,tech:0,dev:0,design:0},base=jobs.filter(j=>inView(j)&&match(j,'area'));
 base.forEach(j=>{ac.all++;if(j.is_development||j.is_design)ac.tech++;if(j.is_development)ac.dev++;if(j.is_design)ac.design++});
 const langs=[...new Set([...Object.keys(cl),...S.lang])].sort((a,b)=>(cl[b]||0)-(cl[a]||0)||a.localeCompare(b));
 const comps=[...new Set([...Object.keys(cc),...(S.company?[S.company]:[])])].sort((a,b)=>(cc[b]||0)-(cc[a]||0)||a.localeCompare(b,'pt-BR'));
 return[
  {k:'area',label:'Área',single:true,val:S.area==='tech'?[]:[S.area],opts:AREAS.map(([v,l])=>({v,l,c:ac[v]}))},
  {k:'sen',label:'Senioridade',val:S.sen,opts:SEN.map(v=>({v,l:v,c:cs[v]||0}))},
  {k:'lang',label:'Linguagem',val:S.lang,search:true,opts:langs.map(v=>({v,l:v,c:cl[v]||0}))},
  {k:'model',label:'Modelo',val:S.model,opts:MODELS.map(v=>({v,l:v,c:cm[v]||0}))},
  {k:'company',label:'Empresa',single:true,search:true,val:S.company?[S.company]:[],opts:comps.map(v=>({v,l:v,c:cc[v]||0}))}]}
function optsHtml(d,q){const nq=norm(q);let xs=d.opts.filter(o=>!nq||norm(o.l).includes(nq));const total=xs.length;xs=xs.slice(0,60);
 return xs.map(o=>{const on=d.val.includes(o.v)||(d.k==='area'&&d.val.length===0&&o.v==='tech');
  return `<button type="button" class="opt${on?' on':''}${o.c===0&&!on?' zero':''}" data-opt="${d.k}" data-v="${esc(o.v)}"><span class="box${d.single?' r':''}">${ic('check')}</span><span class="l">${esc(o.l)}</span><span class="c">${o.c}</span></button>`}).join('')
  +(total>60?`<div class="note" style="margin:6px">Mostrando 60 de ${total}. Refine a busca.</div>`:'')||'<div class="note" style="margin:6px">Nada encontrado.</div>'}
function renderDds(){
 $('dds').innerHTML=ddDef().map(d=>{const n=d.val.length,open=openDd===d.k,label=d.single&&n?(d.opts.find(o=>o.v===d.val[0])||{l:d.val[0]}).l:d.label;
  return `<div class="dd"><button type="button" class="ddb${n?' has':''}${open?' open':''}" data-dd="${d.k}" aria-expanded="${open}">${esc(label)}${!d.single&&n?` <span class="cnt">${n}</span>`:''}${ic('chev')}</button>
  ${open?`<div class="panel" role="dialog">${d.search?`<input class="ps" data-ps="${d.k}" placeholder="Buscar ${d.label.toLowerCase()}" value="${esc(ddq)}" autocomplete="off">`:''}<div class="opts">${optsHtml(d,ddq)}</div>
  ${n&&!(d.k==='area')?`<div class="pfoot"><button type="button" data-reset="${d.k}">Limpar</button></div>`:''}</div>`:''}</div>`}).join('');
 const any=S.sen.length||S.lang.length||S.model.length||S.company||S.q||S.area!=='tech';$('clear').hidden=!any;
 const ps=document.querySelector('.ps');if(ps&&document.activeElement===document.body)ps.focus()}

/* ---------- lista ---------- */
function card(j){const isS=store2.saved.has(j.id),isH=store2.hidden.has(j.id),loc=[j.location,j.model].filter(Boolean);
 return `<article class="card${S.job===j.id?' sel':''}${store2.seen.has(j.id)?' seen':''}${isH?' hid':''}" data-sel="${esc(j.id)}" tabindex="0">
  ${avatar(j.company)}
  <div><div class="ct">${esc(j.title)}</div><div class="co">${esc(j.company)}</div>${loc.length?`<div class="cm">${loc.map(esc).join(' · ')}</div>`:''}<div class="tags">${tagsOf(j,3)}</div></div>
  <div class="cside"><button class="iconbtn${isS?' on':''}" type="button" data-save="${esc(j.id)}" aria-label="${isS?'Remover das salvas':'Salvar vaga'}" aria-pressed="${isS}">${ic('star')}</button><span>${ago(j.published_at)}</span></div></article>`}
function renderList(xs){
 const shown=xs.slice(0,limit);
 $('listpane').innerHTML=`<div class="lhead"><span><b>${xs.length.toLocaleString('pt-BR')}</b> vaga${xs.length===1?'':'s'}</span><span>${S.view==='saved'?'Salvas':S.view==='hidden'?'Ocultas':''}</span></div>`+
  (shown.length?shown.map(card).join('')+(xs.length>limit?`<button class="more" type="button" data-more>Mostrar mais ${Math.min(STEP,xs.length-limit)} de ${(xs.length-limit).toLocaleString('pt-BR')}</button>`:''):emptyHtml())}
function emptyHtml(){const f=S.q||S.sen.length||S.lang.length||S.model.length||S.company||S.area!=='tech';
 if(S.view==='saved')return'<div class="empty"><b>Nenhuma vaga salva</b>Clique na estrela de uma vaga para guardá-la aqui.</div>';
 if(S.view==='hidden')return'<div class="empty"><b>Nenhuma vaga oculta</b>Vagas que você ocultar ficam aqui, caso queira restaurá-las.</div>';
 if(!jobs.length)return'<div class="empty"><b>Nenhuma vaga carregada</b>Rode <code>python3 inhire_jobs.py --discover --collect</code> e recarregue a página.</div>';
 return`<div class="empty"><b>Nenhuma vaga encontrada</b>${f?'Tente remover algum filtro ou ampliar a busca.':''}${f?'<br><button class="btn" type="button" data-clearall>Limpar filtros</button>':''}</div>`}

/* ---------- detalhe ---------- */
function renderDetail(){const j=byId.get(S.job);
 if(!j){$('detail').innerHTML='<div class="empty"><b>Selecione uma vaga</b>Os detalhes aparecem aqui.</div>';return}
 const isS=store2.saved.has(j.id),isH=store2.hidden.has(j.id);
 const facts=[j.location&&`<span>${ic('pin')}${esc(j.location)}</span>`,j.model&&`<span>${ic('home')}${esc(j.model)}</span>`,(j.contract||[]).length&&`<span>${ic('doc')}${esc(j.contract.join(', '))}</span>`,j.published_at&&`<span>${ic('clock')}Publicada ${ago(j.published_at)}</span>`].filter(Boolean).join('');
 const others=jobs.filter(x=>x.company===j.company&&x.id!==j.id&&!store2.hidden.has(x.id)&&(x.is_development||x.is_design||S.area==='all')).slice(0,6);
 const dl=[['Área',[j.is_development&&'<span class="tag dev">Desenvolvimento</span>',j.is_design&&'<span class="tag design">Design / UX</span>'].filter(Boolean).join('')||'<span style="color:var(--faint)">Não identificada</span>'],
  ['Senioridade',(j.seniority||[]).map(s=>`<span class="tag">${esc(s)}</span>`).join('')||'<span style="color:var(--faint)">Não informada</span>'],
  ['Modelo',j.model?esc(j.model):'<span style="color:var(--faint)">Não informado</span>']];
 if((j.languages||[]).length)dl.push(['Tecnologias',j.languages.map(l=>`<span class="tag lang">${esc(l)}</span>`).join('')]);
 $('detail').scrollTop=0;
 $('detail').innerHTML=`<div class="det"><button class="back" type="button" data-back>${ic('back')}Voltar para a lista</button>
  <div class="dh">${avatar(j.company,'xl')}<div style="min-width:0"><h1>${esc(j.title)}</h1>
   <div class="co2"><button type="button" data-company="${esc(j.company)}" title="Ver vagas desta empresa">${esc(j.company)}</button></div><div class="facts">${facts}</div></div></div>
  <div class="acts"><a class="btn pri" href="${esc(j.url)}" target="_blank" rel="noopener" data-open="${esc(j.id)}">Candidatar-se ${ic('ext')}</a>
   <button class="btn${isS?' on':''}" type="button" data-save="${esc(j.id)}" aria-pressed="${isS}">${ic('star')}${isS?'Salva':'Salvar'}</button>
   <button class="btn" type="button" data-hide="${esc(j.id)}">${ic(isH?'undo':'eyeoff')}${isH?'Restaurar':'Ocultar'}</button></div>
  <div class="sec"><h2>Resumo</h2><dl class="grid">${dl.map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl></div>
  <div class="sec"><h2>Sobre a vaga</h2><div id="desc">${j.has_description?'<div class="sk" style="width:90%"></div><div class="sk" style="width:80%"></div><div class="sk" style="width:86%"></div><div class="sk" style="width:60%"></div>':`<div class="note">A descrição completa está na página da vaga. <a href="${esc(j.url)}" target="_blank" rel="noopener" data-open="${esc(j.id)}">Abrir no site da empresa</a></div>`}</div></div>
  ${others.length?`<div class="sec"><h2>Mais vagas em ${esc(j.company)}</h2><div class="mini">${others.map(o=>`<button type="button" data-sel="${esc(o.id)}"><b>${esc(o.title)}</b><span>${esc(o.location||o.model||'')}</span></button>`).join('')}</div></div>`:''}</div>`;
 if(j.has_description)loadDesc(j)}
function loadDesc(j){const put=t=>{if(S.job!==j.id)return;$('desc').innerHTML=t?`<div class="desc">${esc(t)}</div>`:`<div class="note">Sem descrição disponível. <a href="${esc(j.url)}" target="_blank" rel="noopener">Abrir no site da empresa</a></div>`};
 if(j.id in descCache)return put(descCache[j.id]);
 fetch('/api/job?id='+encodeURIComponent(j.id)).then(r=>r.json()).then(x=>{descCache[j.id]=x.description||'';put(descCache[j.id])}).catch(()=>put(''))}

/* ---------- render geral ---------- */
function render(opts={}){
 const xs=visible();
 if(!byId.has(S.job)||!xs.some(x=>x.id===S.job)){if(!opts.keepJob){const first=window.innerWidth>980?xs[0]:null;S.job=first?first.id:''}}
 writeUrl();renderViews();renderDds();renderList(xs);renderDetail();$('sort').value=S.sort;document.body.classList.toggle('showdet',!!S.job&&opts.showDetail===true)}
function select(id,mobileOpen=true){S.job=id;store2.seen.add(id);persist();const m=window.innerWidth<=980;
 writeUrl();renderList(visible());renderDetail();document.body.classList.toggle('showdet',m&&mobileOpen)}

/* ---------- eventos ---------- */
const toggle=(a,v)=>a.includes(v)?a.filter(x=>x!==v):a.concat(v);
const reset=()=>{Object.assign(S,{q:'',area:'tech',sen:[],lang:[],model:[],company:''});$('q').value='';limit=STEP};
document.addEventListener('click',e=>{
 const t=e.target.closest('[data-dd],[data-opt],[data-reset],[data-view],[data-save],[data-hide],[data-open],[data-sel],[data-more],[data-clearall],[data-company],[data-back]');
 if(!t){if(openDd&&!e.target.closest('.panel')){openDd=null;ddq='';renderDds()}return}
 const d=t.dataset;
 if(d.dd!==undefined){openDd=openDd===d.dd?null:d.dd;ddq='';renderDds();return}
 if(d.opt){const k=d.opt,v=d.v;if(k==='area'){S.area=v;openDd=null}else if(k==='company'){S.company=S.company===v?'':v;openDd=null}else S[k]=toggle(S[k],v);limit=STEP;ddq='';render();return}
 if(d.reset){const k=d.reset;if(Array.isArray(S[k]))S[k]=[];else S[k]='';limit=STEP;openDd=null;render();return}
 if(d.view){S.view=d.view;limit=STEP;render();return}
 if(d.save){const id=d.save;store2.saved.has(id)?store2.saved.delete(id):store2.saved.add(id);persist();e.stopPropagation();render({keepJob:true,showDetail:document.body.classList.contains('showdet')});return}
 if(d.hide){const id=d.hide;store2.hidden.has(id)?store2.hidden.delete(id):store2.hidden.add(id);persist();S.job='';render();return}
 if(d.open!==undefined){store2.seen.add(d.open);persist();return}
 if(d.sel){select(d.sel);return}
 if(d.more!==undefined){limit+=STEP;renderList(visible());return}
 if(d.clearall!==undefined){reset();render();return}
 if(d.company){S.company=d.company;S.area='all';S.view='all';limit=STEP;render();return}
 if(d.back!==undefined){document.body.classList.remove('showdet');return}
});
document.addEventListener('input',e=>{if(e.target.dataset&&e.target.dataset.ps){ddq=e.target.value;const d=ddDef().find(x=>x.k===e.target.dataset.ps);e.target.parentNode.querySelector('.opts').innerHTML=optsHtml(d,ddq)}});
$('q').addEventListener('input',e=>{S.q=e.target.value;limit=STEP;clearTimeout(window._t);window._t=setTimeout(()=>render(),150)});
$('sort').addEventListener('change',e=>{S.sort=e.target.value;render()});
$('clear').onclick=()=>{reset();render()};
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&openDd){openDd=null;ddq='';renderDds();return}
 const typing=/input|select|textarea/i.test(document.activeElement.tagName);if(typing||e.metaKey||e.ctrlKey)return;
 if(e.key==='/'){e.preventDefault();$('q').focus();return}
 const xs=visible().slice(0,limit),i=xs.findIndex(x=>x.id===S.job);
 if(e.key==='j'||e.key==='ArrowDown'){e.preventDefault();if(xs[i+1]){select(xs[i+1].id,false);document.querySelector('.card.sel')?.scrollIntoView?.({block:'nearest'})}}
 if(e.key==='k'||e.key==='ArrowUp'){e.preventDefault();if(xs[i-1]){select(xs[i-1].id,false);document.querySelector('.card.sel')?.scrollIntoView?.({block:'nearest'})}}
 if(e.key==='s'&&S.job){store2.saved.has(S.job)?store2.saved.delete(S.job):store2.saved.add(S.job);persist();render({keepJob:true})}
 if(e.key==='Enter'&&document.activeElement.classList.contains('card'))select(document.activeElement.dataset.sel);
});

/* ---------- dados ---------- */
function demo(){const cs=['Acme Pay','Nuvem Labs','Orbita','Casa Verde','Praxis'],ts=[['Desenvolvedor Python Sênior',1,0,['Sênior'],['Python']],['Product Designer UX/UI Pleno',0,1,['Pleno'],[]],['Engenheira de Software Java Jr',1,0,['Júnior'],['Java']],['Desenvolvedor Front-end React',1,0,[],['React','TypeScript']],['UX Researcher',0,1,[],[]],['Tech Lead Node.js',1,0,['Liderança'],['JavaScript']]];
 return Array.from({length:60},(_,i)=>{const t=ts[i%ts.length];return{id:'d'+i,title:t[0],url:'#',company:cs[i%5],location:i%3?'São Paulo, SP, BR':'Curitiba, PR, BR',model:['Remoto','Híbrido','Presencial'][i%3],contract:['CLT'],published_at:new Date(Date.now()-i*864e5*2).toISOString(),is_development:!!t[1],is_design:!!t[2],seniority:t[3],languages:t[4],has_description:false}})}
function init(data,demoMode){
 jobs=data;jobs.forEach(j=>{byId.set(j.id,j);if(j.logo&&!logos[j.company])logos[j.company]=j.logo});
 const known=new Set(store.get('inhire.known',[]));if(known.size)jobs.forEach(j=>{if(!known.has(j.id))fresh.add(j.id)});store.set('inhire.known',jobs.map(j=>j.id));
 if(demoMode)$('banner').innerHTML='<div class="banner">Dados de demonstração. Rode <b>python3 inhire_jobs.py --serve</b> para ver as vagas reais.</div>';
 readUrl();$('q').value=S.q;render()}
$('listpane').innerHTML='<div class="card"><div class="av"></div><div><div class="sk" style="width:80%"></div><div class="sk" style="width:50%"></div></div></div>'.repeat(5);
fetch('/api/jobs').then(r=>{if(!r.ok)throw 0;return r.json()}).then(x=>init(x.jobs||[],false)).catch(()=>init(demo(),true));
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    cache_path = DEFAULT_CACHE
    _cache: dict = {"mtime": None, "payload": None}

    def _payload(self) -> dict:
        try:
            mtime = self.cache_path.stat().st_mtime
        except FileNotFoundError:
            return {"jobs": [], "domains": [], "error": "Execute --discover --collect primeiro."}
        cache = Handler._cache
        if cache["mtime"] != mtime:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            for j in payload.get("jobs", []):  # reclassifica com as regras atuais, sem recoletar
                j.update(classify(j.get("title", ""), j.get("description", "")))
            cache["mtime"], cache["payload"] = mtime, payload
        return cache["payload"]

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/":
            self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode()); return
        if parsed.path == "/api/jobs":
            payload = self._payload()
            jobs = payload.get("jobs", [])
            if qs.get("development", [""])[0] in ("1", "true"):
                jobs = [j for j in jobs if j.get("is_development")]
            if qs.get("design", [""])[0] in ("1", "true"):
                jobs = [j for j in jobs if j.get("is_design")]
            # A lista não carrega descrições (pesadas); elas vêm de /api/job sob demanda.
            slim = [{**{k: v for k, v in j.items() if k not in ("description", "tenant")}, "has_description": bool(j.get("description"))} for j in jobs]
            self._json({"updated_at": payload.get("updated_at"), "jobs": slim, "domains_count": len(payload.get("domains", []))}); return
        if parsed.path == "/api/job":
            job_id = qs.get("id", [""])[0]
            job = next((j for j in self._payload().get("jobs", []) if j.get("id") == job_id), None)
            if job is None:
                self.send_error(404); return
            self._json({"id": job_id, "description": job.get("description", "")}); return
        self.send_error(404)

    def _send(self, status, ctype, body):
        self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _json(self, value):
        self._send(200, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode())

    def log_message(self, fmt, *args): print(f"[server] {self.address_string()} - {fmt%args}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--discover", action="store_true", help="descobre e valida os subdomínios")
    ap.add_argument("--collect", action="store_true", help="coleta as vagas das páginas descobertas")
    ap.add_argument("--source", default=DEFAULT_SITEMAP, help="sitemap ou arquivo URL de origem")
    ap.add_argument("--local-source", type=Path, help="usa um arquivo local, como empresas-inhire.md")
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--details", choices=("tech", "all", "none"), default="tech",
                    help="busca descrição/local/modelo de trabalho: só vagas de tecnologia (padrão), todas ou nenhuma")
    ap.add_argument("--serve", action="store_true", help="inicia o frontend local")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    domains = []
    if args.discover or args.collect:
        print("[descoberta] lendo fonte...")
        domains = discover_domains(args.source, args.local_source, args.workers)
        print(f"[descoberta] {len(domains)} domínio(s) válido(s)")
    if args.collect:
        jobs = collect_jobs(domains, args.workers, args.details)
        save_json(args.cache, domains, jobs)
        print(f"[resultado] {len(jobs)} vaga(s), {sum(j.is_development for j in jobs)} de desenvolvimento, {sum(j.is_design for j in jobs)} de design/UX")
    if args.serve:
        Handler.cache_path = args.cache
        server = ThreadingHTTPServer((args.host, args.port), Handler)
        print(f"[frontend] http://{args.host}:{args.port} (Ctrl+C para sair)")
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()
    elif not (args.discover or args.collect):
        ap.print_help()

if __name__ == "__main__": main()
