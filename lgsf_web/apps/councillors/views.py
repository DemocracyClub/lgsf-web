from typing import Any

from councillors.filters import CompareFilterSet
from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.db.models import Count, Q, Value
from django.db.models.functions import NullIf
from django.http import Http404
from django.views.generic import DetailView, ListView, TemplateView
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


# A group of fields counts as missing if the councillor has no enriched
# record, or any field in the group is empty.
MISSING_GROUPS = {
    "division": (
        "EE division ID / name",
        Q(enriched__ee_division_id__isnull=True) | Q(enriched__ee_division_name=""),
    ),
    "party": (
        "YNR party ID / name",
        Q(enriched__ynr_party_id="") | Q(enriched__ynr_party_name=""),
    ),
    "ynr": ("YNR name / ID", Q(enriched__ynr_id__isnull=True) | Q(enriched__ynr_name="")),
}


FILTER_PARAMS = {"ynr": "ynr_name", "division": "ee_division_id", "party": "ynr_party_id"}


def _missing_q(key):
    return Q(enriched__isnull=True) | MISSING_GROUPS[key][1]


def summary_stats(qs):
    aggregates = {
        "total": Count("id"),
        "no_enriched": Count("id", filter=Q(enriched__isnull=True)),
    }
    for key in MISSING_GROUPS:
        aggregates[key] = Count("id", filter=_missing_q(key))
    counts = qs.aggregate(**aggregates)
    total = counts["total"]
    stats = [
        {
            "label": label,
            "filter_param": FILTER_PARAMS[key],
            "complete": total - counts[key],
            "percent": round(100 * (total - counts[key]) / total, 1) if total else 0,
        }
        for key, (label, _) in MISSING_GROUPS.items()
    ]
    return total, counts["no_enriched"], stats


class CouncilSummaryListView(ListView):
    template_name = "councillors/council_summary_list.html"
    context_object_name = "councils"

    def get_queryset(self):
        return (
            ScrapedCouncillor.objects.order_by("council_id")
            .values("council_id")
            .annotate(total=Count("id"))
        )

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        total, no_enriched, stats = summary_stats(ScrapedCouncillor.objects.all())
        context.update(total=total, no_enriched=no_enriched, stats=stats)
        return context


class CouncilSummaryDetailView(TemplateView):
    template_name = "councillors/council_summary_detail.html"

    def get_context_data(self, council_id, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        total, no_enriched, stats = summary_stats(
            ScrapedCouncillor.objects.filter(council_id=council_id)
        )
        if not total:
            raise Http404("No councillors for this council")
        context.update(
            council_id=council_id, total=total, no_enriched=no_enriched, stats=stats
        )
        return context
