from typing import Any

from councillors.filters import CompareFilterSet
from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.db.models import Count, F, Q, Value
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
    queryset = EnrichedCouncillor.objects.select_related(
        "base_councillor",
        "division_match",
        "party_match",
        "name_match",
    )
    filterset_fields = ["base_councillor__council_id"]
    paginate_by = 100
    template_name = "councillors/enrichedcouncillor_list.html"


class EnrichedCouncillorDetailView(DetailView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related("base_councillor")


class CompareListView(FilterView):
    model = EnrichedCouncillor
    queryset = EnrichedCouncillor.objects.select_related(
        "base_councillor",
        "division_match",
        "party_match",
        "name_match",
    ).order_by(
        "base_councillor__council_id",
        NullIf("name_match__person_name", Value("")).asc(nulls_last=True),
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


# A councillor is missing a match if it has no match object for it, which
# includes having no enriched record at all.
# Match relation on EnrichedCouncillor -> label; also the compare filter param.
MATCH_LABELS = {
    "division_match": "EE division",
    "party_match": "YNR party",
    "name_match": "YNR name",
}


def summary_stats(qs):
    aggregates = {
        "total": Count("id"),
        "no_enriched": Count("id", filter=Q(enriched__isnull=True)),
    }
    for key in MATCH_LABELS:
        aggregates[key] = Count(f"enriched__{key}")
    counts = qs.aggregate(**aggregates)
    total = counts["total"]
    stats = [
        {
            "label": label,
            "backends": list(
                qs.filter(**{f"enriched__{key}__isnull": False})
                .order_by(f"enriched__{key}__match_backend")
                .values(backend=F(f"enriched__{key}__match_backend"))
                .annotate(count=Count("id"))
            ),
            "filter_param": key,
            "backend_param": key.replace("_match", "_backend"),
            "complete": counts[key],
            "percent": round(100 * counts[key] / total, 1) if total else 0,
        }
        for key, label in MATCH_LABELS.items()
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
        total, no_enriched, stats = summary_stats(
            ScrapedCouncillor.objects.all()
        )
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
            council_id=council_id,
            total=total,
            no_enriched=no_enriched,
            stats=stats,
        )
        return context


class LandingView(TemplateView):
    template_name = "councillors/landing.html"
