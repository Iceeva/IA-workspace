"""Données de démonstration, clairement étiquetées DEMO et isolées dans leur propre organisation.
Usage : python seed.py   (refuse de s'exécuter si APP_ENV=production)"""
import asyncio, os, secrets

from sqlalchemy import select

from app.agents.roles import ROLES, build_agent
from app.core.config import get_settings
from app.core.db import session_maker
from app.core.security import hash_password
from app.llm.base import LLMProvider
from app.models.entities import Agent, Organization, OrganizationMember, Project, Role, Subscription, User, Workspace

EMAIL = "demo@ai-workspace.local"


class _NoProvider(LLMProvider):
    name = "none"
    async def chat(self, *a, **k): raise RuntimeError("non utilisé")


async def main() -> None:
    if os.getenv("APP_ENV") == "production":
        raise SystemExit("Refus : le seed de démonstration est interdit en production.")
    async with session_maker()() as s:
        if (await s.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none():
            raise SystemExit("Le jeu de démonstration existe déjà.")
        pwd = secrets.token_urlsafe(12)
        user = User(email=EMAIL, password_hash=hash_password(pwd), full_name="Utilisateur DEMO", email_verified=True)
        org = Organization(name="DEMO — Laboratoire")
        s.add_all([user, org]); await s.flush()
        ws = Workspace(organization_id=org.id, name="DEMO — Paillasse 1")
        s.add_all([OrganizationMember(organization_id=org.id, user_id=user.id, role=Role.OWNER),
                   Subscription(organization_id=org.id), ws]); await s.flush()
        s.add(Project(organization_id=org.id, workspace_id=ws.id, name="DEMO — Gestion immobilière",
                      description="Projet de démonstration (données fictives)."))
        for role in ROLES:
            a = build_agent(role, _NoProvider(), get_settings().default_model)
            s.add(Agent(organization_id=org.id, name=f"DEMO {a.name}", role=role, description=a.description,
                        system_prompt=a.system_prompt, model=a.model, temperature=a.temperature))
        await s.commit()
    print(f"Compte DEMO créé\n  e-mail : {EMAIL}\n  mot de passe : {pwd}\n(affiché une seule fois)")


if __name__ == "__main__":
    asyncio.run(main())
