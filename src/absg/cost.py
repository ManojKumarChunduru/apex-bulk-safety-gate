"""The cost model: what one invocation of a trigger issues, as polynomials in its record count.

This file exists to turn Apex source into four polynomials per trigger (SOQL queries, SOSL
queries, DML statements, DML rows), each in r, the number of records in one trigger invocation,
plus the chain of other triggers its DML invokes. Everything the gate later reports is derived
from these. The reader is conservative in one direction only: it never costs a construct as
zero because it did not understand it. Loops it cannot bound, calls it cannot resolve and
chains it cannot follow become refusals, and a trigger with a refusal is undecidable (ADR-002).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from absg.apex import (
    DML_KEYWORDS,
    ClassDecl,
    Method,
    Token,
    TriggerDecl,
    TypeName,
    matching_close,
    read_type,
)
from absg.provenance import Poly, Provenance

PLATFORM_CLASSES = {
    "system",
    "database",
    "schema",
    "string",
    "math",
    "integer",
    "decimal",
    "double",
    "long",
    "date",
    "datetime",
    "time",
    "limits",
    "test",
    "userinfo",
    "json",
    "encodingutil",
    "crypto",
    "http",
    "httprequest",
    "httpresponse",
    "messaging",
    "approval",
    "search",
    "pattern",
    "matcher",
    "blob",
    "url",
    "id",
    "boolean",
    "label",
    "trigger",
    "apexpages",
    "auth",
    "cache",
    "flow",
    "site",
    "network",
    "dom",
    "eventbus",
    "formula",
    "exception",
    "list",
    "set",
    "map",
    "sobject",
    "sobjecttype",
    "describe",
}

# Platform calls that cost a query or a DML statement without the SOQL bracket or DML keyword.
DYNAMIC_SOQL = {("database", "query"), ("database", "countquery"), ("database", "getquerylocator")}
DYNAMIC_SOSL = {("search", "query"), ("search", "find")}
DATABASE_DML = {
    ("database", "insert"): "insert",
    ("database", "update"): "update",
    ("database", "upsert"): "upsert",
    ("database", "delete"): "delete",
    ("database", "undelete"): "undelete",
    ("database", "merge"): "merge",
    ("eventbus", "publish"): "publish",
}
GROWERS = {"add", "addall", "put", "putall"}

# Types a DML statement cannot target. Anything else is taken to be an sObject or a project class.
PRIMITIVES = {
    "integer",
    "long",
    "double",
    "decimal",
    "string",
    "boolean",
    "id",
    "date",
    "datetime",
    "time",
    "blob",
    "object",
    "sobject",
}

# Standard objects a trigger fixture is likely to touch as `Object.sObjectType` or similar.
STANDARD_OBJECTS = {
    "account",
    "contact",
    "opportunity",
    "case",
    "lead",
    "task",
    "event",
    "user",
    "campaign",
    "campaignmember",
    "order",
    "orderitem",
    "product2",
    "pricebook2",
    "pricebookentry",
    "asset",
    "contract",
    "quote",
    "quotelineitem",
    "opportunitylineitem",
    "group",
    "profile",
    "userrole",
    "attachment",
    "contentversion",
    "emailmessage",
    "feeditem",
    "note",
}


@dataclass
class Site:
    """One place in the source that contributes to a limit, for `absg explain`."""

    kind: str  # soql, sosl, dml, call, chain, loop, guard, platform, async
    path: str
    line: int
    multiplier: Poly | None
    detail: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "multiplier": None if self.multiplier is None else self.multiplier.describe(),
            "detail": self.detail,
        }


@dataclass
class ChainSite:
    """A DML statement that invokes other triggers: statements times rows per statement."""

    sobject: str
    operation: str
    statements: Poly
    rows_per_statement: Poly | None
    path: str
    line: int
    resource: str | None = None  # set for Test.loadData, resolved by the test reader

    def to_dict(self) -> dict:
        return {
            "sobject": self.sobject,
            "operation": self.operation,
            "statements": self.statements.describe(),
            "rows_per_statement": None
            if self.rows_per_statement is None
            else self.rows_per_statement.describe(),
            "path": self.path,
            "line": self.line,
            "resource": self.resource,
        }


@dataclass
class Refusal:
    """A construct the reader will not cost. The reason is one of a closed vocabulary."""

    reason: str  # dynamic_dispatch, external_namespace, unbounded_loop, unknown_target,
    # unbounded_rows, recursion, reentrant, unreadable
    construct: str
    path: str
    line: int

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "construct": self.construct,
            "path": self.path,
            "line": self.line,
        }


@dataclass
class Cost:
    soql: Poly = field(default_factory=Poly)
    sosl: Poly = field(default_factory=Poly)
    dml_statements: Poly = field(default_factory=Poly)
    dml_rows: Poly = field(default_factory=Poly)
    chains: list[ChainSite] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    guards: set[str] = field(default_factory=set)

    def absorb(self, other: Cost) -> None:
        self.soql = self.soql + other.soql
        self.sosl = self.sosl + other.sosl
        self.dml_statements = self.dml_statements + other.dml_statements
        self.dml_rows = self.dml_rows + other.dml_rows
        self.chains.extend(other.chains)
        self.refusals.extend(other.refusals)
        self.sites.extend(other.sites)
        self.guards |= other.guards

    def limit_polys(self) -> dict[str, Poly]:
        return {
            "soql_queries": self.soql,
            "sosl_queries": self.sosl,
            "dml_statements": self.dml_statements,
            "dml_rows": self.dml_rows,
        }


Env = dict[str, tuple[TypeName | None, Provenance]]


def _split_top_level(tokens: list[Token], sep: str) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    depth = 0
    for t in tokens:
        if t.is_punct("(", "{", "["):
            depth += 1
        elif t.is_punct(")", "}", "]"):
            depth -= 1
        if t.is_punct(sep) and depth == 0:
            parts.append([])
        else:
            parts[-1].append(t)
    return parts


def _text(tokens: list[Token]) -> str:
    """Readable source text for a site detail: tokens joined, punctuation tightened."""
    joined = " ".join(" ".join(t.text.split()) for t in tokens)
    for a, b in ((" . ", "."), ("( ", "("), (" )", ")"), (" ,", ","), (" ;", ";")):
        joined = joined.replace(a, b)
    return joined


def _count_literal_items(tokens: list[Token], open_index: int) -> int:
    close = matching_close(tokens, open_index)
    inner = tokens[open_index + 1 : close]
    if not inner:
        return 0
    return len(_split_top_level(inner, ","))


class Analyzer:
    """Walks trigger and method bodies and accumulates a Cost for each."""

    def __init__(self, classes: dict[str, ClassDecl], triggers: dict[str, TriggerDecl]):
        self.classes = {name.lower(): decl for name, decl in classes.items()}
        self.triggers = triggers
        self.sobjects = {t.sobject.lower() for t in triggers.values()}

    # ----- entry points -----------------------------------------------------------------

    def analyze_trigger(self, trigger: TriggerDecl) -> Cost:
        env: Env = {}
        return self.analyze_block(trigger.body, env, Poly.const(1), None, trigger.path, [])

    def analyze_method(
        self,
        owner: ClassDecl,
        method: Method,
        arg_provenance: list[Provenance],
        mult: Poly | None,
        stack: list[str],
    ) -> Cost:
        key = f"{owner.name}.{method.name}"
        if key in stack:
            cost = Cost()
            cost.refusals.append(Refusal("recursion", key, owner.path, method.line))
            return cost
        env: Env = {}
        for index, param in enumerate(method.params):
            prov = (
                arg_provenance[index]
                if index < len(arg_provenance)
                else Provenance.unbounded(f"argument {param.name} not visible at the call site")
            )
            if not param.type.is_collection and prov.kind in {"record", "const"}:
                prov = Provenance.element(param.name)
            env[param.name.lower()] = (param.type, prov)
        return self.analyze_block(method.body, env, mult, owner, owner.path, [*stack, key])

    # ----- blocks and statements -------------------------------------------------------

    def analyze_block(
        self,
        tokens: list[Token],
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        stack: list[str],
    ) -> Cost:
        cost = Cost()
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.is_ident("for"):
                i = self._analyze_for(tokens, i, env, mult, owner, path, stack, cost)
            elif t.is_ident("while"):
                close = matching_close(tokens, i + 1)
                cost.absorb(
                    self._scan_expression(tokens[i + 2 : close], env, mult, owner, path, stack)
                )
                body, i = self._loop_body(tokens, close + 1)
                cost.sites.append(Site("loop", path, t.line, None, "while loop: unbounded"))
                cost.absorb(self.analyze_block(body, env, None, owner, path, stack))
            elif t.is_ident("do"):
                body, i = self._loop_body(tokens, i + 1)
                cost.sites.append(Site("loop", path, t.line, None, "do loop: unbounded"))
                cost.absorb(self.analyze_block(body, env, None, owner, path, stack))
                while i < len(tokens) and not tokens[i].is_punct(";"):
                    i += 1
                i += 1
            elif t.is_ident("if"):
                close = matching_close(tokens, i + 1)
                condition = tokens[i + 2 : close]
                for guard in self._guards_in(condition, owner):
                    cost.guards.add(guard)
                    cost.sites.append(Site("guard", path, t.line, None, f"static guard {guard}"))
                cost.absorb(self._scan_expression(condition, env, mult, owner, path, stack))
                i = close + 1
            elif t.is_ident("else", "try", "finally"):
                i += 1
            elif t.is_ident("catch"):
                i = matching_close(tokens, i + 1) + 1
            elif t.is_ident("switch"):
                while i < len(tokens) and not tokens[i].is_punct("{"):
                    i += 1
            elif t.is_ident("when"):
                while i < len(tokens) and not tokens[i].is_punct("{"):
                    i += 1
            elif t.is_punct("{"):
                close = matching_close(tokens, i)
                cost.absorb(
                    self.analyze_block(tokens[i + 1 : close], env, mult, owner, path, stack)
                )
                i = close + 1
            elif t.is_punct(";"):
                i += 1
            else:
                stmt, i = self._statement(tokens, i)
                cost.absorb(self._analyze_statement(stmt, env, mult, owner, path, stack))
        return cost

    @staticmethod
    def _statement(tokens: list[Token], start: int) -> tuple[list[Token], int]:
        """Tokens of one simple statement, ending at `;` or at a block brace at depth 0."""
        depth = 0
        i = start
        while i < len(tokens):
            t = tokens[i]
            if t.is_punct("(", "["):
                depth += 1
            elif t.is_punct(")", "]"):
                depth -= 1
            elif t.is_punct("{"):
                previous = tokens[i - 1] if i > start else None
                if depth == 0 and not (previous and previous.is_punct(">", "]")):
                    return tokens[start:i], i
                depth += 1
            elif t.is_punct("}"):
                depth -= 1
            elif t.is_punct(";") and depth == 0:
                return tokens[start:i], i + 1
            i += 1
        return tokens[start:i], i

    @staticmethod
    def _loop_body(tokens: list[Token], start: int) -> tuple[list[Token], int]:
        if start < len(tokens) and tokens[start].is_punct("{"):
            close = matching_close(tokens, start)
            return tokens[start + 1 : close], close + 1
        stmt, nxt = Analyzer._statement(tokens, start)
        return stmt, nxt

    def _analyze_for(
        self,
        tokens: list[Token],
        i: int,
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        stack: list[str],
        cost: Cost,
    ) -> int:
        line = tokens[i].line
        close = matching_close(tokens, i + 1)
        header = tokens[i + 2 : close]
        colon = [k for k, t in enumerate(header) if t.is_punct(":")]
        if colon and len(_split_top_level(header, ";")) == 1:
            left, right = header[: colon[0]], header[colon[0] + 1 :]
            var_type, j = read_type(left, 0)
            var_name = left[j].text if j < len(left) else "_"
            prov = self.provenance_of(right, env)
            cost.absorb(self._scan_expression(right, env, mult, owner, path, stack))
            env[var_name.lower()] = (var_type, Provenance.element(var_name))
            loop_mult = prov.size
            detail = f"for {var_name} over {_text(right)}: {prov.kind}"
            if prov.note:
                detail += f" ({prov.note})"
        else:
            parts = _split_top_level(header, ";")
            init = parts[0] if parts else []
            condition = parts[1] if len(parts) > 1 else []
            if init:
                var_type, j = read_type(init, 0)
                if var_type is not None and j < len(init) and init[j].is_ident():
                    env[init[j].text.lower()] = (var_type, Provenance.element(init[j].text))
            prov = self._classic_bound(condition, env)
            loop_mult = prov.size
            detail = f"for ({_text(header)}): {prov.kind}"
            if prov.note:
                detail += f" ({prov.note})"
        cost.sites.append(Site("loop", path, line, loop_mult, detail))
        body, nxt = self._loop_body(tokens, close + 1)
        inner_mult = None if mult is None or loop_mult is None else mult * loop_mult
        cost.absorb(self.analyze_block(body, env, inner_mult, owner, path, stack))
        return nxt

    def _classic_bound(self, condition: list[Token], env: Env) -> Provenance:
        """`i < EXPR` or `i <= EXPR`: the bound is EXPR's size or value."""
        for k, t in enumerate(condition):
            if t.is_punct("<", "<="):
                expr = condition[k + 1 :]
                if len(expr) == 1 and expr[0].kind == "number" and expr[0].text.isdigit():
                    n = int(expr[0].text) + (1 if t.text == "<=" else 0)
                    return Provenance.const(n, "literal bound")
                if len(expr) == 1 and expr[0].is_ident():
                    prov = self.provenance_of(expr, env)
                    if prov.kind in {"record", "const"}:
                        return prov
                    return Provenance.unbounded(f"loop bound {expr[0].text} is not bounded")
                if len(expr) >= 4 and expr[-1].is_punct(")") and expr[-3].is_ident("size"):
                    receiver = expr[:-4] if expr[-4].is_punct(".") else expr[:-3]
                    return self.provenance_of(receiver, env)
                return Provenance.unbounded("loop bound is not a literal or a .size()")
        return Provenance.unbounded("loop condition without a < or <= bound")

    def _analyze_statement(
        self,
        stmt: list[Token],
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        stack: list[str],
    ) -> Cost:
        cost = Cost()
        if not stmt:
            return cost
        first = stmt[0]
        if first.is_ident() and first.text.lower() in DML_KEYWORDS and len(stmt) > 1:
            self._dml(first.text.lower(), stmt[1:], env, mult, owner, path, first.line, cost)
            return cost
        if first.is_ident("return", "throw"):
            cost.absorb(self._scan_expression(stmt[1:], env, mult, owner, path, stack))
            return cost
        # declaration: Type name [= expr]
        type_name, j = read_type(stmt, 0)
        if (
            type_name is not None
            and j < len(stmt)
            and stmt[j].is_ident()
            and (j + 1 == len(stmt) or stmt[j + 1].is_punct("=", ","))
            and not first.is_ident("this")
        ):
            name = stmt[j].text
            if j + 1 < len(stmt) and stmt[j + 1].is_punct("="):
                expr = stmt[j + 2 :]
                env[name.lower()] = (type_name, self.provenance_of(expr, env))
                cost.absorb(self._scan_expression(expr, env, mult, owner, path, stack))
            else:
                env[name.lower()] = (type_name, Provenance.const(0, "declared without a value"))
            return cost
        # assignment: name = expr
        if len(stmt) > 2 and first.is_ident() and stmt[1].is_punct("="):
            expr = stmt[2:]
            existing_type = env.get(first.text.lower(), (None, None))[0]
            env[first.text.lower()] = (existing_type, self.provenance_of(expr, env))
            cost.absorb(self._scan_expression(expr, env, mult, owner, path, stack))
            return cost
        cost.absorb(self._scan_expression(stmt, env, mult, owner, path, stack))
        return cost

    # ----- expressions -----------------------------------------------------------------

    def _scan_expression(
        self,
        tokens: list[Token],
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        stack: list[str],
    ) -> Cost:
        cost = Cost()
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.kind == "soql":
                self._charge(cost, "soql", mult, path, t.line, "SOQL bracket", "unbounded loop")
                i += 1
                continue
            if t.kind == "sosl":
                self._charge(cost, "sosl", mult, path, t.line, "SOSL bracket", "unbounded loop")
                i += 1
                continue
            if t.is_ident("new") and i + 1 < len(tokens):
                type_name, j = read_type(tokens, i + 1)
                if type_name is not None and j < len(tokens) and tokens[j].is_punct("("):
                    close = matching_close(tokens, j)
                    args = _split_top_level(tokens[j + 1 : close], ",") if close > j + 1 else []
                    for arg in args:
                        cost.absorb(self._scan_expression(arg, env, mult, owner, path, stack))
                    decl = self.classes.get(type_name.base.lower())
                    if decl is not None:
                        ctor = decl.methods.get(decl.name)
                        if ctor is not None:
                            provs = [self.provenance_of(a, env) for a in args]
                            cost.absorb(self.analyze_method(decl, ctor, provs, mult, stack))
                        # new X(...).method(...)
                        if (
                            close + 2 < len(tokens)
                            and tokens[close + 1].is_punct(".")
                            and tokens[close + 2].is_ident()
                            and close + 3 < len(tokens)
                            and tokens[close + 3].is_punct("(")
                        ):
                            call_close = matching_close(tokens, close + 3)
                            call_args = _split_top_level(tokens[close + 4 : call_close], ",")
                            if call_close == close + 4:
                                call_args = []
                            cost.absorb(
                                self._call(
                                    decl,
                                    tokens[close + 2].text,
                                    call_args,
                                    env,
                                    mult,
                                    owner,
                                    path,
                                    tokens[close + 2].line,
                                    stack,
                                )
                            )
                            i = call_close + 1
                            continue
                    i = close + 1
                    continue
            if t.is_ident() and i + 1 < len(tokens) and tokens[i + 1].is_punct("("):
                # bare call: method(...) on the owning class, or this.method handled below
                close = matching_close(tokens, i + 1)
                args = _split_top_level(tokens[i + 2 : close], ",") if close > i + 2 else []
                for arg in args:
                    cost.absorb(self._scan_expression(arg, env, mult, owner, path, stack))
                receiver = tokens[i - 1] if i > 0 else None
                if receiver is not None and receiver.is_punct("."):
                    i = close + 1
                    continue  # handled when the receiver was visited
                if owner is not None and t.text in owner.methods:
                    cost.absorb(
                        self._call(owner, t.text, args, env, mult, owner, path, t.line, stack)
                    )
                i = close + 1
                continue
            if (
                t.is_ident()
                and i + 5 < len(tokens)
                and tokens[i + 1].is_punct(".")
                and tokens[i + 2].is_ident()
                and tokens[i + 3].is_punct(".")
                and tokens[i + 4].is_ident()
                and tokens[i + 5].is_punct("(")
                and not self._known_head(t.text, env, owner)
                and not (i > 0 and tokens[i - 1].is_punct("."))
            ):
                # namespace.Class.method(...): a managed package whose source is not here
                close = matching_close(tokens, i + 5)
                construct = f"{t.text}.{tokens[i + 2].text}.{tokens[i + 4].text}()"
                cost.refusals.append(Refusal("external_namespace", construct, path, t.line))
                i = close + 1
                continue
            if (
                t.is_ident()
                and i + 3 < len(tokens)
                and tokens[i + 1].is_punct(".")
                and tokens[i + 2].is_ident()
                and tokens[i + 3].is_punct("(")
            ):
                i = self._qualified_call(tokens, i, env, mult, owner, path, stack, cost)
                continue
            i += 1
        return cost

    def _known_head(self, name: str, env: Env, owner: ClassDecl | None) -> bool:
        """Is this identifier something the reader can account for as a receiver?"""
        lower = name.lower()
        return (
            lower in env
            or lower in self.classes
            or lower in PLATFORM_CLASSES
            or self._is_sobject(lower)
            or (owner is not None and name in owner.fields)
        )

    def _is_sobject(self, lower: str) -> bool:
        return (
            lower in self.sobjects
            or lower in STANDARD_OBJECTS
            or lower.endswith(("__c", "__e", "__mdt", "__x", "__b", "__r", "__share", "__history"))
        )

    def _qualified_call(
        self,
        tokens: list[Token],
        i: int,
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        stack: list[str],
        cost: Cost,
    ) -> int:
        head, method = tokens[i], tokens[i + 2]
        open_paren = i + 3
        close = matching_close(tokens, open_paren)
        args = (
            _split_top_level(tokens[open_paren + 1 : close], ",") if close > open_paren + 1 else []
        )
        for arg in args:
            cost.absorb(self._scan_expression(arg, env, mult, owner, path, stack))
        key = (head.text.lower(), method.text.lower())
        line = method.line
        if key in DYNAMIC_SOQL:
            self._charge(
                cost, "soql", mult, path, line, f"{head.text}.{method.text}()", "unbounded loop"
            )
        elif key in DYNAMIC_SOSL:
            self._charge(
                cost, "sosl", mult, path, line, f"{head.text}.{method.text}()", "unbounded loop"
            )
        elif key in DATABASE_DML:
            target = args[0] if args else []
            self._dml(DATABASE_DML[key], target, env, mult, owner, path, line, cost)
        elif key == ("test", "loaddata"):
            self._load_data(args, mult, path, line, cost)
        elif key == ("type", "forname"):
            cost.refusals.append(Refusal("dynamic_dispatch", "Type.forName(...)", path, line))
        elif key in {("system", "enqueuejob"), ("database", "executebatch")}:
            cost.sites.append(
                Site("async", path, line, mult, f"{head.text}.{method.text}(): async")
            )
        elif head.text.lower() == "this" and owner is not None and method.text in owner.methods:
            cost.absorb(self._call(owner, method.text, args, env, mult, owner, path, line, stack))
        elif head.text.lower() in env:
            type_name, prov = env[head.text.lower()]
            decl = self.classes.get(type_name.base.lower()) if type_name else None
            if decl is not None and method.text in decl.methods:
                cost.absorb(
                    self._call(decl, method.text, args, env, mult, owner, path, line, stack)
                )
            elif method.text.lower() in GROWERS:
                env[head.text.lower()] = (type_name, prov.grow(mult))
        elif owner is not None and head.text in owner.fields:
            field_type = owner.fields[head.text].type
            decl = self.classes.get(field_type.base.lower())
            if decl is not None and method.text in decl.methods:
                cost.absorb(
                    self._call(decl, method.text, args, env, mult, owner, path, line, stack)
                )
            else:
                cost.sites.append(
                    Site("platform", path, line, mult, f"{head.text}.{method.text}(): field call")
                )
        elif head.text.lower() in self.classes:
            decl = self.classes[head.text.lower()]
            if method.text in decl.methods:
                cost.absorb(
                    self._call(decl, method.text, args, env, mult, owner, path, line, stack)
                )
            else:
                cost.refusals.append(
                    Refusal("unreadable", f"{head.text}.{method.text}() not declared", path, line)
                )
        elif (
            head.text.lower() not in PLATFORM_CLASSES
            and not self._is_sobject(head.text.lower())
            and i > 0
            and tokens[i - 1].is_punct(".")
        ):
            pass  # a.b.c(): the receiver chain was classified when its head was visited
        elif head.text.lower() not in PLATFORM_CLASSES and not self._is_sobject(head.text.lower()):
            cost.refusals.append(
                Refusal("external_namespace", f"{head.text}.{method.text}()", path, line)
            )
        else:
            cost.sites.append(
                Site("platform", path, line, mult, f"{head.text}.{method.text}(): platform call")
            )
        return close + 1

    def _call(
        self,
        decl: ClassDecl,
        method_name: str,
        args: list[list[Token]],
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        line: int,
        stack: list[str],
    ) -> Cost:
        method = decl.methods[method_name]
        provs = [self.provenance_of(a, env) for a in args]
        cost = Cost()
        cost.sites.append(
            Site(
                "call",
                path,
                line,
                mult,
                f"{decl.name}.{method_name}({', '.join(p.kind for p in provs)})",
            )
        )
        cost.absorb(self.analyze_method(decl, method, provs, mult, stack))
        return cost

    @staticmethod
    def _charge(
        cost: Cost, limit: str, mult: Poly | None, path: str, line: int, construct: str, why: str
    ) -> None:
        if mult is None:
            cost.refusals.append(Refusal("unbounded_loop", construct, path, line))
            return
        if limit == "soql":
            cost.soql = cost.soql + mult
        else:
            cost.sosl = cost.sosl + mult
        cost.sites.append(Site(limit, path, line, mult, construct))

    def _dml(
        self,
        operation: str,
        target: list[Token],
        env: Env,
        mult: Poly | None,
        owner: ClassDecl | None,
        path: str,
        line: int,
        cost: Cost,
    ) -> None:
        if mult is None:
            cost.refusals.append(Refusal("unbounded_loop", f"{operation} statement", path, line))
            return
        sobject, rows = self._dml_target(target, env)
        if sobject is None:
            cost.refusals.append(
                Refusal("unknown_target", f"{operation} {_text(target)}", path, line)
            )
            return
        cost.dml_statements = cost.dml_statements + mult
        if rows is None:
            cost.refusals.append(
                Refusal("unbounded_rows", f"{operation} {_text(target)}", path, line)
            )
        else:
            cost.dml_rows = cost.dml_rows + mult * rows
        cost.sites.append(
            Site(
                "dml",
                path,
                line,
                mult,
                f"{operation} {sobject}: {'?' if rows is None else rows.describe()} "
                "rows per statement",
            )
        )
        cost.chains.append(ChainSite(sobject, operation, mult, rows, path, line))

    def _dml_target(self, target: list[Token], env: Env) -> tuple[str | None, Poly | None]:
        if not target:
            return None, None
        if target[0].kind == "soql":
            match = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", target[0].text, re.IGNORECASE)
            return (match.group(1) if match else None), None
        if target[0].is_ident("new"):
            type_name, j = read_type(target, 1)
            if type_name is None:
                return None, None
            if type_name.is_collection:
                if j < len(target) and target[j].is_punct("{"):
                    return type_name.element, Poly.const(_count_literal_items(target, j))
                return type_name.element, Poly.const(0)
            return type_name.base, Poly.const(1)
        if target[0].is_ident():
            name = target[0].text.lower()
            if name == "trigger" and len(target) >= 3:
                return None, None  # DML on Trigger.new itself is not allowed by the platform
            if name in env:
                type_name, prov = env[name]
                sobject = type_name.sobject if type_name else None
                if sobject is None or sobject.lower() in PRIMITIVES:
                    return None, None
                if type_name is not None and not type_name.is_collection:
                    return sobject, Poly.const(1)
                return sobject, prov.size
        return None, None

    def _load_data(
        self, args: list[list[Token]], mult: Poly | None, path: str, line: int, cost: Cost
    ) -> None:
        sobject = args[0][0].text if args and args[0] else None
        resource = None
        if len(args) > 1 and args[1] and args[1][0].kind == "string":
            resource = args[1][0].text
        if sobject is None or resource is None or mult is None:
            cost.refusals.append(Refusal("unknown_target", "Test.loadData(...)", path, line))
            return
        cost.sites.append(Site("dml", path, line, mult, f"Test.loadData {sobject} from {resource}"))
        cost.chains.append(ChainSite(sobject, "insert", mult, None, path, line, resource=resource))

    def _guards_in(self, condition: list[Token], owner: ClassDecl | None) -> list[str]:
        guards = []
        for k, t in enumerate(condition):
            if (
                t.is_ident()
                and k + 2 < len(condition)
                and condition[k + 1].is_punct(".")
                and condition[k + 2].is_ident()
            ):
                decl = self.classes.get(t.text.lower())
                if decl is not None and condition[k + 2].text in decl.static_booleans():
                    guards.append(f"{decl.name}.{condition[k + 2].text}")
            elif t.is_ident() and owner is not None and t.text in owner.static_booleans():
                if not (k > 0 and condition[k - 1].is_punct(".")):
                    guards.append(f"{owner.name}.{t.text}")
        return guards

    # ----- provenance of an expression -------------------------------------------------

    def provenance_of(self, expr: list[Token], env: Env) -> Provenance:
        if not expr:
            return Provenance.unbounded("empty expression")
        # strip a cast: (Type) expr
        if expr[0].is_punct("(") and len(expr) > 2:
            close = matching_close(expr, 0)
            inner = expr[1:close]
            if inner and all(t.is_ident() or t.is_punct(".", "<", ">", ",") for t in inner):
                return self.provenance_of(expr[close + 1 :], env)
        if expr[0].kind in {"soql", "sosl"}:
            return Provenance.unbounded("query result")
        if expr[0].is_ident("new"):
            type_name, j = read_type(expr, 1)
            if type_name is None:
                return Provenance.unbounded("unreadable constructor")
            if type_name.is_collection:
                if j < len(expr) and expr[j].is_punct("{"):
                    return Provenance.const(_count_literal_items(expr, j), "collection literal")
                if j < len(expr) and expr[j].is_punct("("):
                    close = matching_close(expr, j)
                    inner = expr[j + 1 : close]
                    if inner:
                        return self.provenance_of(inner, env)
                return Provenance.const(0, "empty collection")
            return Provenance.element("constructed record")
        if expr[0].is_ident("trigger") and len(expr) >= 3 and expr[1].is_punct("."):
            member = expr[2].text.lower()
            if member in {"new", "old", "newmap", "oldmap"}:
                if len(expr) >= 4 and expr[3].is_punct("["):
                    return Provenance.element("one trigger record")
                if (
                    len(expr) >= 6
                    and expr[3].is_punct(".")
                    and expr[4].text.lower() == "size"
                    and expr[5].is_punct("(")
                ):
                    return Provenance.record(f"Trigger.{expr[2].text}.size()")
                return Provenance.record(f"Trigger.{expr[2].text}")
            return Provenance.unbounded(f"Trigger.{expr[2].text}")
        if expr[0].is_ident():
            name = expr[0].text.lower()
            if len(expr) == 1:
                if name in env:
                    return env[name][1]
                return Provenance.unbounded(f"{expr[0].text} was never assigned in view")
            if name in env and expr[1].is_punct("."):
                member = expr[2].text.lower() if len(expr) > 2 else ""
                if member in {"values", "keyset", "clone", "deepclone", "size"}:
                    return env[name][1]
                return Provenance.unbounded(
                    f"{expr[0].text}.{expr[2].text if len(expr) > 2 else ''}"
                )
            if any(t.is_punct("(") for t in expr):
                return Provenance.unbounded("method return value")
        if expr[0].kind == "number" and len(expr) == 1 and expr[0].text.isdigit():
            return Provenance.const(int(expr[0].text), "literal")
        return Provenance.unbounded(" ".join(t.text for t in expr[:4]))
