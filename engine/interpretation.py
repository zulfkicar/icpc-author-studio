"""Conservative typed interpretation of author free text.

This module is a *proposal* layer.  It never grants authority, settles a
mathematical claim, or changes a specification by itself.  The host applies an
explicit ``grant`` decision, fences consequential ambiguity, and enforces scope
again at publication.

Two contracts live here:

* :func:`interpret_authorization` separates an affirmative edit instruction from
  a question, quotation, tentative suggestion, negation, revocation or an
  explicit exclusion.  A keyword hit is not authority.
* :func:`interpret_semantics` separates a clear endpoint instruction from a
  mention, quotation, question, tentative suggestion or negation.  A mention is
  not a decision.

The finite language model here is deliberately conservative and testable; it is
not a general natural-language parser.  Ambiguity remains a first-class outcome.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

EditAction = Literal["grant", "deny", "revoke", "ambiguous", "none"]
SemanticMode = Literal["explicit", "negated", "tentative", "question", "quoted", "mention", "none"]


def canonical_endpoint_option(value: Any) -> str | None:
    if value in ("half_open", "half-open"):
        return "half_open"
    return "closed" if value == "closed" else None

_SMART_TRANSLATE = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2032": "'", "\u2033": '"',
})
_CLAUSE_SPLIT = re.compile(
    r"(?<=[!?;])\s+|\.(?=\s|$)|\n+|\bbut\b|\bhowever\b", re.I)
_QUESTION_START = re.compile(
    r"^\s*(?:please\s+|kindly\s+)?(?:is|are|was|were|do|does|did|can|could|should|"
    r"would|will|may|might|must|have|has|what|which|why|how|who|where)\b", re.I)
_NEGATION = re.compile(
    r"\b(?:not|never|without|avoid|no|none|zero|cannot|can't|can\u2019t|don't|"
    r"don\u2019t|dont|doesn't|doesn\u2019t|isn't|isn\u2019t|aren't|aren\u2019t|"
    r"won't|won\u2019t|wouldn't|wouldn\u2019t|shouldn't|shouldn\u2019t|"
    r"mustn't|mustn\u2019t|couldn't|couldn\u2019t|needn't|needn\u2019t|"
    r"haven't|haven\u2019t|hasn't|hasn\u2019t|didn't|didn\u2019t|stop)\b",
    re.I)
_TENTATIVE = re.compile(
    r"\b(?:maybe|perhaps|possibly|probably|could|might|would|unsure|uncertain|"
    r"not\s+sure|consider|either|or\s+maybe|tentative)\b", re.I)
_TENTATIVE_START = re.compile(
    r"^\s*(?:please\s+|kindly\s+)?(?:maybe|perhaps|possibly|probably|could|might|"
    r"would|consider|i\s+might|i\s+could|i\s+may|unsure|not\s+sure)\b", re.I)
_CONDITIONAL_START = re.compile(
    r"^\s*(?:if|unless|when|whenever|suppose|supposing|assuming|in\s+case|"
    r"were\s+you\s+to|if\s+you\s+were)\b", re.I)
_REVOKE = re.compile(
    r"\b(?:revoke|revoked|withdraw|withdrawn|rescind|rescinded|cancel|cancelled|"
    r"canceled|disable|disabled|remove|removed|stop|end)\b.{0,60}?"
    r"\b(?:edit|edits|editing|patch|patching|write|writing|repair|repairs|"
    r"modify|modification|permission|permissions|authority|grant)\b"
    r"|\b(?:no\s+more|stop)\s+(?:editing|patching|writing|repairs?)\b"
    r"|\b(?:edit|patch|write)\s+(?:permission|authority|grant)\b.{0,30}"
    r"\b(?:revoked|withdrawn|removed|disabled|off)\b",
    re.I)
_EXCLUSIVE = re.compile(
    r"\b(?:only\s+(?:compare|investigate|explain|read|review)|"
    r"no\s+(?:edits?|patching|repairs?|modifications?|writes?|changes?\s+to\s+files?)|"
    r"without\s+(?:editing|patching|modifying|writing)|"
    r"do\s+not\s+(?:apply|edit|patch|repair|fix|modify|write|change)|"
    r"don't\s+(?:apply|edit|patch|repair|fix|modify|write|change)|"
    r"don\u2019t\s+(?:apply|edit|patch|repair|fix|modify|write|change)|"
    r"must\s+not\s+(?:apply|edit|patch|repair|fix|modify|write|change)|"
    r"never\s+(?:apply|edit|patch|repair|fix|modify|write|change)|"
    r"avoid\s+(?:applying|editing|patching|modifying|writing))\b",
    re.I)
_EDIT_MENTION = re.compile(
    r"\b(?:edit|edits|editing|patch|patching|repair|repairs|repairing|fix|fixes|"
    r"fixing|modify|modifies|modifying|modification|write|writes|writing|apply|"
    r"applies|applying|change|changes|changing|update|updates|updating|create|"
    r"creates|creating|delete|deletes|deleting|rename|renames|renaming)\b",
    re.I)
_ACTION_VERBS = re.compile(
    r"^(?:please\s*,?\s+|kindly\s*,?\s+)?(?:apply|edit|fix|repair|update|modify|write|change|"
    r"create|delete|remove|rename|patch)\b",
    re.I)
_ACTION_AFTER = re.compile(
    r"^(?:please\s*,?\s+|kindly\s*,?\s+)?(?:go\s+ahead\s+and|make\s+sure\s+to|be\s+sure\s+to|"
    r"i\s+want\s+you\s+to|i'd\s+like\s+you\s+to|i\s+would\s+like\s+you\s+to|"
    r"you\s+should|you\s+must|you\s+need\s+to|you\s+have\s+to|let's|let\s+us)\s+"
    r"(?:apply|edit|fix|repair|update|modify|write|change|create|delete|remove|"
    r"rename|patch)\b",
    re.I)
_PERMISSION = re.compile(
    r"\b(?:you\s+may|you\s+can|permission\s+to|authorized\s+to|authorise\s+to|"
    r"go\s+ahead\s+and|i\s+authorize|i\s+authorise|i\s+approve|feel\s+free\s+to|"
    r"i\s+want\s+you\s+to|i'd\s+like\s+you\s+to|i\s+would\s+like\s+you\s+to)\b",
    re.I)
_REVIEW_START = re.compile(
    r"^\s*(?:please\s+|kindly\s+)?(?:review|reviews|inspect|audit|check|"
    r"patch\s+review)\b", re.I)
_INFO_OBJECT = re.compile(
    r"\b(?:explanation|explain|plan|planning|summary|summarize|description|describe|"
    r"outline|analysis|analyze|report|documentation|specification|editorial|proof|"
    r"proposal|recommendation|options?|comparison|note)\b", re.I)
_REPORTED = re.compile(
    r"\b(?:someone|somebody|they|he|she|the\s+reviewer|a\s+reviewer|another\s+person|"
    r"another\s+model|the\s+docs?|documentation|guide|specification|prompt|example|"
    r"suggested|suggests|said|says|wrote|writes|claims?|according\s+to|reportedly|"
    r"apparently|it\s+is\s+said|was\s+told|were\s+told)\b", re.I)
_INFO_START = re.compile(
    r"^\s*(?:please\s+|kindly\s+)?(?:explain|describe|show|tell|discuss|compare|"
    r"review|inspect|analy[sz]e|check|audit|outline|summari[sz]e|clarify|detail|"
    r"list|suggest|propose|recommend|walk\s+me\s+through|help\s+me|"
    r"i\s+want\s+to\s+know|i'd\s+like\s+to\s+know)\b", re.I)
_INFO_PHRASE = re.compile(
    r"\b(?:how\s+to|how\s+we\s+(?:can|could|might|would)|what\s+changes|"
    r"changes?\s+needed|steps?\s+to|the\s+way\s+to|ways?\s+to|"
    r"is\s+a\s+repair\s+needed|explain|description|analysis|review)\b",
    re.I)
_REVIEW_CONTEXT = re.compile(
    r"\b(?:review|reviews|reviewing|reviewed|inspect|inspected|examining|discuss|"
    r"discussion|compare|comparison|explain|read|checking|check|audit|"
    r"patch\s+review|review\s+of)\b", re.I)
_PATH = re.compile(
    r"(?<![\w/.-])([A-Za-z0-9_][A-Za-z0-9_./-]{0,200}\."
    r"(?:cpp|cc|cxx|h|hpp|md|txt|py|json|ya?ml|toml|ini|cfg|tex|java|rs|go))\b"
)

_HALF_OPEN = re.compile(
    r"\b(?:half[- ]open|touching\s+(?:jobs?\s+)?(?:are\s+)?(?:allowed|compatible)|"
    r"rooms?\s+free|free\s+(?:at|exactly\s+at)\s+(?:the\s+)?finish|end\s+exactly)\b",
    re.I)
_CLOSED = re.compile(
    r"\b(?:closed\s+intervals?|closed[- ]endpoint|inclusive\s+endpoints?|"
    r"includes?\s+the\s+finish|strict\s+predecessor|finish\s*<\s*start)\b",
    re.I)
_SEMANTIC_MARKER = re.compile(
    r"\b(?:use|using|used|adopt|switch|set|make|treat|choose|chose|define|assume|"
    r"keep|apply|enforce|require|prefer|preference|i\s+meant|we\s+use|let'?s\s+use|"
    r"please\s+use|decided|decision|intended|correct\s+convention|should\s+be|"
    r"must\s+be|is\s+correct|are\s+correct|go\s+with)\b",
    re.I)


def clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT.split(text) if part.strip()]


def _single_quote_opens(text: str, index: int) -> bool:
    if index == 0:
        return True
    previous = text[index - 1]
    return previous.isspace() or previous in "([{<,:;!?-\u2014\u2013/"


def _single_quote_closes(text: str, index: int) -> bool:
    if index + 1 >= len(text):
        return True
    following = text[index + 1]
    return not following.isalnum()


def lex_text(text: str) -> tuple[str, list[str]]:
    """Return (visible text, quoted spans).

    Apostrophes inside words (``Don't``, ``author's``, ``don’t``) are not quote
    delimiters.  Straight and typographic quotation marks are recognized; an
    unmatched quote is left visible rather than erasing the following text.
    """
    normalized = str(text or "").translate(_SMART_TRANSLATE)
    visible: list[str] = []
    spans: list[str] = []
    index = 0
    length = len(normalized)
    while index < length:
        char = normalized[index]
        if char in ('"', "`"):
            close = normalized.find(char, index + 1)
            if close != -1:
                spans.append(normalized[index + 1:close])
                visible.append(" ")
                index = close + 1
                continue
            visible.append(char)
            index += 1
            continue
        if char == "'" and _single_quote_opens(normalized, index):
            close = index + 1
            while close < length:
                if normalized[close] == "'" and _single_quote_closes(normalized, close):
                    break
                close += 1
            if close < length:
                spans.append(normalized[index + 1:close])
                visible.append(" ")
                index = close + 1
                continue
        visible.append(char)
        index += 1
    return "".join(visible), spans


def unquoted(text: str) -> str:
    return lex_text(text)[0]


def quoted_spans(text: str) -> list[str]:
    return lex_text(text)[1]


def _quoted_paths(spans: list[str]) -> list[str]:
    paths: list[str] = []
    for span in spans:
        value = span.strip()
        if value and _PATH.fullmatch(value):
            normalized = value.replace("\\", "/").lstrip("./")
            if normalized not in paths:
                paths.append(normalized)
    return paths


def _is_question(clause: str, whole: str) -> bool:
    return "?" in clause or "?" in whole or bool(_QUESTION_START.match(clause))


def _has_edit_action(clause: str) -> bool:
    return bool(_EDIT_ACTION.search(clause)) or bool(_PERMISSION.search(clause))


def _scope_paths(text: str) -> list[str]:
    seen: list[str] = []
    for match in _PATH.finditer(text):
        value = match.group(1).replace("\\", "/").lstrip("./")
        if value and value not in seen:
            seen.append(value)
    return seen


@dataclass(frozen=True)
class AuthorizationDecision:
    action: EditAction
    edit: bool = False
    scope_paths: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    reason: str = ""
    intent: Literal["edit", "information", "review", "restricted", "ambiguous", "neutral"] = "neutral"
    negated: bool = False
    tentative: bool = False
    question: bool = False
    quoted: bool = False
    revokes: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action, "edit": self.edit,
            "scopePaths": list(self.scope_paths),
            "exclusions": list(self.exclusions), "reason": self.reason,
            "intent": self.intent,
            "negated": self.negated, "tentative": self.tentative,
            "question": self.question, "quoted": self.quoted,
            "revokes": self.revokes,
        }


def _clause_intent(clause: str) -> str:
    """Classify one clause's requested action.

    Supported affirmative forms are finite: a leading directive action verb,
    a leading explicit permission/politeness construction, or a leading
    ``you should/must/need to``-type directive.  An action verb embedded in an
    explanation, review, question, conditional, tentative or subordinate
    construction is not an instruction.
    """
    lowered = " ".join(clause.lower().split())
    if not lowered:
        return "none"
    if _REVOKE.search(lowered):
        return "revoke"
    if _EXCLUSIVE.search(lowered):
        return "deny"
    if _NEGATION.search(lowered):
        return "deny"
    if _CONDITIONAL_START.match(lowered):
        return "conditional"
    if _TENTATIVE_START.match(lowered) and not re.match(
            r"^\s*(?:please\s+|kindly\s+)?(?:could|would|might|may)\s+you\b", lowered):
        return "tentative"
    if _is_question(lowered, lowered):
        return "question"
    if _TENTATIVE_START.match(lowered):
        return "tentative"
    if _REVIEW_START.match(lowered):
        return "review"
    if _REPORTED.search(lowered) and (_PERMISSION.search(lowered) or _EDIT_MENTION.search(lowered)):
        # A reported third party's permission is data, not this author's grant.
        return "information"
    if re.match(
            r"^\s*(?:please\s+|kindly\s+)?(?:write|create|draft|prepare|produce|generate|"
            r"give\s+me|make)\b", lowered) and _INFO_OBJECT.search(lowered):
        # "Write an explanation", "create a plan", "write a proof" are
        # information/planning requests, not file effects.
        return "information"
    if _INFO_START.match(lowered):
        return "information"
    if _INFO_PHRASE.search(lowered) and not _ACTION_VERBS.match(lowered):
        return "information"
    if _ACTION_VERBS.match(lowered):
        return "affirmative"
    if _ACTION_AFTER.match(lowered):
        return "affirmative"
    if _PERMISSION.search(lowered) and _EDIT_MENTION.search(lowered):
        return "affirmative"
    if _REVIEW_CONTEXT.search(lowered):
        return "information"
    return "mention"


def interpret_authorization(text: str) -> AuthorizationDecision:
    """Classify edit-authority language conservatively.

    A grant requires a supported complete affirmative clause and a concrete
    named path (or a typed effect authorization outside this function).  The
    finite grammar is documented in the module docstring; an unrecognized
    consequential construction yields no authority expansion.
    """
    raw = str(text or "")
    visible, quotes = lex_text(raw)
    edit_in_quotes = any(_EDIT_MENTION.search(span) for span in quotes)
    edit_visible = bool(_EDIT_MENTION.search(visible))
    revoke = bool(_REVOKE.search(visible))
    exclusive = bool(_EXCLUSIVE.search(visible))
    question = "?" in visible or any(_is_question(c, visible) for c in clauses(visible))
    quoted_only = edit_in_quotes and not edit_visible

    if revoke:
        return AuthorizationDecision("revoke", False, (), ("edit",),
                                     "explicit revocation of edit authority",
                                     intent="restricted", revokes=True)
    if exclusive:
        return AuthorizationDecision("deny", False, (), ("edit",),
                                     "explicit exclusion or negation of editing",
                                     intent="restricted", negated=True)
    if quoted_only:
        return AuthorizationDecision("none", False, (), (),
                                     "edit language appears only in quoted discussion",
                                     intent="information", quoted=True)
    if not edit_visible:
        return AuthorizationDecision("none", False, (), (), "no edit effect mentioned",
                                     intent="neutral")

    affirmative: list[str] = []
    negated = False
    tentative_clause = False
    question_clause = False
    information = False
    review = False
    for clause in clauses(visible):
        if not _EDIT_MENTION.search(clause):
            continue
        intent = _clause_intent(clause)
        if intent == "revoke":
            return AuthorizationDecision("revoke", False, (), ("edit",),
                                         "revocation clause",
                                         intent="restricted", revokes=True)
        if intent == "deny":
            negated = True
            continue
        if intent == "tentative":
            tentative_clause = True
            continue
        if intent == "conditional":
            tentative_clause = True
            continue
        if intent == "question":
            question_clause = True
            continue
        if intent == "information":
            information = True
            continue
        if intent == "review":
            information = True
            review = True
            continue
        if intent == "affirmative":
            affirmative.append(clause)
            continue
        # An edit mention without a supported complete construction is not
        # permission; fall through to no-expansion/ambiguous handling.
        information = True

    if affirmative and negated:
        # Mixed instruction: retain narrower authority and ask for the exact
        # effect rather than guessing which clause wins.
        return AuthorizationDecision("ambiguous", False, (), ("edit",),
                                     "mixed affirmative and negative edit clauses",
                                     intent="ambiguous", negated=True)
    if affirmative:
        # A concrete path is required.  A path quoted directly as an argument
        # to an affirmative clause is legitimate; an instruction inside quotes
        # is not a path and provides no scope.
        paths = _scope_paths(" ".join(affirmative))
        if not paths:
            paths = _quoted_paths(quotes)
        if not paths:
            return AuthorizationDecision(
                "ambiguous", False, (), ("edit",),
                "affirmative edit without a concrete path needs a concrete effect decision",
                intent="ambiguous",
            )
        if len(paths) > 1 and re.search(r"\bor\b", " ".join(affirmative), re.I):
            return AuthorizationDecision(
                "ambiguous", False, (), ("edit",),
                "alternative paths are not a concrete edit scope",
                intent="ambiguous",
            )
        return AuthorizationDecision(
            "grant", True, tuple(paths), (),
            "supported affirmative edit instruction scoped to " + ", ".join(paths),
            intent="edit",
        )
    if negated:
        return AuthorizationDecision("deny", False, (), ("edit",),
                                     "edit clause is negated or excluded",
                                     intent="restricted", negated=True)
    if tentative_clause:
        return AuthorizationDecision("ambiguous", False, (), ("edit",),
                                     "tentative or conditional edit needs clarification",
                                     intent="ambiguous", tentative=True,
                                     question=question_clause or question)
    if question_clause or question:
        return AuthorizationDecision("none", False, (), (),
                                     "question does not authorize an effect",
                                     intent="information", question=True)
    if information:
        return AuthorizationDecision("none", False, (), (),
                                     "explanation/review request does not authorize an effect",
                                     intent="review" if review else "information")
    return AuthorizationDecision("ambiguous", False, (), ("edit",),
                                 "unrecognized edit mention needs a concrete effect decision",
                                 intent="ambiguous")


@dataclass(frozen=True)
class SemanticDecision:
    endpoint: Literal["half_open", "closed"] | None
    mode: SemanticMode
    mentioned: tuple[str, ...] = ()
    reason: str = ""
    ambiguous: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "mode": self.mode,
                "mentioned": list(self.mentioned), "reason": self.reason,
                "ambiguous": self.ambiguous}


def _endpoint_mode(text: str, endpoint: str, *, initial: bool) -> tuple[SemanticMode, bool]:
    """Return (mode, explicit) for one endpoint family."""
    visible = unquoted(text)
    regex = _HALF_OPEN if endpoint == "half_open" else _CLOSED
    mentions = [m.start() for m in regex.finditer(visible)]
    quoted_mentions = [m for span in quoted_spans(text) for m in regex.finditer(span)]
    if not mentions:
        if quoted_mentions:
            return "quoted", False
        return "none", False
    for clause in clauses(visible):
        if not regex.search(clause):
            continue
        if _REVOKE.search(clause):
            return "negated", False
        if _EXCLUSIVE.search(clause) or _NEGATION.search(clause):
            return "negated", False
        if _is_question(clause, clause):
            return "question", False
        if _TENTATIVE.search(clause):
            return "tentative", False
        # An explicit marker close to the endpoint mention establishes a choice.
        if _SEMANTIC_MARKER.search(clause):
            return "explicit", True
    if initial and not _is_question(text, text) and not _TENTATIVE.search(visible):
        return "explicit", True
    return "mention", False


def interpret_semantics(text: str, *, initial: bool = False) -> SemanticDecision:
    """Classify endpoint language without turning a mention into a decision."""
    raw = str(text or "")
    half_mode, half_explicit = _endpoint_mode(raw, "half_open", initial=initial)
    closed_mode, closed_explicit = _endpoint_mode(raw, "closed", initial=initial)
    mentioned = tuple(name for name, mode in (("half_open", half_mode), ("closed", closed_mode))
                      if mode != "none")
    if half_explicit and closed_explicit:
        return SemanticDecision(None, "mention", mentioned,
                                "both endpoint conventions appear as instructions; clarify", True)
    if half_explicit:
        return SemanticDecision("half_open", "explicit", mentioned, "author instruction")
    if closed_explicit:
        return SemanticDecision("closed", "explicit", mentioned, "author instruction")
    for mode, endpoint in ((closed_mode, "closed"), (half_mode, "half_open")):
        if mode in ("tentative", "question", "quoted", "mention"):
            return SemanticDecision(None, mode, mentioned,
                                    "endpoint mentioned without a clear decision", True)
        if mode == "negated":
            return SemanticDecision(None, "negated", mentioned,
                                    "endpoint mention is negated", False)
    return SemanticDecision(None, "none", (), "")
