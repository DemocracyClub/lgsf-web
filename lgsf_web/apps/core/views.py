import json
from collections import defaultdict

import boto3
from core.forms import DecisionSearchForm
from core.models import Chunk, Council, Decision, Document, Embedding
from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.core.paginator import Paginator
from django.db.models import Count, IntegerField, Model, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.generic import DetailView, ListView
from modelsearch.query import Phrase
from pgvector.django import CosineDistance


def hello_world(request):
    return HttpResponse("Hello, world.")


RRF_K = 60
DECISION_SEARCH_LIMIT = 100
CHUNK_SEARCH_LIMIT = 1000
MAX_CHUNKS_PER_DECISION = 5
SEARCH_RESULTS_PER_PAGE = 20


def fuse_chunks(*ranked_lists):
    """Reciprocal rank fusion of ranked Chunk lists, de-duplicated by pk."""
    scores = defaultdict(float)
    by_pk = {}
    for hits in ranked_lists:
        for rank, chunk in enumerate(hits, start=1):
            scores[chunk.pk] += 1 / (RRF_K + rank)
            by_pk.setdefault(chunk.pk, chunk)
    return [by_pk[pk] for pk in sorted(scores, key=scores.get, reverse=True)]


def fused_decision_search(decisions, chunks, query, vector_chunks=()):
    """
    Reciprocal rank fusion of Decision and Chunk search results.

    Full-text and vector Chunk hits are fused first, then fused with the
    Decision hits. Returns Decisions ordered by fused score, each with
    `rrf_score` and `matched_chunks` attributes. Decisions matched only
    via their chunks are included.
    """
    decision_hits = list(decisions.search(query)[:DECISION_SEARCH_LIMIT])
    fts_chunks = list(
        chunks.select_related("document__decision")
        .defer("document__text")
        .search(query)[:CHUNK_SEARCH_LIMIT]
    )
    chunk_hits = fuse_chunks(fts_chunks, vector_chunks)

    scores = defaultdict(float)
    matched_chunks = defaultdict(list)

    for rank, decision in enumerate(decision_hits, start=1):
        scores[decision.pk] += 1 / (RRF_K + rank)

    for rank, chunk in enumerate(chunk_hits, start=1):
        decision_id = chunk.document.decision_id
        # Only a decision's best chunks count, so many weak chunks can't
        # outrank one strong chunk. Chunks arrive in rank order.
        if len(matched_chunks[decision_id]) < MAX_CHUNKS_PER_DECISION:
            matched_chunks[decision_id].append(chunk)
            scores[decision_id] += 1 / (RRF_K + rank)

    by_pk = {decision.pk: decision for decision in decision_hits}
    missing = scores.keys() - by_pk.keys()
    by_pk.update(decisions.in_bulk(missing))

    results = []
    for pk in sorted(scores, key=scores.get, reverse=True):
        # in_bulk respects the filters, so a missing pk was filtered out
        if decision := by_pk.get(pk):
            decision.rrf_score = scores[pk]
            decision.matched_chunks = matched_chunks.get(pk, [])
            results.append(decision)
    return results


def decision_search(request):
    form = DecisionSearchForm(request.GET or None)
    results = []

    if form.is_valid():
        queryset = form.filter(
            Decision.objects.select_related("council").prefetch_related(
                "documents"
            )
        )

        if query := form.cleaned_data["q"]:
            if form.cleaned_data["search_mode"] == "phrase":
                query = Phrase(query)
            chunks = form.filter(
                Chunk.objects.all(), prefix="document__decision__"
            )

            vector_chunks = []
            # Semantic similarity is meaningless for an exact phrase match
            if form.cleaned_data["search_mode"] != "phrase":
                embeddings = form.filter(
                    Embedding.objects.select_related(
                        "chunk__document__decision"
                    ).defer("chunk__document__text"),
                    prefix="chunk__document__decision__",
                )
                vector_chunks = [
                    hit["chunk"]
                    for hit in similar_chunks(
                        form.cleaned_data["q"], embeddings
                    )
                ]

            results = fused_decision_search(
                queryset, chunks, query, vector_chunks
            )
        else:
            results = queryset.order_by("-publication_date", "pk")

    page = Paginator(results, SEARCH_RESULTS_PER_PAGE).get_page(
        request.GET.get("page")
    )
    params = request.GET.copy()
    params.pop("page", None)

    context = {
        "form": form,
        "page": page,
        "querystring": params.urlencode(),
        "query": form.cleaned_data.get("q", "") if form.is_valid() else "",
    }
    return render(request, "core/decision_search.html", context)


