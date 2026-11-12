"""The costing subset of Apex: a tokenizer and declaration reader, not a parser.

This file exists because the question the gate asks (how many queries and DML statements does
this trigger issue per record) needs only a small part of the language: braces, loop headers,
SOQL and SOSL brackets, DML keywords, method calls and declarations. A full Apex grammar would
be weeks of work and most of it irrelevant. The price of the small subset is paid honestly: a
construct the reader does not understand is reported as a refusal by the analyser rather than
silently costed as zero (ADR-002).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DML_KEYWORDS = {"insert", "update", "upsert", "delete", "undelete", "merge"}
TRIGGER_EVENTS = {"insert", "update", "delete", "undelete"}
TRIGGER_TIMINGS = {"before", "after"}
MODIFIERS = {
    "public",
    "private",
    "protected",
    "global",
    "static",
    "final",
    "override",
    "virtual",
    "abstract",
    "transient",
    "webservice",
    "testmethod",
    "with",
    "without",
    "inherited",
    "sharing",
}
TWO_CHAR_PUNCT = {"==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "=>"}


@dataclass(frozen=True)
class Token:
    kind: str  # ident, number, string, soql, sosl, punct
    text: str
    line: int

    def is_ident(self, *names: str) -> bool:
        return self.kind == "ident" and (
            not names or self.text.lower() in {n.lower() for n in names}
        )

    def is_punct(self, *texts: str) -> bool:
        return self.kind == "punct" and (not texts or self.text in texts)


class ApexSyntaxError(ValueError):
    """Raised when a file cannot even be tokenized or its declaration header read."""


def tokenize(source: str) -> list[Token]:
    """Turn Apex source into tokens, folding each SOQL or SOSL bracket into one token.

    Comments and string contents are dropped (strings keep their kind so a bind expression in a
    dynamic query is still visible to the reader). A bracket whose first word is SELECT becomes a
    single `soql` token and one starting with FIND a single `sosl` token; every other bracket is
    an index or a list literal and stays as punctuation.
    """
    tokens: list[Token] = []
    i, n, line = 0, len(source), 1
    while i < n:
        ch = source[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end == -1 else end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                raise ApexSyntaxError(f"unterminated block comment at line {line}")
            line += source.count("\n", i, end)
            i = end + 2
            continue
        if ch == "'":
            j = i + 1
            while j < n and source[j] != "'":
                if source[j] == "\\":
                    j += 1
                if j < n and source[j] == "\n":
                    raise ApexSyntaxError(f"unterminated string at line {line}")
                j += 1
            if j >= n:
                raise ApexSyntaxError(f"unterminated string at line {line}")
            tokens.append(Token("string", source[i + 1 : j], line))
            i = j + 1
            continue
        if ch == "[":
            m = re.match(r"\[\s*(select|find)\b", source[i:], re.IGNORECASE)
            if m:
                depth, j = 0, i
                while j < n:
                    if source[j] == "[":
                        depth += 1
                    elif source[j] == "]":
                        depth -= 1
                        if depth == 0:
                            break
                    elif source[j] == "'":
                        j += 1
                        while j < n and source[j] != "'":
                            j += 1
                    j += 1
                if j >= n:
                    raise ApexSyntaxError(f"unterminated query bracket at line {line}")
                kind = "soql" if m.group(1).lower() == "select" else "sosl"
                text = source[i + 1 : j].strip()
                tokens.append(Token(kind, text, line))
                line += source.count("\n", i, j)
                i = j + 1
                continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            tokens.append(Token("ident", source[i:j], line))
            i = j
            continue
        if ch.isdigit():
            j = i
            while j < n and (source[j].isalnum() or source[j] == "."):
                j += 1
            tokens.append(Token("number", source[i:j], line))
            i = j
            continue
        two = source[i : i + 2]
        if two in TWO_CHAR_PUNCT:
            tokens.append(Token("punct", two, line))
            i += 2
            continue
        tokens.append(Token("punct", ch, line))
        i += 1
    return tokens


def matching_close(tokens: list[Token], open_index: int) -> int:
    """Index of the punctuation that closes the one at open_index (brace, paren or bracket)."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    opener = tokens[open_index].text
    closer = pairs[opener]
    depth = 0
    for j in range(open_index, len(tokens)):
        t = tokens[j]
        if t.is_punct(opener):
            depth += 1
        elif t.is_punct(closer):
            depth -= 1
            if depth == 0:
                return j
    raise ApexSyntaxError(f"unbalanced {opener!r} opened at line {tokens[open_index].line}")


@dataclass
class TypeName:
    """A declared type such as `List<Account>` or `Map<Id, Contact>`, kept as its parts."""

    base: str
    args: list[str] = field(default_factory=list)

    @property
    def is_collection(self) -> bool:
        return self.base.lower() in {"list", "set", "map"}

    @property
    def element(self) -> str | None:
        """The sObject or class a List or Set holds, or the value type of a Map."""
        if not self.is_collection or not self.args:
            return None
        return self.args[-1]

    @property
    def sobject(self) -> str | None:
        return self.element if self.is_collection else self.base


