"""LangGraph pipeline that compares two policy wording PDFs subject by subject.

    START -> prepare -> process_policy (A and B in parallel: read PDF, outline code in Monty, window chunks, index)
          -> generate_subjects (one taxonomy from both outlines)
          -> compare_subject (one per subject in parallel: hybrid passage retrieval per policy, LLM verdict)
          -> build_report -> END

Run: PYTHONPATH=src uv run python -m ciwc_worker.graph policy_A.pdf policy_B.pdf --out report.json
"""

import hashlib
import json
import logging
import operator
import os
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from ciwc_worker import llm, vectordb
from ciwc_worker.ocr import read_pdf

logger = logging.getLogger(__name__)

MAX_CONCURRENCY = int(os.environ.get("GRAPH_MAX_CONCURRENCY", "4"))
LABELS = ("A", "B")
OUTLINE_OPENING_CHARS = 150
VERDICT_LABELS = {
    "A_more_favourable": "A more favourable",
    "B_more_favourable": "B more favourable",
    "equivalent": "Equivalent",
    "only_in_A": "Only in A",
    "only_in_B": "Only in B",
}
REPORT_POLICY_FIELDS = ("file", "name", "policy_id", "pages", "chunks")


class PolicyError(ValueError):
    """A policy PDF cannot be compared (missing or without text); retrying would fail the same way."""


def _merge(left: dict, right: dict) -> dict:
    """Reducer that lets the parallel policy branches each add their own key."""
    return {**left, **right}


class CompareState(TypedDict, total=False):
    """Graph state: the two PDF paths in, the report out."""

    pdf_a: str
    pdf_b: str
    policies: Annotated[dict[str, dict[str, Any]], _merge]
    subjects: list[dict[str, str]]
    comparisons: Annotated[list[dict[str, Any]], operator.add]
    report: dict[str, Any]


class PolicyTask(TypedDict):
    """Input of one process_policy branch."""

    label: str
    path: str


class SubjectTask(TypedDict):
    """Input of one compare_subject branch."""

    subject: dict[str, str]
    all_subjects: list[dict[str, str]]
    policy_ids: dict[str, str]


def prepare(state: CompareState) -> dict:
    """Check both PDFs exist and create the Qdrant collection once, before the parallel branches start."""
    for key in ("pdf_a", "pdf_b"):
        if not Path(state[key]).is_file():
            raise PolicyError(f"{key} not found: {state[key]}")

    vectordb.ensure_collection()

    return {}


def dispatch_policies(state: CompareState) -> list[Send]:
    """Fan out one process_policy branch per policy."""
    return [
        Send("process_policy", PolicyTask(label=label, path=state[f"pdf_{label.lower()}"]))
        for label in LABELS
    ]


def _policy_name(text: str, fallback: str) -> str:
    """The first non-empty line of the policy, which is usually its title."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), fallback)
    return first_line[:120]


def _outline(text: str, starts: list[int], chunks: list[vectordb.Chunk]) -> str:
    """The outline for the subject taxonomy: the heading lines, or the opening line of each window if none."""
    lines = text.splitlines()
    if starts:
        return "\n".join(lines[i] for i in starts)

    openings = (chunk.text.strip().splitlines()[0] for chunk in chunks)
    return "\n".join(opening[:OUTLINE_OPENING_CHARS] for opening in openings)


def process_policy(task: PolicyTask) -> dict:
    """Read the PDF, extract its outline with LLM-written sandboxed code for the subjects, chunk and index it."""
    label = task["label"]
    path = Path(task["path"])

    pdf = path.read_bytes()
    policy_id = f"{hashlib.sha256(pdf).hexdigest()[:16]}-{label}"

    pages = read_pdf(pdf)
    text = "\n\n".join(pages)
    name = _policy_name(text, path.stem)

    code, starts = llm.generate_outline(pages)

    chunks = vectordb.chunk_policy(pages, name)
    if not chunks:
        raise PolicyError(f"policy {label} ({path.name}) produced no text to index")

    vectordb.index_policy(policy_id, label, chunks)

    outline = _outline(text, starts, chunks)

    logger.info(
        "policy %s: %d pages, %d outline lines, %d chunks",
        label, len(pages), len(starts), len(chunks),
    )

    policy = {
        "label": label,
        "file": str(path),
        "name": name,
        "policy_id": policy_id,
        "pages": len(pages),
        "outline": outline,
        "outline_code": code,
        "chunks": len(chunks),
    }
    return {"policies": {label: policy}}


def generate_subjects(state: CompareState) -> dict:
    """Build one subject taxonomy from both outlines, so every subject can be looked up in both policies."""
    policies = state["policies"]

    subjects = llm.generate_subjects(policies["A"]["outline"], policies["B"]["outline"])

    logger.info("%d subjects: %s", len(subjects), ", ".join(s.key for s in subjects))

    return {"subjects": [s.model_dump() for s in subjects]}


def dispatch_subjects(state: CompareState) -> list[Send] | str:
    """Fan out one compare_subject branch per subject."""
    subjects = state["subjects"]
    policy_ids = {label: policy["policy_id"] for label, policy in state["policies"].items()}

    tasks = [
        Send("compare_subject", SubjectTask(subject=subject, all_subjects=subjects, policy_ids=policy_ids))
        for subject in subjects
    ]

    return tasks or "build_report"


def _passages_block(passages: list[vectordb.Passage]) -> str:
    """Format retrieved passages for the comparison prompt, each under its page location."""
    return "\n\n".join(f"[{passage.location}]\n{passage.text}" for passage in passages)


def compare_subject(task: SubjectTask) -> dict:
    """Retrieve each policy's passages on the subject from Qdrant and let the LLM judge them."""
    subject = llm.Subject(**task["subject"])
    other_subjects = [llm.Subject(**s) for s in task["all_subjects"]]

    query = f"{subject.key.replace('_', ' ')}: {subject.description}"
    passages = {label: vectordb.retrieve(task["policy_ids"][label], query) for label in LABELS}

    result = llm.compare_subject(
        subject,
        _passages_block(passages["A"]),
        _passages_block(passages["B"]),
        other_subjects,
    )

    comparison = {
        "subject": subject.key,
        "description": subject.description,
        "verdict": result.verdict,
        "reason": result.reason,
        "policy_a_passages": [passage.location for passage in passages["A"]],
        "policy_b_passages": [passage.location for passage in passages["B"]],
    }
    return {"comparisons": [comparison]}


