"""Taxonomie qui génère le catalogue intégré (> 1 000 définitions).

Les définitions sont produites à partir de listes de sujets × rôles. Chaque agent reçoit un prompt structuré
(`prompts.py`) alimenté par des connaissances propres à son sujet (`prompt_specialists.py`, `prompt_stacks.py`).
Pour affiner encore un agent, créez-en une version personnalisée (même `domain`, `source="custom"`) ou ajoutez un
fichier JSON (voir `catalog.load_json`).
"""
from __future__ import annotations
from .model import AgentDef, Permission
from .prompts import specialist_prompt, stack_prompt

# (nom affiché, mots-clés supplémentaires). Le premier mot-clé est toujours le nom lui-même.
_LANGS = ("Python|py;JavaScript|js;TypeScript|ts;Java;Kotlin;Swift;C|clang;C++|cpp;C#|csharp;Go|golang;Rust;PHP;"
          "Ruby;Scala;Dart;Elixir;Haskell;Lua;Perl;R|rlang;Julia;MATLAB;Bash|shell;PowerShell;Solidity;"
          "Objective-C;Fortran;COBOL;Assembly|asm;Zig;Nim;OCaml;Clojure;F#|fsharp;Groovy;Erlang")
_WEB = ("React|reactjs;Angular;Vue|vuejs;Svelte;Next.js|nextjs;Nuxt;Astro;Remix;jQuery;Tailwind CSS|tailwind;"
        "HTML and CSS|html,css;Redux;Three.js|threejs;WebAssembly|wasm;Vite;Webpack;Playwright;Cypress;Jest;"
        "pytest;Deno;Bun")
_BACK = ("FastAPI;Django;Flask;Express|expressjs;NestJS;Spring Boot|spring;Laravel;Symfony;Ruby on Rails|rails;"
         "ASP.NET|dotnet,aspnet;Node.js|nodejs,node;GraphQL;gRPC;REST API|rest,api;Phoenix;Celery;SQLAlchemy;Prisma")
_MOBILE = "Flutter;React Native;Android;iOS;SwiftUI;Jetpack Compose"
_DB = ("PostgreSQL|postgres,pg;MySQL|mariadb;SQLite;MongoDB|mongo;Redis;Elasticsearch|elastic;Cassandra;DynamoDB;"
       "Neo4j;ClickHouse;Snowflake;BigQuery;SQL Server|mssql;Oracle Database|oracle;pgvector|vectordb")
_OPS = ("Docker|container;Kubernetes|k8s;Terraform;Ansible;AWS|amazon;Azure;Google Cloud|gcp;Vercel;Cloudflare;"
        "Nginx;Linux Administration|linux,sysadmin;GitHub Actions|actions;GitLab CI|gitlab;Jenkins;Prometheus;"
        "Grafana;Kafka;RabbitMQ;Helm;ArgoCD;Pulumi;Fly.io|flyio;Supabase;Firebase;Git|github")
_DATA_ML = ("pandas;NumPy;scikit-learn|sklearn;PyTorch|torch;TensorFlow;Hugging Face|huggingface,transformers;"
            "LangChain;LlamaIndex;Apache Spark|spark;Airflow;dbt;Jupyter;OpenCV;spaCy;XGBoost;MLflow;ONNX;"
            "llama.cpp|llamacpp,gguf;Ollama;vLLM;Whisper")
_SEC = ("OWASP|owasp;OAuth and OIDC|oauth,oidc;Cryptography|crypto;Wireshark;Nmap;SAST and DAST|sast,dast;"
        "Active Directory|activedirectory;Kubernetes Hardening|k8shardening,hardening")

_STACKS = (("Languages", _LANGS, "dev"), ("Web", _WEB, "dev"), ("Backend", _BACK, "dev"), ("Mobile", _MOBILE, "dev"),
           ("Databases", _DB, "ops"), ("Cloud & DevOps", _OPS, "ops"), ("Data & ML tooling", _DATA_ML, "ops"),
           ("Security tooling", _SEC, "ops"))
_ROLES = {"dev": (("Developer", "build"), ("Code Reviewer", "review"), ("Debugging Specialist", "debug"),
                  ("Test Engineer", "test"), ("Tutor", "teach"), ("Architect", "architect")),
          "ops": (("Specialist", "build"), ("Reviewer", "review"), ("Troubleshooter", "debug"),
                  ("Tutor", "teach"), ("Architect", "architect"))}
