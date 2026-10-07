"""Budgets et coûts (§39). Logique pure, testable sans base de données."""
from __future__ import annotations
from dataclasses import dataclass

ON_LIMIT = ("block", "confirm")


@dataclass(frozen=True)
class BudgetPolicy:
    monthly_limit_usd: float | None = None   # None = pas de plafond
    on_limit: str = "block"                  # block : refuser ; confirm : demander une confirmation explicite
    warn_ratio: float = 0.8


@dataclass
class BudgetDecision:
    allowed: bool
    needs_confirmation: bool
    warn: bool
    spent: float
    limit: float | None
    remaining: float | None
    reason: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def cost_usd(tokens_in: int, tokens_out: int, cost_in_per_m: float, cost_out_per_m: float) -> float:
    return round(tokens_in * cost_in_per_m / 1e6 + tokens_out * cost_out_per_m / 1e6, 6)


def evaluate(policy: BudgetPolicy, spent: float, estimate: float = 0.0, confirmed: bool = False) -> BudgetDecision:
    if policy.on_limit not in ON_LIMIT:
        raise ValueError(f"on_limit invalide: {policy.on_limit}")
    lim = policy.monthly_limit_usd
    if lim is None:
        return BudgetDecision(True, False, False, spent, None, None)
    projected, remaining = spent + estimate, max(0.0, lim - spent)
    warn = projected >= lim * policy.warn_ratio
    if spent >= lim or projected > lim:
        why = f"Budget mensuel de {lim:.2f} $ atteint (dépensé : {spent:.2f} $, estimation : {estimate:.2f} $)"
        if policy.on_limit == "confirm":
            return BudgetDecision(confirmed, not confirmed, True, spent, lim, remaining, why)
        return BudgetDecision(False, False, True, spent, lim, remaining, why)
    return BudgetDecision(True, False, warn, spent, lim, remaining)
