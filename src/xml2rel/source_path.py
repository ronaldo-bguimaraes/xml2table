from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_PREDICATE_RE = re.compile(
    r"^@([A-Za-z_][A-Za-z0-9_.-]*)\s*(?:=\s*(['\"])(.*?)\2)?$",
    re.DOTALL,
)


class SourcePathError(ValueError):
    def __init__(self, expression: str, reason: str) -> None:
        self.expression = expression
        self.reason = reason
        super().__init__(f"{reason} in source XPath {expression!r}")


@dataclass(frozen=True)
class AttributePredicate:
    name: str
    value: str | None

    def matches(self, element: Any) -> bool:
        actual = element.get(self.name)
        if actual is None:
            return False
        return self.value is None or actual == self.value


@dataclass(frozen=True)
class PathSegment:
    axis: str
    tag: str
    predicates: tuple[AttributePredicate, ...] = ()

    def matches(self, element: Any) -> bool:
        tag = element.tag
        if not isinstance(tag, str) or tag.startswith("{"):
            return False
        if self.tag != "*" and tag != self.tag:
            return False
        return all(predicate.matches(element) for predicate in self.predicates)


class SourcePathMatcher:
    """Compile the supported source XPath subset used for streaming record matching."""

    def __init__(self, expression: str) -> None:
        if not isinstance(expression, str) or not expression.strip():
            raise SourcePathError(str(expression), "expression must be a non-empty string")
        self.expression = expression.strip()
        self.segments = _compile_segments(self.expression)
        self._requires_root_anchor = self.segments[0].axis == "child"

    def matches(self, element: Any) -> bool:
        if not self.segments[-1].matches(element):
            return False

        current = element
        for segment in reversed(self.segments[:-1]):
            if segment.axis == "child":
                parent = current.getparent()
                if parent is None or not segment.matches(parent):
                    return False
                current = parent
                continue

            parent = current.getparent()
            found = None
            while parent is not None:
                if segment.matches(parent):
                    found = parent
                    break
                parent = parent.getparent()
            if found is None:
                return False
            current = found

        return not self._requires_root_anchor or current.getparent() is None

    def __repr__(self) -> str:
        return f"SourcePathMatcher({self.expression!r})"


def _compile_segments(expression: str) -> tuple[PathSegment, ...]:
    if expression.startswith("//"):
        leading_axis = "descendant"
        body = expression[2:]
    elif expression.startswith("/"):
        leading_axis = "child"
        body = expression[1:]
    else:
        leading_axis = "child"
        body = expression

    if not body.strip():
        raise SourcePathError(expression, "path has no steps")

    parts, axes = _split_steps(expression, body, leading_axis)
    segments: list[PathSegment] = []
    for axis, part in zip(axes, parts):
        segments.append(_compile_segment(expression, axis, part))
    return tuple(segments)


def _split_steps(expression: str, body: str, leading_axis: str) -> tuple[list[str], list[str]]:
    parts = [""]
    axes = [leading_axis]
    quote: str | None = None
    depth = 0
    index = 0

    while index < len(body):
        char = body[index]
        if quote is not None:
            parts[-1] += char
            if char == quote:
                quote = None
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            parts[-1] += char
        elif char == "[":
            depth += 1
            parts[-1] += char
        elif char == "]":
            depth -= 1
            if depth < 0:
                raise SourcePathError(expression, "unbalanced ']'")
            parts[-1] += char
        elif char == "/" and depth == 0:
            if not parts[-1].strip():
                raise SourcePathError(expression, "empty path step")
            if index + 1 < len(body) and body[index + 1] == "/":
                axes.append("descendant")
                index += 1
            else:
                axes.append("child")
            parts.append("")
        else:
            parts[-1] += char
        index += 1

    if quote is not None:
        raise SourcePathError(expression, "unterminated quoted predicate")
    if depth != 0:
        raise SourcePathError(expression, "unbalanced '['")
    if not parts[-1].strip():
        raise SourcePathError(expression, "empty path step")

    return parts, axes


def _compile_segment(expression: str, axis: str, raw: str) -> PathSegment:
    text = raw.strip()
    bracket = text.find("[")
    tag = (text if bracket < 0 else text[:bracket]).strip()
    if tag != "*" and not _NAME_RE.match(tag):
        raise SourcePathError(expression, f"unsupported step {tag!r}; expected an element name or '*'")

    predicates: list[AttributePredicate] = []
    if bracket >= 0:
        predicates = _parse_predicates(expression, text[bracket:])
    return PathSegment(axis=axis, tag=tag, predicates=tuple(predicates))


def _parse_predicates(expression: str, text: str) -> list[AttributePredicate]:
    predicates: list[AttributePredicate] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if text[index] != "[":
            raise SourcePathError(expression, f"unexpected text {text[index:]!r} after step")

        end = index + 1
        quote: str | None = None
        while end < len(text):
            char = text[end]
            if quote is not None:
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char == "]":
                break
            end += 1

        if end >= len(text):
            raise SourcePathError(expression, "unterminated predicate")
        content = text[index + 1 : end].strip()
        match = _PREDICATE_RE.match(content)
        if match is None:
            raise SourcePathError(
                expression,
                f"unsupported predicate [{content}]; only @attribute and @attribute='value' are supported",
            )
        name, _, value = match.groups()
        predicates.append(AttributePredicate(name=name, value=value))
        index = end + 1

    return predicates
