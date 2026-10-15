from core.forms import DecisionSearchForm
from core.models import Decision
from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import DetailView


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
            results = queryset.search(query)
        else:
            results = queryset

    context = {
        "form": form,
        "results": results,
    }
    return render(request, "core/decision_search.html", context)


class DecisionDetailView(DetailView):
    model = Decision
    template_name = "core/decision_detail.html"
    queryset = Decision.objects.all().prefetch_related("documents")
