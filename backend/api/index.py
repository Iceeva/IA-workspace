# Point d'entrée ASGI pour Vercel (fonctions Python). Les orchestrations longues restent dans le worker.
from app.main import app  # noqa: F401
