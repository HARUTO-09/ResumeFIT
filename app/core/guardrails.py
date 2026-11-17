"""Coach guardrails: a scope check before retrieval and a groundedness check after generation.

Both are deliberately simple rules. The scope check catches hiring predictions
and obvious attempts to override the coach's instructions; off-topic questions
are mostly caught later, when retrieval finds nothing relevant. Neither is a
guarantee, which is why the evaluation set includes adversarial prompts.
"""

import re

NOT_IN_SOURCES = "not in the sources"

_OUTCOME = (
    r"(hired|selected|shortlisted|rejected|placed|an? offer|through|"
    r"(the|this) (job|role|position|interview)(?! description))"
)
_HIRING_PREDICTION = [
    # "will I get this job", "can I be shortlisted", "am I going to be selected"
    r"\b(will|would|shall|can|could|do|am)\s+i\b.{0,40}"
    r"\b(get|be|land|clear|pass|crack|make it|going to)\b.{0,30}\b" + _OUTCOME + r"\b",
    # "what are my chances of getting an interview", "how likely am I to be hired"
    r"\b(chance|chances|probability|odds|likelihood|likely)\b.{0,60}"
    r"\b(hired|hire|selected|selection|shortlist\w*|job|offer|interview|placement|placed|"
    r"rejected)\b",
    r"\bpredict\w*\b.{0,60}\b(hir\w+|select\w+|shortlist\w*|outcome|result|offer)\b",
    r"\bguarantee\w*\b.{0,60}\b(job|offer|hired|selected|shortlist\w*|interview)\b",
    r"\b(rank|compare)\s+me\b.{0,40}\b(against|with|among|to)\b.{0,30}"
    r"\b(candidates|applicants|others|students)\b",
]
# "how do I improve my chances" asks for advice, not a prediction
_ADVICE = re.compile(
    r"\b(improve|increase|boost|raise|better|maximi[sz]e)\b.{0,25}\b(chance|chances|odds)\b",
    re.IGNORECASE,
)
_INJECTION = [
    r"\b(ignore|disregard|forget|override)\b.{0,40}"
    r"\b(instruction|instructions|rules|prompt|prompts|guidelines|above|previous)\b",
    r"\b(system|developer|hidden)\s+(prompt|message|instructions)\b",
    r"\b(reveal|show|print|repeat)\b.{0,30}\b(your|the)\s+(prompt|instructions|rules)\b",
    r"\bpretend (you|to be|that)\b|\brole-?play\b|\byou are now\b|\bjailbreak\b",
    r"\bdeveloper mode\b",
    r"\bwithout (citing|citations|sources)\b|\bdo(n't| not) (cite|use the sources)\b",
]
_HIRING_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _HIRING_PREDICTION]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION]

DECLINE_MESSAGES = {
    "hiring_prediction": (
        "I can't predict whether you will be hired, shortlisted or selected. "
        "I can help you see what this job description asks for and how to show it on your resume."
    ),
    "prompt_injection": (
        "I can only answer questions about your resume, this job description and career "
        "preparation, using the supplied sources with citations."
    ),
}

_CITATION = re.compile(r"\[\s*((?:[RJG]\d+)(?:\s*[,;]\s*[RJG]\d+)*)\s*\]")


def scope_check(question: str) -> str | None:
    """Return a decline reason ("hiring_prediction" or "prompt_injection"), or None if in scope."""
    if any(p.search(question) for p in _INJECTION_RE):
        return "prompt_injection"
    if any(p.search(question) for p in _HIRING_RE) and not _ADVICE.search(question):
        return "hiring_prediction"
    return None


def extract_citations(answer: str) -> list[str]:
    """Passage ids cited in the answer, in order of first use, e.g. ["G3", "R12"]."""
    ids: list[str] = []
    for match in _CITATION.finditer(answer):
        for pid in re.split(r"\s*[,;]\s*", match.group(1)):
            if pid not in ids:
                ids.append(pid)
    return ids


def check_grounded(answer: str, retrieved_ids: set[str]) -> tuple[str, list[str]]:
    """Classify a generated answer.

    Returns (verdict, cited_ids) where verdict is one of:
      "ok"                 at least one citation, and every cited id was retrieved
      "not_in_sources"     the model said the sources do not cover the question
      "no_citation"        rejected: claims without any citation
      "unknown_citation"   rejected: cites an id that was not retrieved
    """
    cited = extract_citations(answer)
    if any(pid not in retrieved_ids for pid in cited):
        return "unknown_citation", cited
    if not cited:
        if NOT_IN_SOURCES in answer.lower():
            return "not_in_sources", []
        return "no_citation", []
    return "ok", cited
