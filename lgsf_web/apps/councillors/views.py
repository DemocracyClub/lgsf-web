from typing import Any

from councillors.filters import CompareFilterSet
from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.db.models import Value
from django.db.models.functions import NullIf
from django.views.generic import DetailView
from django_filters.views import FilterView


class ScrapedCouncillorListView(FilterView):
    model = ScrapedCouncillor
    queryset = ScrapedCouncillor.objects.select_related("enriched")
    filterset_fields = ["council_id"]
    paginate_by = 100
    template_name = "councillors/scrapedcouncillor_list.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        if "page" in params:
            del params["page"]
        context["filter_params"] = params.urlencode()
        return context


class ScrapedCouncillorDetailView(DetailView):
    model = ScrapedCouncillor


class EnrichedCouncillorListView(FilterView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related("base_councillor")
    filterset_fields = ["base_councillor__council_id"]
    paginate_by = 100
    template_name = "councillors/enrichedcouncillor_list.html"


class EnrichedCouncillorDetailView(DetailView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related("base_councillor")


class CompareListView(FilterView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related(
        "base_councillor"
    ).order_by(
        "base_councillor__council_id",
        NullIf("ynr_name", Value("")).asc(nulls_last=True),
        "base_councillor__raw_name",
    )
    filterset_class = CompareFilterSet
    paginate_by = 100
    template_name = "councillors/compare_list.html"


class CompareDetailView(DetailView):
    """Keyed on the scraped councillor pk; 404s if there is no enriched record."""

    queryset = ScrapedCouncillor.objects.filter(
        enriched__isnull=False
    ).select_related("enriched")
    template_name = "councillors/compare_detail.html"