TITAN_MODEL = "amazon.titan-embed-text-v2:0"
TITAN_DIMENSIONS = 1024


def embed_text(text):
    client = boto3.client("bedrock-runtime", region_name="eu-west-2")
    response = client.invoke_model(
        modelId=TITAN_MODEL,
        body=json.dumps(
            {
                "inputText": text,
                "dimensions": TITAN_DIMENSIONS,
                "normalize": True,
            }
        ),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


VECTOR_BATCH_SIZE = 10
VECTOR_MAX_RESULTS = 100
VECTOR_MIN_RESULTS_BEFORE_STOP = 5
VECTOR_DISTANCE_GAP_THRESHOLD = 0.01


def similar_chunks(text, embeddings):
    """
    Nearest chunks to `text` as [{"chunk", "distance"}, ...], closest first.

    `embeddings` is an Embedding queryset, already filtered as required.
    """
    query_embedding = embed_text(text)
    embeddings = (
        embeddings.filter(model=TITAN_MODEL)
        .annotate(distance=CosineDistance("embedding", query_embedding))
        .order_by("distance")
    )

    results = []
    offset = 0

    while len(results) < VECTOR_MAX_RESULTS:
        batch = list(embeddings[offset : offset + VECTOR_BATCH_SIZE])

        if not batch:
            break

        for embedding in batch:
            distance = embedding.distance

            # Once we have enough results, look for a substantial
            # deterioration in relevance.
            if len(results) >= VECTOR_MIN_RESULTS_BEFORE_STOP:
                gap = distance - results[-1]["distance"]
                if gap >= VECTOR_DISTANCE_GAP_THRESHOLD:
                    return results

            results.append({"chunk": embedding.chunk, "distance": distance})

        offset += len(batch)

    return results


class DecisionDetailView(DetailView):
    model = Decision
    template_name = "core/decision_detail.html"
    queryset = Decision.objects.all().prefetch_related("documents")


def councils_with_counts():
    def count_per_council(model: type[Model], council_field: str) -> Coalesce:
        counts = (
            model.objects.filter(**{council_field: OuterRef("pk")})
            .values(council_field)
            .annotate(count=Count("pk"))
            .values("count")
        )
        return Coalesce(Subquery(counts, output_field=IntegerField()), 0)

    return Council.objects.annotate(
        decision_count=count_per_council(Decision, "council"),
        document_count=count_per_council(Document, "decision__council"),
        scraped_councillor_count=count_per_council(
            ScrapedCouncillor, "council"
        ),
        enriched_councillor_count=count_per_council(
            EnrichedCouncillor, "base_councillor__council"
        ),
    )


class CouncilListView(ListView):
    template_name = "core/council_list.html"
    context_object_name = "councils"
    queryset = councils_with_counts().order_by("territory", "name")


class CouncilDetailView(DetailView):
    template_name = "core/council_detail.html"
    context_object_name = "council"
    queryset = councils_with_counts()


class CouncilDecisionListView(ListView):
    template_name = "core/council_decisions.html"
    context_object_name = "decisions"

    def get_queryset(self):
        self.council = get_object_or_404(Council, pk=self.kwargs["pk"])
        return (
            Decision.objects.filter(council=self.council)
            .annotate(document_count=Count("documents"))
            .order_by("-raw_date", "pk")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["council"] = self.council
        return context