_ROLE_PROMPT = {"build": "Tu conçois et produis des livrables corrects et maintenables.",
                "review": "Tu relis de façon critique : correction, sécurité, lisibilité, performances.",
                "debug": "Tu diagnostiques la cause racine d'un défaut avant de proposer un correctif minimal.",
                "test": "Tu écris et évalues des tests ; tu termines par 'VERDICT: PASS' ou 'VERDICT: FAIL'.",
                "teach": "Tu expliques pas à pas, avec des exemples, au niveau de l'apprenant.",
                "architect": "Tu conçois l'architecture : composants, contrats, compromis et risques."}

# Spécialistes transverses : catégorie → noms. Les domaines sensibles sont marqués plus bas.
_SPECIALISTS = {
 "Software Development": "Software Architect;Full Stack Developer;Frontend Developer;Backend Developer;API Developer;Database Engineer;DevOps Engineer;Cloud Engineer;Testing Engineer;Code Reviewer;Debugging Specialist;Refactoring Specialist;Performance Engineer;Technical Writer;Release Manager;Site Reliability Engineer;Embedded Systems Engineer;Game Developer;Compiler Engineer;Legacy Migration Specialist;Accessibility Engineer;Mobile Developer;Platform Engineer;Build Systems Engineer;Monorepo Specialist;Open Source Maintainer;API Designer;Microservices Architect;Domain-Driven Design Specialist;Code Documentation Agent",
 "Artificial Intelligence": "AI Architect;LLM Specialist;Prompt Engineer;RAG Specialist;AI Agent Engineer;Machine Learning Engineer;Computer Vision Specialist;Speech Specialist;NLP Specialist;Model Optimization Specialist;Quantization Specialist;Embedding Specialist;Fine-tuning Specialist;Evaluation Engineer;MLOps Engineer;AI Safety Reviewer;Reinforcement Learning Specialist;Time Series Forecaster;Recommender Systems Specialist;Synthetic Data Specialist",
 "Research": "Research Agent;Web Researcher;Scientific Researcher;Academic Researcher;Market Researcher;Competitive Intelligence Agent;Literature Review Agent;Patent Researcher;Fact Checker;Citation Manager;Trend Analyst;Survey Designer;Interview Synthesizer;Systematic Review Specialist",
 "Business": "Product Manager;Business Analyst;Financial Analyst;Marketing Specialist;Sales Specialist;CRM Specialist;Strategy Consultant;Entrepreneurial Advisor;Project Manager;Scrum Master;Operations Analyst;HR Specialist;Recruiter;Customer Support Agent;Customer Success Manager;Pricing Analyst;Growth Marketer;SEO Specialist;Content Strategist;Social Media Manager;Email Marketing Specialist;Brand Strategist;Procurement Specialist;Supply Chain Analyst;Accounting Assistant;Business Plan Writer;Pitch Deck Specialist;Grant Writer;Legal Operations Analyst;Compliance Analyst;Risk Analyst;Real Estate Analyst;E-commerce Specialist;Event Planner;Negotiation Coach",
 "Data": "Data Analyst;Data Scientist;Data Engineer;SQL Specialist;Data Cleaning Agent;Data Visualization Agent;Statistics Agent;Business Intelligence Analyst;ETL Developer;Data Governance Specialist;Spreadsheet Specialist;A/B Testing Analyst;Bayesian Statistician;Geospatial Analyst;Web Scraping Engineer",
 "Cybersecurity": "Security Auditor;Penetration Testing Assistant;Vulnerability Analyst;Code Security Analyst;Network Security Specialist;Security Architecture Agent;Incident Response Analyst;Threat Modeling Specialist;Privacy Engineer;Secrets Management Specialist;ISO 27001 Compliance Auditor;GDPR Specialist;Security Awareness Trainer;Cloud Security Engineer",
 "Documents": "PDF Analyst;Document Summarizer;Contract Analyzer;OCR Agent;Data Extraction Agent;Document Classification Agent;Meeting Notes Agent;Proofreader;Technical Documentation Writer;Report Writer;Form Filling Agent;Invoice Processor;Legal Document Drafter;Email Drafting Agent;Resume Reviewer;Presentation Designer;Spreadsheet Auditor;Knowledge Base Curator",
 "Multimedia": "Image Analyst;Image Generator;Video Analyst;Video Generator;Audio Analyst;Speech-to-Text Agent;Text-to-Speech Agent;Music Composition Assistant;Sound Designer;Photo Editor;Logo Designer;UI Designer;UX Researcher;Icon Designer;Storyboard Artist;Subtitle Agent;Podcast Producer;Diagram Designer;3D Modeling Assistant;Animation Planner;Thumbnail Designer",
 "Education": "Tutor;Mathematics Teacher;Programming Teacher;Language Teacher;Exam Preparation Agent;Physics Teacher;Chemistry Teacher;Biology Teacher;History Teacher;Geography Teacher;Philosophy Tutor;Economics Teacher;Curriculum Designer;Quiz Generator;Study Planner;Academic Writing Coach;Public Speaking Coach;Music Teacher;Career Counselor;Early Childhood Educator",
 "Health": "Medical Research Assistant;Medical Document Analyzer;Health Data Assistant;Nutrition Information Assistant;Fitness Planning Assistant;Clinical Trial Reviewer;Medical Terminology Explainer;Pharmacology Information Assistant;Public Health Analyst",
 "Science & Engineering": "Physicist;Chemist;Biologist;Astronomer;Geologist;Climate Scientist;Mathematician;Neuroscientist;Materials Scientist;Bioinformatics Specialist;Ecologist;Quantum Computing Specialist;Robotics Engineer;Electrical Engineer;Mechanical Engineer;Civil Engineer;Aerospace Engineer;Chemical Engineer;Energy Systems Analyst",
 "Writing & Languages": "French Translator;English Translator;Spanish Translator;German Translator;Italian Translator;Portuguese Translator;Arabic Translator;Chinese Translator;Japanese Translator;Korean Translator;Russian Translator;Hindi Translator;Turkish Translator;Dutch Translator;Polish Translator;Swahili Translator;Yoruba Translator;Creative Writer;Copywriter;Editor;Screenwriter;Novelist;Poet;Speechwriter;Journalist;Ghostwriter;Storytelling Coach",
 "Legal & Finance": "Contract Lawyer Assistant;Intellectual Property Analyst;Tax Information Assistant;Investment Research Analyst;Personal Finance Planner;Auditor;Insurance Analyst;Cryptocurrency Analyst;Economics Researcher",
 "Productivity": "Personal Assistant;Calendar Planner;Task Prioritizer;Note Taker;Email Triage Agent;Decision Analyst;Brainstorming Partner;Checklist Builder",
}
_SENSITIVE = {"Health", "Legal & Finance"}
_SENSITIVE_NAMES = ("Penetration Testing", "Vulnerability", "Incident Response")
_GUARD = ("Domaine sensible : fournis de l'information générale, signale tes limites, ne remplace jamais un "
          "professionnel qualifié et recommande une validation humaine pour toute décision importante.")
