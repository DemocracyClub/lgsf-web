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

    if form.is_valid() and (query := form.cleaned_data["q"]):
        queryset = Decision.objects.all().prefetch_related("documents")

        if council := form.cleaned_data["council"]:
            queryset = queryset.filter(council=council)

        if status := form.cleaned_data["status"]:
            queryset = queryset.filter(status=status)

        results = queryset.search(query)

    context = {
        "form": form,
        "results": results,
    }
    return render(request, "core/decision_search.html", context)


class DecisionDetailView(DetailView):
    model = Decision
    template_name = "core/decision_detail.html"
    queryset = Decision.objects.all().prefetch_related("documents")
