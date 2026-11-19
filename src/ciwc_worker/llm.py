"""Gemini calls of the comparison graph: outline code generation, subject taxonomy and subject comparison."""

import logging
import os
import re
from functools import cache
from itertools import pairwise
from typing import Literal

import pydantic_monty
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic import BaseModel, Field

from ciwc_worker.prompt import render_prompt

logger = logging.getLogger(__name__)

LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
CODEGEN_MODEL = os.environ.get("CODEGEN_MODEL", "gemini-4-hydrogen")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-2")
MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "32768"))
CODEGEN_THINKING_LEVEL = os.environ.get("CODEGEN_THINKING_LEVEL", "low")
MAX_ATTEMPTS = 3
CODEGEN_ATTEMPTS = 4
SAMPLE_PAGES = 2
EXTRA_SAMPLE_PAGES = 2
MAX_SAMPLE_PAGE_CHARS = 8000
MAX_HEADING_SHARE = 0.5
MIN_REVIEWED_HEADINGS = 10
LONG_CLAUSE_CHARS = 15000
MAX_REVIEW_LINES = 30
MAX_REVIEW_LINE_CHARS = 120
SANDBOX_LIMITS = {"max_feed_duration_secs": 10, "max_memory": 256 * 1024 * 1024}
CATCH_ALL_KEYS = {"other", "others", "miscellaneous", "general"}

Verdict = Literal["equivalent", "A_more_favourable", "B_more_favourable", "only_in_A", "only_in_B"]


class Subject(BaseModel):
    """One insurance subject both policies are compared on."""

    key: str = Field(description="Unique lowercase snake_case identifier of 1-4 words")
    description: str = Field(description="Plain phrase of 3-12 words saying what falls under the subject")


class Subjects(BaseModel):
    """The subject taxonomy of the two policies."""

    subjects: list[Subject]


class Comparison(BaseModel):
    """Verdict on one subject; `reason` comes first so the model reasons before it decides."""

    subject: str = Field(description="The subject key")
    reason: str = Field(description="1-3 sentences naming the specific differences that decide the verdict")
    verdict: Verdict


