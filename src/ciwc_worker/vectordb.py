"""Hybrid passage retrieval over policy wordings in Qdrant.

Storing makes no assumption about the policy's layout, so messy OCR or text-layer output works as well as
clean text. The policy is cut into overlapping windows of about CHUNK_CHARS characters, ending at a
paragraph break, line break or space where one is near. Each window is stored with its page numbers, its
character offsets, a dense Gemini vector and a BM25 sparse vector that Qdrant computes itself.

Retrieval is hit -> neighbours -> passage: a dense and a BM25 search inside one policy are fused with
Reciprocal Rank Fusion, each hit is widened by NEIGHBOURS windows on either side, windows that overlap or
touch are merged, and each merged run is stitched back into one continuous passage from the offsets. So a
match that falls at the edge of a window still comes back with the text around it.
"""

import logging
import os
import threading
import uuid
from bisect import bisect_right
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from ciwc_worker.llm import EMBED_MODEL, embeddings

logger = logging.getLogger(__name__)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.environ.get(
    "QDRANT_COLLECTION",
    "policy_chunks_" + "".join(c if c.isalnum() else "_" for c in EMBED_MODEL.lower()),
)
RETRIEVAL_K = int(os.environ.get("RETRIEVAL_K", "4"))
CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
BREAK_ZONE = 0.2
NEIGHBOURS = 1
HITS_PER_PASSAGE = 2
PREFETCH_LIMIT = 20
EMBED_BATCH = 16
PAGE_SEPARATOR = "\n\n"
DENSE = "dense"
SPARSE = "bm25"
BM25_MODEL = "Qdrant/bm25"
BREAKS = ("\n\n", "\n", " ")
WHITESPACE = (" ", "\n", "\t")

_local = threading.local()


@dataclass
class Chunk:
    """One stored window of policy text."""

    order: int
    start: int
    end: int
    page_start: int
    page_end: int
    text: str


@dataclass
class Passage:
    """A retrieved run of neighbouring windows, stitched into continuous text."""

    location: str
    text: str
    score: float


def client() -> QdrantClient:
    """Qdrant client of the current thread.

    BM25 `Document`s are embedded by the Qdrant server, but the client still batches them in per-client state
    that is not thread-safe, so the parallel graph branches each get their own client.
    """
    if not hasattr(_local, "client"):
        _local.client = QdrantClient(url=QDRANT_URL)

    return _local.client