_SEC_GUARD = "Usage défensif et autorisé uniquement ; refuse toute demande visant des systèmes sans autorisation explicite."


def _slug(s: str) -> str:
    s = s.replace("++", "pp").replace("#", "sharp")
    out = "".join(c if c.isalnum() else "-" for c in s.lower())
    return "-".join(p for p in out.split("-") if p)


_ROLE_WORDS = frozenset({"learn", "review", "debug", "test", "teach", "course", "architecture"})


def _kw(name: str, extra: str, strip_roles: bool = False) -> tuple[str, ...]:
    """Mots-clés d'un sujet. Pour un sujet technique (« scikit-learn »), on retire les mots qui déclenchent
    un rôle (« learn ») afin qu'ils ne produisent pas de faux positifs."""
    from .text import tokens
    ks = set(tokens(name))
    if strip_roles:
        ks -= _ROLE_WORDS
    for e in extra.split(",") if extra else ():
        ks.update(tokens(e))
    return tuple(sorted(ks))


def _io(name: str, category: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], bool]:
    """(entrées, sorties, besoins du modèle, besoin GPU local) déduits du nom — règles explicites, testées."""
    n = name.lower()
    if "speech-to-text" in n or "subtitle" in n or "podcast" in n:
        return ("audio",), ("text",), ("chat", "speech-to-text"), False
    if "text-to-speech" in n:
        return ("text",), ("audio",), ("chat", "text-to-speech"), False
    if "audio" in n or "sound" in n or "music" in n:
        return ("audio", "text"), ("text",), ("chat", "audio"), False
    if "image generator" in n or "logo" in n or "icon" in n or "thumbnail" in n:
        return ("text",), ("image",), ("chat", "text-to-image"), True
    if "video generator" in n:
        return ("text", "image"), ("video",), ("chat", "text-to-video"), True
    if "video" in n or "storyboard" in n or "animation" in n:
        return ("video", "text"), ("text",), ("chat", "vision"), False
    if "image" in n or "photo" in n or "ocr" in n or "computer vision" in n or "ui designer" in n:
        return ("image", "text"), ("text",), ("chat", "vision"), False
    if category in ("Documents", "Legal & Finance") or "pdf" in n or "contract" in n:
        return ("document", "text"), ("text", "document"), ("chat", "long-context"), False
    if category in ("Data",) or "sql" in n or "statistic" in n:
        return ("data", "text"), ("data", "text"), ("chat", "reasoning"), False
    if category in ("Software Development", "Artificial Intelligence") or "code" in n:
        return ("text", "code"), ("code", "text"), ("chat", "code"), False
    if category in ("Research", "Science & Engineering", "Education"):
        return ("text",), ("text",), ("chat", "reasoning"), False
    return ("text",), ("text",), ("chat",), False