def read_type(tokens: list[Token], i: int) -> tuple[TypeName | None, int]:
    """Read a type name starting at i; return it and the index after it, or (None, i)."""
    if i >= len(tokens) or not tokens[i].is_ident():
        return None, i
    base = tokens[i].text
    j = i + 1
    while j + 1 < len(tokens) and tokens[j].is_punct(".") and tokens[j + 1].is_ident():
        base += "." + tokens[j + 1].text
        j += 2
    args: list[str] = []
    if j < len(tokens) and tokens[j].is_punct("<"):
        depth, k, current = 0, j, []
        while k < len(tokens):
            t = tokens[k]
            if t.is_punct("<"):
                depth += 1
                if depth > 1:
                    current.append(t.text)
            elif t.is_punct(">"):
                depth -= 1
                if depth == 0:
                    args.append("".join(current).strip())
                    k += 1
                    break
                current.append(t.text)
            elif t.is_punct(",") and depth == 1:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(t.text)
            k += 1
        else:
            raise ApexSyntaxError(f"unterminated type parameter at line {tokens[j].line}")
        j = k
    while j + 1 < len(tokens) and tokens[j].is_punct("[") and tokens[j + 1].is_punct("]"):
        base, args = "List", [base]
        j += 2
    return TypeName(base, args), j


@dataclass
class Param:
    type: TypeName
    name: str


@dataclass
class Method:
    name: str
    is_static: bool
    params: list[Param]
    body: list[Token]  # tokens strictly inside the braces
    line: int
    annotations: list[str] = field(default_factory=list)

    @property
    def is_test(self) -> bool:
        return "istest" in self.annotations or "testmethod" in self.annotations


@dataclass
class Field:
    name: str
    type: TypeName
    is_static: bool
    initializer: list[Token]


@dataclass
class ClassDecl:
    name: str
    path: str
    methods: dict[str, Method]
    fields: dict[str, Field]
    annotations: list[str]
    inner_classes: dict[str, ClassDecl] = field(default_factory=dict)

    @property
    def is_test(self) -> bool:
        return "istest" in self.annotations

    def static_booleans(self) -> set[str]:
        return {
            n for n, f in self.fields.items() if f.is_static and f.type.base.lower() == "boolean"
        }


@dataclass
class TriggerDecl:
    name: str
    path: str
    sobject: str
    events: set[tuple[str, str]]  # (timing, event) such as ("before", "insert")
    body: list[Token]
    line: int

    def fires_on(self, operation: str) -> bool:
        return any(ev == operation for _, ev in self.events)


def _read_annotations(tokens: list[Token], i: int) -> tuple[list[str], int]:
    annotations = []
    while i < len(tokens) and tokens[i].is_punct("@") and i + 1 < len(tokens):
        annotations.append(tokens[i + 1].text.lower())
        i += 2
        if i < len(tokens) and tokens[i].is_punct("("):
            i = matching_close(tokens, i) + 1
    return annotations, i


def _read_params(tokens: list[Token]) -> list[Param]:
    params: list[Param] = []
    i = 0
    while i < len(tokens):
        if tokens[i].is_punct(","):
            i += 1
            continue
        if tokens[i].is_ident("final"):
            i += 1
            continue
        type_name, j = read_type(tokens, i)
        if type_name is None or j >= len(tokens) or not tokens[j].is_ident():
            raise ApexSyntaxError(f"unreadable parameter list at line {tokens[i].line}")
        params.append(Param(type_name, tokens[j].text))
        i = j + 1
    return params


def parse_class(source: str, path: str = "<memory>") -> ClassDecl:
    """Read the outer class of a .cls file: its methods, fields, annotations and inner classes."""
    tokens = tokenize(source)
    annotations, i = _read_annotations(tokens, 0)
    while i < len(tokens) and tokens[i].is_ident() and tokens[i].text.lower() in MODIFIERS:
        i += 1
    if i >= len(tokens) or not tokens[i].is_ident("class", "interface"):
        raise ApexSyntaxError(f"{path}: no class declaration found")
    if tokens[i].is_ident("interface"):
        name = tokens[i + 1].text
        return ClassDecl(name, path, {}, {}, annotations)
    name = tokens[i + 1].text
    j = i + 2
    while j < len(tokens) and not tokens[j].is_punct("{"):
        j += 1
    if j >= len(tokens):
        raise ApexSyntaxError(f"{path}: class {name} has no body")
    close = matching_close(tokens, j)
    decl = ClassDecl(name, path, {}, {}, annotations)
    _read_members(tokens[j + 1 : close], decl, path)
    return decl


