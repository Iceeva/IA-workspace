from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://aiw:aiw@localhost:5432/aiw"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str
    jwt_refresh_secret: str
    allow_private_provider_urls: bool = False  # true pour un hébergement local (Ollama sur localhost, etc.)
    encryption_key: str = ""  # clés AES (séparées par des virgules, la première chiffre) ; sinon dérivée de JWT_SECRET
    access_ttl_min: int = 15
    refresh_ttl_days: int = 14
    cors_origins: str = "http://localhost:4200"
    default_model: str = "anthropic/claude-sonnet-4"
    max_upload_mb: int = 25
    frontend_url: str = "http://localhost:4200"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@ai-workspace.local"
    auth_rate_per_min: int = 20
    sandbox_enabled: bool = False
    search_url: str = ""        # instance SearXNG (ex. http://searxng:8080/search) pour l'outil web_search
    github_token: str = ""      # jeton en lecture seule pour l'outil github (facultatif)
    video_gen_url: str = ""     # serveur de génération vidéo (opérateur) ; vide = génération vidéo indisponible
    stt_url: str = ""           # serveur de transcription (Phonon ou compatible /v1/audio/transcriptions), défini par l'opérateur
    deploy_hooks: str = ""      # JSON {"nom": "https://…hook"} pour l'outil deploy

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # lève une erreur claire si JWT_SECRET est absent
