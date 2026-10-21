import json

import boto3
from core.forms import DecisionSearchForm, VectorSearchForm
from core.models import Decision, Embedding
from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import DetailView
from modelsearch.query import Phrase
from pgvector.django import CosineDistance


def hello_world(request):
    return HttpResponse("Hello, world.")


def decision_search(request):
    form = DecisionSearchForm(request.GET or None)
    results = []

    if form.is_valid():
        queryset = Decision.objects.all().prefetch_related("documents")

        if council := form.cleaned_data["council"]:
            queryset = queryset.filter(council=council)

        if status := form.cleaned_data["status"]:
            queryset = queryset.filter(status=status)

        if date_from := form.cleaned_data["publication_date_from"]:
            queryset = queryset.filter(publication_date__gte=date_from)

        if date_to := form.cleaned_data["publication_date_to"]:
            queryset = queryset.filter(publication_date__lte=date_to)

        if form.cleaned_data["is_key_decision"]:
            queryset = queryset.filter(is_key_decision=True)

        if form.cleaned_data["is_officer_decision"]:
            queryset = queryset.filter(is_officer_decision=True)

        if form.cleaned_data["is_subject_to_call_in"]:
            queryset = queryset.filter(is_subject_to_call_in=True)

        if query := form.cleaned_data["q"]:
            if form.cleaned_data["search_mode"] == "phrase":
                query = Phrase(query)
            results = queryset.search(query)
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
    client = boto3.client("bedrock-runtime")
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
        query_embedding = embed_text(form.cleaned_data["q"])
        embeddings = (
            Embedding.objects.filter(model=TITAN_MODEL)
            .select_related("chunk__document__decision__council")
            .annotate(distance=CosineDistance("embedding", query_embedding))
            .order_by("distance")[:VECTOR_SEARCH_LIMIT]
        )
        results = [
            {"chunk": e.chunk, "distance": e.distance} for e in embeddings
        ]

    context = {
        "form": form,
        "results": results,
    }
    return render(request, "core/vector_search.html", context)


class DecisionDetailView(DetailView):
    model = Decision
    template_name = "core/decision_detail.html"
    queryset = Decision.objects.all().prefetch_related("documents")