def _policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    """The policy fields shown in the report."""
    return {field: policy[field] for field in REPORT_POLICY_FIELDS}


def build_report(state: CompareState) -> dict:
    """Put the comparisons in subject order and count the verdicts."""
    order = {subject["key"]: i for i, subject in enumerate(state.get("subjects", []))}
    comparisons = sorted(
        state.get("comparisons", []),
        key=lambda comparison: order.get(comparison["subject"], len(order)),
    )

    report = {
        "policy_a": _policy_summary(state["policies"]["A"]),
        "policy_b": _policy_summary(state["policies"]["B"]),
        "summary": dict(Counter(comparison["verdict"] for comparison in comparisons)),
        "comparisons": comparisons,
    }
    return {"report": report}


def build_graph():
    """Compile the comparison graph; LLM and Qdrant nodes retry transient failures."""
    retry = RetryPolicy(max_attempts=3)
    builder = StateGraph(CompareState)

    builder.add_node("prepare", prepare, retry_policy=retry)
    builder.add_node("process_policy", process_policy, retry_policy=retry)
    builder.add_node("generate_subjects", generate_subjects, retry_policy=retry)
    builder.add_node("compare_subject", compare_subject, retry_policy=retry)
    builder.add_node("build_report", build_report)

    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", dispatch_policies, ["process_policy"])
    builder.add_edge("process_policy", "generate_subjects")
    builder.add_conditional_edges("generate_subjects", dispatch_subjects, ["compare_subject", "build_report"])
    builder.add_edge("compare_subject", "build_report")
    builder.add_edge("build_report", END)

    return builder.compile()


graph = build_graph()


def compare_policies(pdf_a: str, pdf_b: str) -> dict[str, Any]:
    """Run the graph on two PDF paths and return the comparison report."""
    inputs = {"pdf_a": str(pdf_a), "pdf_b": str(pdf_b)}

    state = graph.invoke(inputs, config={"max_concurrency": MAX_CONCURRENCY})

    return state["report"]


def _cell(text: Any) -> str:
    """Make text safe for one markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    """Human-readable report: the two policies, the verdict counts and one row per subject."""
    policy_a = report["policy_a"]
    policy_b = report["policy_b"]

    lines = [
        "# Policy wording comparison",
        "",
        f"- **Policy A:** {policy_a['name']} (`{policy_a['file']}`)",
        f"- **Policy B:** {policy_b['name']} (`{policy_b['file']}`)",
        "",
        "| Verdict | Subjects |",
        "|---|---|",
    ]
    for verdict, label in VERDICT_LABELS.items():
        lines.append(f"| {label} | {report['summary'].get(verdict, 0)} |")

    lines += [
        "",
        "| Subject | Verdict | Reason | Policy A passages | Policy B passages |",
        "|---|---|---|---|---|",
    ]
    for comparison in report["comparisons"]:
        verdict = VERDICT_LABELS.get(comparison["verdict"], comparison["verdict"])
        passages_a = "; ".join(comparison["policy_a_passages"])
        passages_b = "; ".join(comparison["policy_b_passages"])
        lines.append(
            f"| {_cell(comparison['subject'])} | {verdict} | {_cell(comparison['reason'])} "
            f"| {_cell(passages_a)} | {_cell(passages_b)} |"
        )

    return "\n".join(lines)


def main() -> None:
    """Command line entry point: compare two PDFs, print the markdown report, optionally save the JSON."""
    import argparse

    parser = argparse.ArgumentParser(description="Compare two insurance policy wording PDFs.")
    parser.add_argument("pdf_a")
    parser.add_argument("pdf_b")
    parser.add_argument("--out", help="also write the JSON report to this file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    report = compare_policies(args.pdf_a, args.pdf_b)

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(render_markdown(report))


if __name__ == "__main__":
    main()