def ensure_collection() -> None:
    """Create the collection with dense and BM25 vectors and a policy_id index, if it does not exist yet.

    The default collection name contains the embedding model, so switching models starts a new collection.
    """
    qdrant = client()
    dim = len(embeddings().embed_query("dimension probe", task_type="RETRIEVAL_QUERY"))

    if qdrant.collection_exists(COLLECTION):
        size = qdrant.get_collection(COLLECTION).config.params.vectors[DENSE].size
        if size != dim:
            raise ValueError(
                f"{COLLECTION} has {size}-d vectors but {EMBED_MODEL} gives {dim}-d; "
                "set QDRANT_COLLECTION to a new name"
            )
        return

    qdrant.create_collection(
        COLLECTION,
        vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    qdrant.create_payload_index(COLLECTION, "policy_id", models.PayloadSchemaType.KEYWORD)

    logger.info("created Qdrant collection %s (%d-d dense + BM25)", COLLECTION, dim)


def _window_end(text: str, start: int) -> int:
    """End of the window that starts at `start`.

    It is the last paragraph break, else line break, else space inside the final BREAK_ZONE of the window,
    so a window rarely ends mid-word; text with no break there is cut at CHUNK_CHARS.
    """
    limit = start + CHUNK_CHARS
    if limit >= len(text):
        return len(text)

    zone = limit - int(CHUNK_CHARS * BREAK_ZONE)
    for mark in BREAKS:
        cut = text.rfind(mark, zone, limit)
        if cut != -1:
            return cut + len(mark)

    return limit


def _next_start(text: str, start: int, end: int) -> int:
    """Start of the next window: OVERLAP_CHARS before `end`, moved forward to the start of a word."""
    position = max(end - OVERLAP_CHARS, start + 1)

    while position < end and text[position - 1] not in WHITESPACE:
        position += 1

    return position


def _windows(text: str) -> list[tuple[int, int]]:
    """(start, end) character spans of overlapping windows covering the whole text."""
    spans = []
    start = 0

    while start < len(text):
        end = _window_end(text, start)
        spans.append((start, end))
        if end >= len(text):
            break
        start = _next_start(text, start, end)

    return spans


def chunk_policy(pages: list[str], policy_name: str) -> list[Chunk]:
    """Cut the policy into overlapping windows, each with its 1-based page range.

    The policy text is the pages joined with PAGE_SEPARATOR. Windows holding only whitespace are dropped.
    """
    text = PAGE_SEPARATOR.join(pages)

    page_starts = []
    offset = 0
    for page in pages:
        page_starts.append(offset)
        offset += len(page) + len(PAGE_SEPARATOR)

    chunks: list[Chunk] = []
    for start, end in _windows(text):
        piece = text[start:end]
        if not piece.strip():
            continue

        chunks.append(Chunk(
            order=len(chunks),
            start=start,
            end=end,
            page_start=bisect_right(page_starts, start),
            page_end=bisect_right(page_starts, max(start, end - 1)),
            text=piece,
        ))

    logger.info("policy %s: %d characters in %d windows", policy_name, len(text), len(chunks))
    return chunks


def _policy_filter(policy_id: str) -> models.Filter:
    """Restrict a search or delete to one policy."""
    return models.Filter(must=[models.FieldCondition(key="policy_id", match=models.MatchValue(value=policy_id))])


def _point_id(policy_id: str, order: int) -> str:
    """Stable point id of a policy's window, so neighbours can be fetched by id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{policy_id}/{order}"))


def _point(policy_id: str, label: str, chunk: Chunk, dense: list[float]) -> models.PointStruct:
    """Qdrant point of one window: its id, the dense vector, the BM25 document and the payload."""
    return models.PointStruct(
        id=_point_id(policy_id, chunk.order),
        vector={
            DENSE: dense,
            SPARSE: models.Document(text=chunk.text, model=BM25_MODEL),
        },
        payload={
            "policy_id": policy_id,
            "policy_label": label,
            "order": chunk.order,
            "start": chunk.start,
            "end": chunk.end,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text": chunk.text,
        },
    )


def index_policy(policy_id: str, label: str, chunks: list[Chunk]) -> int:
    """Replace the policy's points with `chunks`, embedded dense and BM25; return the number of points.

    The points are upserted over the old ones by id, then only the old points past the new last window are
    deleted. The policy is never empty in between, so another job comparing the same PDF at the same time
    keeps finding its windows.
    """
    qdrant = client()

    vectors = embeddings().embed_documents(
        [chunk.text for chunk in chunks],
        task_type="RETRIEVAL_DOCUMENT",
        batch_size=EMBED_BATCH,
    )

    points = [_point(policy_id, label, chunk, dense) for chunk, dense in zip(chunks, vectors, strict=True)]
    qdrant.upsert(COLLECTION, points=points, wait=True)

    stale = models.Filter(must=[
        models.FieldCondition(key="policy_id", match=models.MatchValue(value=policy_id)),
        models.FieldCondition(key="order", range=models.Range(gte=len(points))),
    ])
    qdrant.delete(COLLECTION, points_selector=models.FilterSelector(filter=stale), wait=True)

    logger.info("indexed policy %s (%s): %d windows", label, policy_id, len(points))
    return len(points)


def _runs(hits: list[tuple[int, float]]) -> list[tuple[int, int, float]]:
    """Widen each (order, score) hit by NEIGHBOURS windows and merge runs that overlap or touch.

    Returns (first order, last order, best score) per run, in policy order.
    """
    spans = sorted((max(0, order - NEIGHBOURS), order + NEIGHBOURS, score) for order, score in hits)
    runs: list[tuple[int, int, float]] = []

    for first, last, score in spans:
        if runs and first <= runs[-1][1] + 1:
            prev_first, prev_last, prev_score = runs[-1]
            runs[-1] = (prev_first, max(prev_last, last), max(prev_score, score))
        else:
            runs.append((first, last, score))

    return runs


def _stitch(windows: list[dict]) -> str:
    """Join neighbouring windows into continuous text, dropping the part each one shares with the last."""
    text = ""
    end = 0

    for window in windows:
        skip = max(0, end - window["start"])
        text += window["text"][skip:]
        end = max(end, window["end"])

    return text.strip()


def _location(windows: list[dict]) -> str:
    """Page range of a passage, e.g. "page 3" or "pages 3-4"."""
    first = windows[0]["page_start"]
    last = windows[-1]["page_end"]

    return f"page {first}" if first == last else f"pages {first}-{last}"


def retrieve(policy_id: str, query: str, k: int = RETRIEVAL_K) -> list[Passage]:
    """The `k` best passages of one policy for `query`, in the order they appear in the policy.

    Dense and BM25 searches are fused with RRF; the top k * HITS_PER_PASSAGE windows are widened by their
    neighbours, merged into runs, ranked by their best hit, and the top k runs are fetched by id and stitched.
    """
    only_policy = _policy_filter(policy_id)
    dense = embeddings().embed_query(query, task_type="RETRIEVAL_QUERY")
    sparse = models.Document(text=query, model=BM25_MODEL)
    qdrant = client()

    hits = qdrant.query_points(
        COLLECTION,
        prefetch=[
            models.Prefetch(query=dense, using=DENSE, filter=only_policy, limit=PREFETCH_LIMIT),
            models.Prefetch(query=sparse, using=SPARSE, filter=only_policy, limit=PREFETCH_LIMIT),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=only_policy,
        limit=k * HITS_PER_PASSAGE,
        with_payload=["order"],
    ).points

    runs = sorted(_runs([(hit.payload["order"], hit.score) for hit in hits]), key=lambda run: -run[2])[:k]
    runs.sort()

    orders = sorted({order for first, last, _ in runs for order in range(first, last + 1)})
    fetched = qdrant.retrieve(COLLECTION, ids=[_point_id(policy_id, order) for order in orders], with_payload=True)
    windows = {point.payload["order"]: point.payload for point in fetched}

    passages = []
    for first, last, score in runs:
        run = [windows[order] for order in range(first, last + 1) if order in windows]
        if run:
            passages.append(Passage(location=_location(run), text=_stitch(run), score=score))

    return passages
