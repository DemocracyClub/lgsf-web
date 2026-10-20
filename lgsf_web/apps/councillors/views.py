from typing import Any

from core.models import Council
from councillors.filters import CompareFilterSet
from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.db.models import Count, F, FloatField, Q, Value
from django.db.models.functions import Cast, NullIf
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView, TemplateView
from django_filters.views import FilterView


class ScrapedCouncillorListView(FilterView):
    model = ScrapedCouncillor
    queryset = ScrapedCouncillor.objects.select_related("enriched")
    filterset_fields = ["council"]  # noqa: RUF012
    paginate_by = 100
    template_name = "councillors/scrapedcouncillor_list.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.get_filter_params()
        context["filter_params"] = params
        return context

    def get_filter_params(self):
        params = self.request.GET.copy()
        if "page" in params:
            del params["page"]
        return params.urlencode()


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
    filterset_fields = ["base_councillor__council"]  # noqa: RUF012
    paginate_by = 100
    template_name = "councillors/enrichedcouncillor_list.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.get_filter_params()
        context["filter_params"] = params
        return context

    def get_filter_params(self):
        params = self.request.GET.copy()
        if "page" in params:
            del params["page"]
        return params.urlencode()


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

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.get_filter_params()
        context["filter_params"] = params
        return context

    def get_filter_params(self):
        params = self.request.GET.copy()
        if "page" in params:
            del params["page"]
        return params.urlencode()


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
        qs = Council.objects.filter(scraped_councillors__isnull=False).annotate(
            total=Count("scraped_councillors")
        )
        for key in MATCH_LABELS:
            qs = qs.annotate(
                **{
                    key: 100
                    * Count(f"scraped_councillors__enriched__{key}")
                    / Cast(F("total"), FloatField())
                }
            )

        sort = self.request.GET.get("sort", "code")
        field = sort.removeprefix("-")
        if field not in self.sortable_fields:
            sort, field = "code", "code"
        self.sort = sort
        return qs.order_by(sort, "code")

    @property
    def sortable_fields(self):
        return {"code", "name", "total", *MATCH_LABELS}

    def sort_param(self, field):
        # Clicking the active column toggles direction; others start ascending
        # (percentages start descending, since highest first is more useful).
        if self.sort.removeprefix("-") == field:
            return field if self.sort.startswith("-") else f"-{field}"
        return (
            f"-{field}" if field in MATCH_LABELS or field == "total" else field
        )

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        total, no_enriched, stats = summary_stats(
            ScrapedCouncillor.objects.all()
        )
        context.update(
            total=total,
            no_enriched=no_enriched,
            stats=stats,
            sort=self.sort,
            sort_params={
                field: self.sort_param(field) for field in self.sortable_fields
            },
        )
        return context


class CouncilSummaryDetailView(TemplateView):
    template_name = "councillors/council_summary_detail.html"

    def get_context_data(self, council_id, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        council = get_object_or_404(Council, code=council_id)
        total, no_enriched, stats = summary_stats(
            ScrapedCouncillor.objects.filter(council=council)
        )
        context.update(
            council=council,
            council_id=council.code,
            total=total,
            no_enriched=no_enriched,
            stats=stats,
        )
        return context


class LandingView(TemplateView):
    template_name = "councillors/landing.html"