def _read_members(body: list[Token], decl: ClassDecl, path: str) -> None:
    i = 0
    while i < len(body):
        annotations, i = _read_annotations(body, i)
        modifiers: set[str] = set()
        while i < len(body) and body[i].is_ident() and body[i].text.lower() in MODIFIERS:
            modifiers.add(body[i].text.lower())
            i += 1
        if i >= len(body):
            break
        if body[i].is_punct("{"):  # static or instance initializer block
            i = matching_close(body, i) + 1
            continue
        if body[i].is_ident("class", "interface", "enum"):
            inner_name = body[i + 1].text
            k = i + 2
            while k < len(body) and not body[k].is_punct("{"):
                k += 1
            close = matching_close(body, k)
            if body[i].is_ident("class"):
                inner = ClassDecl(inner_name, path, {}, {}, annotations)
                _read_members(body[k + 1 : close], inner, path)
                decl.inner_classes[inner_name] = inner
            i = close + 1
            continue
        # constructor: Name ( ... ) {
        if body[i].is_ident() and body[i].text == decl.name and body[i + 1].is_punct("("):
            close_paren = matching_close(body, i + 1)
            open_brace = close_paren + 1
            close_brace = matching_close(body, open_brace)
            decl.methods[decl.name] = Method(
                decl.name,
                False,
                _read_params(body[i + 2 : close_paren]),
                body[open_brace + 1 : close_brace],
                body[i].line,
                annotations,
            )
            i = close_brace + 1
            continue
        type_name, j = read_type(body, i)
        if type_name is None or j >= len(body) or not body[j].is_ident():
            raise ApexSyntaxError(f"{path}: unreadable member at line {body[i].line}")
        member_name = body[j].text
        if j + 1 < len(body) and body[j + 1].is_punct("("):
            close_paren = matching_close(body, j + 1)
            k = close_paren + 1
            if k < len(body) and body[k].is_punct("{"):
                close_brace = matching_close(body, k)
                if "testmethod" in modifiers:
                    annotations = [*annotations, "testmethod"]
                decl.methods[member_name] = Method(
                    member_name,
                    "static" in modifiers,
                    _read_params(body[j + 2 : close_paren]),
                    body[k + 1 : close_brace],
                    body[j].line,
                    annotations,
                )
                i = close_brace + 1
            else:  # abstract or interface method with no body
                while k < len(body) and not body[k].is_punct(";"):
                    k += 1
                i = k + 1
            continue
        # field: Type name [= initializer] ;  (possibly a property with { get; set; })
        k = j + 1
        initializer: list[Token] = []
        if k < len(body) and body[k].is_punct("="):
            start = k + 1
            depth = 0
            while k < len(body):
                if body[k].is_punct("(", "{", "["):
                    depth += 1
                elif body[k].is_punct(")", "}", "]"):
                    depth -= 1
                elif body[k].is_punct(";") and depth == 0:
                    break
                k += 1
            initializer = body[start:k]
        elif k < len(body) and body[k].is_punct("{"):
            k = matching_close(body, k)
        decl.fields[member_name] = Field(member_name, type_name, "static" in modifiers, initializer)
        i = k + 1


def parse_trigger(source: str, path: str = "<memory>") -> TriggerDecl:
    """Read `trigger Name on Object (before insert, after update) { ... }`."""
    tokens = tokenize(source)
    if len(tokens) < 6 or not tokens[0].is_ident("trigger"):
        raise ApexSyntaxError(f"{path}: not a trigger file")
    name = tokens[1].text
    if not tokens[2].is_ident("on"):
        raise ApexSyntaxError(f"{path}: expected 'on' after the trigger name")
    sobject = tokens[3].text
    i = 4
    while i + 1 < len(tokens) and tokens[i].is_punct(".") and tokens[i + 1].is_ident():
        sobject += "." + tokens[i + 1].text
        i += 2
    if not tokens[i].is_punct("("):
        raise ApexSyntaxError(f"{path}: expected the event list after the object name")
    close = matching_close(tokens, i)
    words = [t.text.lower() for t in tokens[i + 1 : close] if t.is_ident()]
    events: set[tuple[str, str]] = set()
    for a, b in zip(words[0::2], words[1::2], strict=False):
        if a not in TRIGGER_TIMINGS or b not in TRIGGER_EVENTS:
            raise ApexSyntaxError(f"{path}: unreadable trigger event '{a} {b}'")
        events.add((a, b))
    if not events:
        raise ApexSyntaxError(f"{path}: trigger declares no events")
    open_brace = close + 1
    if open_brace >= len(tokens) or not tokens[open_brace].is_punct("{"):
        raise ApexSyntaxError(f"{path}: trigger has no body")
    close_brace = matching_close(tokens, open_brace)
    return TriggerDecl(
        name, path, sobject, events, tokens[open_brace + 1 : close_brace], tokens[0].line
    )
