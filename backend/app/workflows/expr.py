"""Expressions de workflow : sous-ensemble sûr de Python (conditions, boucles) et gabarits {{a.output}}.

Pas d'`eval` : l'arbre syntaxique est parcouru et seuls les nœuds listés sont acceptés. Aucun accès aux attributs
« _ », aucune fonction hors liste blanche, longueur et profondeur bornées."""
from __future__ import annotations
import ast
import operator as op
import re

MAX_LEN = 500
MAX_DEPTH = 20
_FUNCS = {"len": len, "str": str, "int": int, "float": float, "min": min, "max": max, "abs": abs,
          "any": any, "all": all, "bool": bool}
_STR_METHODS = {"lower", "upper", "strip", "startswith", "endswith", "count", "split", "find"}
_CMP = {ast.Eq: op.eq, ast.NotEq: op.ne, ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b, ast.Is: op.is_, ast.IsNot: op.is_not}
_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Mod: op.mod,
        ast.FloorDiv: op.floordiv}
_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z_][\w.\[\]'\"-]*)\s*\}\}")


class ExprError(ValueError):
    pass


def parse(expr: str) -> ast.Expression:
    if not isinstance(expr, str) or not expr.strip() or len(expr) > MAX_LEN:
        raise ExprError("Expression vide ou trop longue")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"Syntaxe invalide : {e.msg}") from e
    _check(tree.body, 0)
    return tree


def _check(n, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ExprError("Expression trop imbriquée")
    ok = (ast.BoolOp, ast.UnaryOp, ast.Compare, ast.BinOp, ast.Constant, ast.Name, ast.Attribute, ast.Subscript,
          ast.Call, ast.List, ast.Tuple, ast.IfExp, ast.Load, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
          ast.Index if hasattr(ast, "Index") else ast.Constant)
    if not isinstance(n, ok) and type(n) not in (*_CMP, *_BIN):
        raise ExprError(f"Élément non autorisé : {type(n).__name__}")
    if isinstance(n, ast.Name) and n.id.startswith("_"):
        raise ExprError("Nom interdit")
    if isinstance(n, ast.Attribute) and n.attr.startswith("_"):
        raise ExprError("Attribut interdit")
    if isinstance(n, ast.Call):
        f = n.func
        if not ((isinstance(f, ast.Name) and f.id in _FUNCS) or
                (isinstance(f, ast.Attribute) and f.attr in _STR_METHODS)):
            raise ExprError("Appel de fonction non autorisé")
        if n.keywords:
            raise ExprError("Arguments nommés non autorisés")
    for c in ast.iter_child_nodes(n):
        _check(c, depth + 1)


def evaluate(expr: str | ast.Expression, ctx: dict):
    tree = parse(expr) if isinstance(expr, str) else expr
    return _ev(tree.body, ctx)


def _ev(n, ctx):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        if n.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[n.id]
        if n.id not in ctx:
            raise ExprError(f"Variable inconnue : {n.id}")
        return ctx[n.id]
    if isinstance(n, ast.BoolOp):
        vals = (_ev(v, ctx) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.UnaryOp):
        v = _ev(n.operand, ctx)
        return {ast.Not: lambda x: not x, ast.USub: op.neg, ast.UAdd: op.pos}[type(n.op)](v)
    if isinstance(n, ast.BinOp):
        l, r = _ev(n.left, ctx), _ev(n.right, ctx)
        if isinstance(n.op, ast.Mult) and (isinstance(l, (str, list)) or isinstance(r, (str, list))):
            raise ExprError("Multiplication de séquences interdite")
        try:
            return _BIN[type(n.op)](l, r)
        except (TypeError, ZeroDivisionError) as e:
            raise ExprError(f"Opération impossible : {e}") from e
    if isinstance(n, ast.Compare):
        left = _ev(n.left, ctx)
        for o, c in zip(n.ops, n.comparators):
            right = _ev(c, ctx)
            try:
                if not _CMP[type(o)](left, right):
                    return False
            except TypeError as e:
                raise ExprError(f"Comparaison impossible : {e}") from e
            left = right
        return True
    if isinstance(n, ast.IfExp):
        return _ev(n.body, ctx) if _ev(n.test, ctx) else _ev(n.orelse, ctx)
    if isinstance(n, (ast.List, ast.Tuple)):
        return [_ev(e, ctx) for e in n.elts]
    if isinstance(n, ast.Attribute):
        base = _ev(n.value, ctx)
        if isinstance(base, dict):
            if n.attr not in base:
                raise ExprError(f"Champ inconnu : {n.attr}")
            return base[n.attr]
        raise ExprError(f"Attribut inaccessible : {n.attr}")
    if isinstance(n, ast.Subscript):
        base, key = _ev(n.value, ctx), _ev(n.slice, ctx)
        try:
            return base[key]
        except (KeyError, IndexError, TypeError) as e:
            raise ExprError(f"Accès impossible : {e}") from e
    if isinstance(n, ast.Call):
        args = [_ev(a, ctx) for a in n.args]
        f = n.func
        try:
            if isinstance(f, ast.Name):
                return _FUNCS[f.id](*args)
            obj = _ev(f.value, ctx)
            if not isinstance(obj, str):
                raise ExprError("Méthode réservée aux chaînes")
            return getattr(obj, f.attr)(*args)
        except (TypeError, ValueError) as e:
            raise ExprError(f"Appel impossible : {e}") from e
    raise ExprError(f"Élément non géré : {type(n).__name__}")


def truthy(expr: str, ctx: dict) -> bool:
    return bool(evaluate(expr, ctx))


def render(template: str, ctx: dict, max_len: int = 200_000) -> str:
    """Remplace {{chemin.pointé}} par la valeur ; une variable inconnue lève une erreur (pas de texte vide silencieux)."""
    def sub(m):
        return str(evaluate(m.group(1), ctx))
    out = _TEMPLATE.sub(sub, template)
    if len(out) > max_len:
        raise ExprError("Texte généré trop long")
    return out