def _api_key() -> str:
    """Return the Gemini API key from the environment."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    return key


@cache
def chat(model: str = LLM_MODEL, thinking_level: str | None = None) -> ChatGoogleGenerativeAI:
    """Deterministic Gemini chat model on the Gemini Developer API.

    Thinking tokens count against `max_output_tokens`. On the outline codegen prompt the default thinking
    ran long enough to cut off or empty the reply, so that call passes a low `thinking_level`.
    """
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=0,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_level=thinking_level,
        api_key=_api_key(),
        vertexai=False,
    )


@cache
def embeddings() -> GoogleGenerativeAIEmbeddings:
    """Dense embedding model used for both clause indexing and subject queries."""
    return GoogleGenerativeAIEmbeddings(model=EMBED_MODEL, google_api_key=_api_key(), vertexai=False)


def _codegen_reply(messages: list[BaseMessage]) -> AIMessage:
    """Ask CODEGEN_MODEL for code, or LLM_MODEL when CODEGEN_MODEL stays unavailable after its own retries."""
    try:
        return chat(CODEGEN_MODEL, CODEGEN_THINKING_LEVEL).invoke(messages)

    except Exception as e:
        if CODEGEN_MODEL == LLM_MODEL:
            raise
        logger.warning("%s failed (%s: %s); using %s", CODEGEN_MODEL, type(e).__name__, str(e)[:200], LLM_MODEL)
        return chat(LLM_MODEL, CODEGEN_THINKING_LEVEL).invoke(messages)


def _extract_code(reply: str) -> str:
    """Return the body of the first fenced code block in `reply`, or the whole reply if there is none."""
    match = re.search(r"```(?:python)?[ \t]*\n(.*?)```", reply, re.DOTALL)
    code = match.group(1) if match else reply

    return code.strip("\n")


def _sample(pages: list[str]) -> str:
    """The first SAMPLE_PAGES pages plus EXTRA_SAMPLE_PAGES spread over the rest, each tagged with its number.

    Later pages often switch heading style (definitions, conditions, endorsements), so the codegen prompt
    sees more than the opening pages.
    """
    rest = list(range(SAMPLE_PAGES, len(pages)))
    extra = {rest[len(rest) * (k + 1) // (EXTRA_SAMPLE_PAGES + 1)] for k in range(EXTRA_SAMPLE_PAGES)} if rest else set()
    picks = sorted(set(range(min(SAMPLE_PAGES, len(pages)))) | extra)

    return "\n\n".join(
        f'<page number="{i + 1}" of="{len(pages)}">\n{pages[i][:MAX_SAMPLE_PAGE_CHARS]}\n</page>' for i in picks
    )


def _check_outline(result: object, lines: list[str]) -> list[int]:
    """The result must be ascending, unique line numbers of non-blank lines of `text`."""
    if not isinstance(result, list | tuple) or not all(isinstance(i, int) and not isinstance(i, bool) for i in result):
        raise TypeError(f"extract_outline(text) must return a list of int, got {type(result).__name__}")

    starts = list(result)
    for before, after in pairwise(starts):
        if after <= before:
            raise ValueError(f"line numbers must be ascending and unique: {before} then {after}")

    for i in starts:
        if not 0 <= i < len(lines):
            raise ValueError(f"line number {i} is outside 0..{len(lines) - 1}")
        if not lines[i].strip():
            raise ValueError(f"line {i} is blank")

    return starts


def _run_in_sandbox(code: str, text: str) -> list[int]:
    """Run LLM-written code in a fresh Monty session with `text` as its only input."""
    with pydantic_monty.Monty() as pool, pool.checkout(limits=SANDBOX_LIMITS) as session:
        result = session.feed_run(code, inputs={"text": text})

    return _check_outline(result, text.splitlines())


def _review(starts: list[int], lines: list[str]) -> str | None:
    """Problems of an outline that ran without error, worded as feedback for the LLM, or None if it looks right.

    Too many kept lines means body text is kept. A very long stretch without a kept line usually means a
    heading style the sample did not show, so its short lines are listed for the LLM to judge.
    """
    nonblank = sum(1 for line in lines if line.strip())

    if not starts:
        return "It kept no lines. If the policy has headings, fix the patterns."

    if len(starts) > max(MIN_REVIEWED_HEADINGS, MAX_HEADING_SHARE * nonblank):
        return (
            f"It kept {len(starts)} of {nonblank} non-blank lines, so it keeps body text, list items or "
            "wrapped lines. Keep only lines that start a clause."
        )

    bounds = [0, *starts, len(lines)]
    size, start, end = max(
        (sum(len(line) + 1 for line in lines[a:b]), a, b) for a, b in pairwise(bounds)
    )
    if size <= LONG_CLAUSE_CHARS:
        return None

    short = [
        f"{i}: {lines[i]}" for i in range(start + 1, end)
        if lines[i].strip() and len(lines[i].strip()) <= MAX_REVIEW_LINE_CHARS
    ][:MAX_REVIEW_LINES]
    if not short:
        return None

    listing = "\n".join(short)
    return (
        f"Lines {start}-{end - 1} ({size} characters) contain no kept line. These are short lines in that "
        f"stretch:\n{listing}\n"
        "If some of them start clauses in a style the code misses, fix the patterns. If none of them does, "
        "reply with the same code unchanged."
    )


def generate_outline(pages: list[str]) -> tuple[str, list[int]]:
    """Let the LLM write regex code from sample pages, run it on the whole policy, return (code, start lines).

    The start lines are indices into `"\\n\\n".join(pages).splitlines()`. Sandbox errors, invalid results and
    review findings are sent back to the LLM to fix. When no attempt gives a reviewed outline, the last
    outline that ran is used, and when none ran the result is empty, so the policy is chunked as passages
    instead of failing the comparison.
    """
    text = "\n\n".join(pages)
    lines = text.splitlines()

    prompt = render_prompt("clause_outline_codegen_prompt", sample=_sample(pages))
    messages: list[BaseMessage] = [HumanMessage(prompt)]
    best: tuple[str, list[int]] | None = None

    for attempt in range(1, CODEGEN_ATTEMPTS + 1):
        reply = _codegen_reply(messages)
        code = _extract_code(reply.text)

        try:
            if reply.response_metadata.get("finish_reason") == "MAX_TOKENS":
                raise RuntimeError("the reply was cut off at the output token limit; reply with shorter code")
            starts = _run_in_sandbox(code, text)

        except Exception as e:
            logger.warning("outline code attempt %d failed: %s: %s", attempt, type(e).__name__, str(e)[:300])
            feedback = f"That failed with:\n{type(e).__name__}: {e}\nFix the code. Reply with only the code."

        else:
            if best is not None and code == best[0]:
                return best

            best = (code, starts)
            problem = _review(starts, lines)
            if problem is None:
                return best

            logger.info("outline code attempt %d: %d lines kept, sent back: %s", attempt, len(starts), problem[:200])
            feedback = f"The code ran and returned {len(starts)} line numbers. {problem}\nReply with only the code."

        messages += [AIMessage(f"```python\n{code}\n```"), HumanMessage(feedback)]

    if best is None:
        logger.warning("no working outline code after %d attempts; chunking the policy as passages", CODEGEN_ATTEMPTS)
        return "", []

    logger.warning("outline not confirmed after %d attempts; using the last one that ran", CODEGEN_ATTEMPTS)
    return best


def _check_subjects(result: Subjects | None) -> list[Subject]:
    """Reject empty, non-snake_case, duplicate and catch-all subjects."""
    if result is None or not result.subjects:
        raise ValueError("no subjects returned")

    keys = [subject.key for subject in result.subjects]

    bad = [key for key in keys if not re.fullmatch(r"[a-z][a-z0-9_]*", key)]
    if bad:
        raise ValueError(f"keys must be lowercase snake_case: {bad}")

    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"keys must be unique; merge duplicates: {duplicates}")

    catch_all = [key for key in keys if key in CATCH_ALL_KEYS]
    if catch_all:
        raise ValueError(f"do not return a catch-all subject: {catch_all}")

    return result.subjects


def generate_subjects(outline_a: str, outline_b: str) -> list[Subject]:
    """Build one subject taxonomy from the outlines of both policies."""
    llm = chat().with_structured_output(Subjects)

    prompt = render_prompt("subject_taxonomy_prompt", outline_a=outline_a, outline_b=outline_b)
    messages: list[BaseMessage] = [HumanMessage(prompt)]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _check_subjects(llm.invoke(messages))

        except Exception as e:
            logger.warning("subject attempt %d failed: %s: %s", attempt, type(e).__name__, str(e)[:300])
            messages.append(HumanMessage(f"Your answer was invalid: {e}\nAnswer again."))

    raise RuntimeError(f"no valid subjects after {MAX_ATTEMPTS} attempts")


def compare_subject(
    subject: Subject,
    policy_a_text: str,
    policy_b_text: str,
    other_subjects: list[Subject],
) -> Comparison:
    """Judge which policy is more favourable to the insured on one subject, from the retrieved clauses.

    `other_subjects` tells the model which topics are judged separately, so it does not count them here.
    """
    others = "\n".join(f"- {s.key}: {s.description}" for s in other_subjects if s.key != subject.key)

    prompt = render_prompt(
        "subject_comparison_prompt",
        subject_key=subject.key,
        subject_description=subject.description,
        other_subjects=others,
        policy_a_text=policy_a_text,
        policy_b_text=policy_b_text,
    )

    result = chat().with_structured_output(Comparison).invoke([HumanMessage(prompt)])
    if result is None:
        raise ValueError(f"no comparison returned for {subject.key}")

    return result.model_copy(update={"subject": subject.key})
