from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.views.generic import DetailView, ListView


class ScrapedCouncillorListView(ListView):
    model = ScrapedCouncillor
    queryset = ScrapedCouncillor.objects.select_related("enriched")


class ScrapedCouncillorDetailView(DetailView):
    model = ScrapedCouncillor


class EnrichedCouncillorListView(ListView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related("base_councillor")


class EnrichedCouncillorDetailView(DetailView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related("base_councillor")
