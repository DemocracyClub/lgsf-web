from core.forms import DecisionSearchForm
from core.models import Decision
from django.http import HttpResponse
from django.shortcuts import render


def hello_world(request):
    return HttpResponse("Hello, world.")


def decision_search(request):
    form = DecisionSearchForm(request.GET or None)
    results = []

    if form.is_valid() and (query := form.cleaned_data["q"]):
        results = Decision.objects.all().search(query)

    context = {
        "form": form,
        "results": results,
    }
    return render(request, "core/decision_search.html", context)
