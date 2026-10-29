import datetime
import json

import boto3
from core.forms import DecisionSearchForm
from core.models import (
    Chunk,
    Council,
    Decision,
    DecisionEmbedding,
    Document,
)
from core.opensearch import (
    CHUNK,
    DECISION,
    INDEX_NAME,
    SEARCH_PIPELINE,
    opensearch_client,
)
from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, IntegerField, Model, OuterRef, Subquery
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.generic import DetailView, ListView
from pgvector.django import CosineDistance


def hello_world(request):
    return HttpResponse("Hello, world.")


MAX_CHUNKS_PER_DECISION = 5
SEARCH_RESULTS_PER_PAGE = 20
# How many chunk/decision hits to fetch, before grouping them by decision
MAX_SEARCH_HITS = 1000
KNN_K = 400
DECISION_BOOST = 3
# Each lower-ranked chunk counts this much of the one above it
CHUNK_RANK_DECAY = 0.7


def search_filters(data):
    filters = []
    for field in ("council", "status"):
        if data.get(field):
            filters.append({"term": {field: data[field]}})
    for field in (
        "is_key_decision",
        "is_officer_decision",
        "is_subject_to_call_in",
    ):
        if data.get(field):
            filters.append({"term": {field: True}})

    date_range = {}
    if data.get("publication_date_from"):
        date_range["gte"] = data["publication_date_from"].isoformat()
    if data.get("publication_date_to"):
        date_range["lte"] = data["publication_date_to"].isoformat()
    if date_range:
        filters.append({"range": {"publication_date": date_range}})
    return filters


def full_text_query(query, mode, filters):
    def match(fields):
        if mode == "phrase":
            return {
                "multi_match": {
                    "query": query,
                    "fields": fields,
                    "type": "phrase",
                }
            }
        multi_match = {"query": query, "fields": fields}
        if mode == "fuzzy":
            # Accents are folded by the field's analyzer
            multi_match["fuzziness"] = "AUTO"
        return {"multi_match": multi_match}

    decision_fields = [f"raw_title^{DECISION_BOOST}", f"text^{DECISION_BOOST}"]
    return {
        "bool": {
            # "text" is on both decisions and chunks, so each is matched
            # separately to boost only the decisions
            "should": [
                {
                    "bool": {
                        "filter": [{"term": {"object_type": DECISION}}],
                        "must": [match(decision_fields)],
                    }
                },
                {
                    "bool": {
                        "filter": [{"term": {"object_type": CHUNK}}],
                        "must": [match(["text"])],
                    }
                },
            ],
            "minimum_should_match": 1,
            "filter": filters,
        }
    }


def search_hits(data):
    query = data["q"]
    mode = data["search_mode"]
    filters = search_filters(data)
    text_query = full_text_query(query, mode, filters)

    request_kwargs = {}
    if mode == "phrase":
        # Exact phrases have no vector equivalent
        search_query = text_query
    else:
        search_query = {
            "hybrid": {
                # "pagination_depth": KNN_K,
                "queries": [
                    text_query,
                    {
                        "knn": {
                            "embedding": {
                                "vector": embed_text(query),
                                "k": KNN_K,
                                "filter": {"bool": {"filter": filters}},
                            }
                        }
                    },
                ]
            }
        }
        request_kwargs["params"] = {"search_pipeline": SEARCH_PIPELINE}

    response = opensearch_client().search(
        index=INDEX_NAME,
        body={"size": MAX_SEARCH_HITS, "query": search_query},
        **request_kwargs,
    )

    return response["hits"]["hits"]


