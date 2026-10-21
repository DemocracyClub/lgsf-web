import json
from collections import defaultdict

import boto3
from core.forms import DecisionSearchForm, VectorSearchForm
from core.models import Chunk, Decision, Embedding
from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import DetailView
from modelsearch.query import Phrase
from pgvector.django import CosineDistance


def hello_world(request):
    return HttpResponse("Hello, world.")


RRF_K = 60
DECISION_SEARCH_LIMIT = 100
CHUNK_SEARCH_LIMIT = 1000
MAX_CHUNKS_PER_DECISION = 5


def fused_decision_search(decisions, chunks, query):
    """
    Reciprocal rank fusion of Decision and Chunk search results.

    Returns Decisions ordered by fused score, each with `rrf_score` and
    `matched_chunks` attributes. Decisions matched only via their chunks
    are included.
    """
    decision_hits = list(decisions.search(query)[:DECISION_SEARCH_LIMIT])
    chunk_hits = list(
        chunks.select_related("document").search(query)[:CHUNK_SEARCH_LIMIT]
    )

    scores = defaultdict(float)
    matched_chunks = defaultdict(list)

    for rank, decision in enumerate(decision_hits, start=1):
        scores[decision.pk] += 1 / (RRF_K + rank)

    for rank, chunk in enumerate(chunk_hits, start=1):
        decision_id = chunk.document.decision_id
        scores[decision_id] += 1 / (RRF_K + rank)
        # Chunks arrive in rank order, so the first N are the most relevant
        if len(matched_chunks[decision_id]) < MAX_CHUNKS_PER_DECISION:
            matched_chunks[decision_id].append(chunk)

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
        queryset = form.filter_decisions(
            Decision.objects.all().prefetch_related("documents")
        )

        if query := form.cleaned_data["q"]:
            if form.cleaned_data["search_mode"] == "phrase":
                query = Phrase(query)
            chunks = form.filter_decisions(
                Chunk.objects.all(), prefix="document__decision__"
            )
            results = fused_decision_search(queryset, chunks, query)
        else:
            results = queryset

    context = {
        "form": form,
        "results": results,
    }
    return render(request, "core/decision_search.html", context)


TITAN_MODEL = "amazon.titan-embed-text-v2:0"
TITAN_DIMENSIONS = 1024
VECTOR_SEARCH_LIMIT = 100


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


def vector_search(request):
    form = VectorSearchForm(request.GET or None)
    results = []

    if form.is_valid():
        decisions = form.filter_decisions(Decision.objects.all())

        BATCH_SIZE = 10
        MAX_RESULTS = 100
        MIN_RESULTS_BEFORE_STOP = 5
        DISTANCE_GAP_THRESHOLD = 0.01

        query_embedding = embed_text(form.cleaned_data["q"])

        embeddings = (
            Embedding.objects.filter(
                model=TITAN_MODEL,
                chunk__document__decision__in=decisions.values("pk"),
            )
            .select_related("chunk__document__decision__council")
            .annotate(distance=CosineDistance("embedding", query_embedding))
            .order_by("distance")
        )

        results = []
        offset = 0
        stop = False

        while len(results) < MAX_RESULTS and not stop:
            batch = list(embeddings[offset : offset + BATCH_SIZE])

            if not batch:
                break

            for embedding in batch:
                distance = embedding.distance

                # Once we have enough results, look for a substantial
                # deterioration in relevance.
                if len(results) >= MIN_RESULTS_BEFORE_STOP:
                    previous_distance = results[-1]["distance"]
                    gap = distance - previous_distance

                    if gap >= DISTANCE_GAP_THRESHOLD:
                        stop = True
                        break

                results.append(
                    {
                        "chunk": embedding.chunk,
                        "distance": distance,
                    }
                )

            offset += len(batch)

    context = {
        "form": form,
        "results": results,
    }
    return render(request, "core/vector_search.html", context)


class DecisionDetailView(DetailView):
    model = Decision
    template_name = "core/decision_detail.html"
    queryset = Decision.objects.all().prefetch_related("documents")