def _tools_for(category: str, role: str) -> tuple[tuple[str, int], ...]:
    r, w, x = int(Permission.READ), int(Permission.WRITE), int(Permission.EXECUTE)
    if category in ("Software Development", "Languages", "Web", "Backend", "Mobile") and role in ("build", "debug", "test"):
        return (("filesystem", w), ("terminal", x), ("git", r))
    if category in ("Software Development", "Languages", "Web", "Backend", "Mobile", "Databases", "Cloud & DevOps"):
        return (("filesystem", r), ("git", r))
    if category in ("Research",):
        return (("web_search", r), ("browser", r))
    if category in ("Data", "Data & ML tooling"):
        return (("filesystem", r), ("python", x))
    return ()


def build_default_catalog() -> list[AgentDef]:
    out: list[AgentDef] = []
    for category, raw, kind in _STACKS:
        for item in raw.split(";"):
            name, _, extra = item.partition("|")
            domain = _slug(name)
            for role_name, role_kind in _ROLES[kind]:
                full = f"{name} {role_name}"
                is_code = kind == "dev" or category in ("Data & ML tooling",)
                inputs, outputs = (("text", "code"), ("code", "text")) if is_code else (("text",), ("text",))
                out.append(AgentDef(
                    id=f"{domain}-{_slug(role_name)}", name=full, category=category, subcategory=role_name,
                    domain=domain, role_kind=role_kind, skills=(f"{'code' if is_code else 'ops'}.{domain}",
                                                                 f"role.{role_kind}"),
                    description=f"{role_name} spécialisé {name}. {_ROLE_PROMPT[role_kind]}",
                    keywords=_kw(name, extra, True), needs=("chat", "code") if is_code else ("chat",),
                    tools=_tools_for(category, role_kind), inputs=inputs, outputs=outputs,
                    permission_level=max([p for _, p in _tools_for(category, role_kind)] or [int(Permission.READ)]),
                    est_tokens=6000 if role_kind in ("build", "specialist") else 3500,
                    system_prompt=stack_prompt(name, role_name, role_kind, category, _tools_for(category, role_kind))))
    for category, raw in _SPECIALISTS.items():
        for name in raw.split(";"):
            domain = _slug(name)
            inputs, outputs, needs, gpu = _io(name, category)
            sensitive = category in _SENSITIVE or any(s in name for s in _SENSITIVE_NAMES)
            guard = _GUARD if category in _SENSITIVE else (_SEC_GUARD if category == "Cybersecurity" else "")
            kind = "specialist"
            tools = _tools_for(category, "specialist")
            out.append(AgentDef(
                id=f"{domain}", name=name, category=category, subcategory=category, domain=domain, role_kind=kind,
                skills=(f"{_slug(category)}.{domain}",), keywords=_kw(name, ""),
                description=f"{name} : analyse, produit et vérifie des travaux relevant de « {name} ».",
                needs=needs, tools=tools, inputs=inputs, outputs=outputs,
                permission_level=max([p for _, p in tools] or [int(Permission.READ)]),
                est_tokens=8000 if category == "Research" else 4000, needs_gpu=gpu, min_ram_gb=16.0 if gpu else 0.0,
                local_ok=True, cloud_ok=True, sensitive=sensitive,
                system_prompt=specialist_prompt(name, category, tools, guard, tester=name == "Testing Engineer")))
    return out