def decisions_from_hits(hits):
    """
    Decisions ranked by the decision's own score plus the scores of its top
    MAX_CHUNKS_PER_DECISION chunks, each weighted down by its rank, with
    .matched_chunks set to those chunks. Hits are expected in descending
    score order.
    """
    chunk_ids_by_decision = {}
    scores = {}
    for hit in hits:
        decision_id = hit["_source"]["decision_id"]
        chunk_ids = chunk_ids_by_decision.setdefault(decision_id, [])
        scores.setdefault(decision_id, 0)
        if hit["_source"]["object_type"] != CHUNK:
            scores[decision_id] += hit["_score"]
        elif len(chunk_ids) < MAX_CHUNKS_PER_DECISION:
            # Hits are in descending score order, so len() is the chunk's rank
            weight = CHUNK_RANK_DECAY ** len(chunk_ids)
            chunk_ids.append(int(hit["_id"].split("-", 1)[1]))
            scores[decision_id] += hit["_score"] * weight

    decisions = Decision.objects.select_related("council").in_bulk(
        chunk_ids_by_decision
    )
    chunks = Chunk.objects.select_related("document").in_bulk(
        [pk for pks in chunk_ids_by_decision.values() for pk in pks]
    )

    results = []
    for decision_id, chunk_ids in chunk_ids_by_decision.items():
        # The index can be out of date with the database
        if decision_id not in decisions:
            continue
        decision = decisions[decision_id]
        decision.matched_chunks = [
            chunks[pk] for pk in chunk_ids if pk in chunks
        ]
        decision.search_score = scores[decision_id]
        results.append(decision)
    results.sort(key=lambda d: d.search_score, reverse=True)
    return results


def decision_search(request):
    form = DecisionSearchForm(request.GET or None)
    results = []

    if form.is_valid():
        results = decisions_from_hits(search_hits(form.cleaned_data))

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


def decision_makers(request):
    councils = Council.objects.order_by("territory", "name")
    council = None
    makers = []

    if code := request.GET.get("council"):
        council = get_object_or_404(Council, pk=code)
        makers = (
            Decision.objects.filter(council=council)
            .values("raw_decision_maker")
            .annotate(count=Count("pk"))
            .order_by("-count", "raw_decision_maker")
        )

    context = {
        "councils": councils,
        "council": council,
        "makers": makers,
        "total": sum(maker["count"] for maker in makers),
    }
    return render(request, "core/decision_makers.html", context)


TITAN_MODEL = "amazon.titan-embed-text-v2:0"
TITAN_DIMENSIONS = 1024


def embed_text(text):
    client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
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


SIMILAR_DECISIONS_COUNT = 10


def similar_decisions(decision):
    """
    The decisions whose DecisionEmbedding is nearest `decision`'s, closest
    first. Empty if `decision` has no DecisionEmbedding.
    """
    try:
        embedding = decision.embedding
    except DecisionEmbedding.DoesNotExist:
        return []

    neighbours = (
        DecisionEmbedding.objects.filter(model=embedding.model)
        .exclude(pk=embedding.pk)
        .select_related("decision__council")
        .annotate(distance=CosineDistance("embedding", embedding.embedding))
        .order_by("distance")[:SIMILAR_DECISIONS_COUNT]
    )
    return [neighbour.decision for neighbour in neighbours]


class DecisionDetailView(DetailView):
    model = Decision
    template_name = "core/decision_detail.html"
    queryset = Decision.objects.all().prefetch_related("documents")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["similar_decisions"] = similar_decisions(self.object)
        return context


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


def decisions_per_month(decisions):
    """
    A count for every month from the first decision to the last, including
    months with none. `percent` is the count relative to the busiest month,
    for drawing bars.
    """
    counts = dict(
        decisions.exclude(raw_date=None)
        .annotate(month=TruncMonth("raw_date"))
        .values("month")
        .annotate(count=Count("pk"))
        .values_list("month", "count")
    )
    if not counts:
        return []

    busiest = max(counts.values())
    month, last = min(counts), max(counts)
    months = []
    while month <= last:
        count = counts.get(month, 0)
        months.append(
            {"month": month, "count": count, "percent": 100 * count / busiest}
        )
        # The 1st plus 32 days is always in the following month
        month = (month + datetime.timedelta(days=32)).replace(day=1)
    return months


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
        context["months"] = decisions_per_month(
            Decision.objects.filter(council=self.council)
        )
        return context
