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


class CompareListView(ListView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related("base_councillor")
    template_name = "councillors/compare_list.html"


class CompareDetailView(DetailView):
    """Keyed on the scraped councillor pk; 404s if there is no enriched record."""

    queryset = ScrapedCouncillor.objects.filter(
        enriched__isnull=False
    ).select_related("enriched")
    template_name = "councillors/compare_detail.html"
