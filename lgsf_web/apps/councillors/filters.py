import django_filters as filters
from core.models import Council
from councillors.models import (
    EnrichedCouncillor,
    ScrapedCouncillor,
    YNRPartyMatch,
)
from django.core.validators import EMPTY_VALUES
from django.forms import CheckboxInput, CheckboxSelectMultiple


class EmptyStringFilter(filters.BooleanFilter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        exclude = self.exclude ^ (value is False)
        method = qs.exclude if exclude else qs.filter

        return method(**{self.field_name: ""})


def backend_choices(relation):
    field = f"{relation}_backend"

    def choices():
        backends = (
            EnrichedCouncillor.objects.exclude(**{field: ""})
            .order_by(field)
            .values_list(field, flat=True)
            .distinct()
        )
        return [(b, b) for b in backends]

    return choices


def backend_filter(relation, label):
    return filters.MultipleChoiceFilter(
        field_name=f"{relation}_backend",
        label=label,
        choices=backend_choices(relation),
        widget=CheckboxSelectMultiple,
    )


class ScrapedCouncillorFilterSet(filters.FilterSet):
    council_id = filters.ModelChoiceFilter(
        queryset=Council.objects.all(),
        field_name="council",
        label="Council",
    )

    raw_party = filters.CharFilter(
        field_name="raw_party",
        lookup_expr="icontains",
        label="Raw Party Name",
    )
    raw_division = filters.CharFilter(
        field_name="raw_division",
        lookup_expr="icontains",
        label="Raw Division Name",
    )
    raw_person = filters.CharFilter(
        field_name="raw_name",
        lookup_expr="icontains",
        label="Raw Person Name",
    )

    class Meta:
        model = ScrapedCouncillor
        fields = []  # noqa: RUF012


class EnrichedCouncillorFilterSet(filters.FilterSet):
    council_id = filters.ModelChoiceFilter(
        queryset=Council.objects.all(),
        field_name="base_councillor__council",
        label="Council",
    )

    matched_party_name = filters.CharFilter(
        field_name="party_match__party_name",
        lookup_expr="icontains",
        label="Matched Party Name",
    )
    matched_division_name = filters.CharFilter(
        field_name="division_match__division_name",
        lookup_expr="icontains",
        label="Matched Division Name",
    )
    matched_person_name = filters.CharFilter(
        field_name="person_match__person_name",
        lookup_expr="icontains",
        label="Matched Person Name",
    )

    matched_party_id = filters.ModelChoiceFilter(
        queryset=YNRPartyMatch.objects.all(),
        field_name="party_match",
        label="Matched Party ID",
    )

    class Meta:
        model = EnrichedCouncillor
        fields = []  # noqa: RUF012


class CompareFilterSet(EnrichedCouncillorFilterSet):
    raw_party = filters.CharFilter(
        field_name="base_councillor__raw_party",
        lookup_expr="icontains",
        label="Raw Party Name",
    )
    raw_division = filters.CharFilter(
        field_name="base_councillor__raw_division",
        lookup_expr="icontains",
        label="Raw Division Name",
    )
    raw_person = filters.CharFilter(
        field_name="base_councillor__raw_name",
        lookup_expr="icontains",
        label="Raw Person Name",
    )

    missing_name_match = filters.BooleanFilter(
        field_name="name_match",
        label="Missing Name?",
        lookup_expr="isnull",
        widget=CheckboxInput(),
    )
    missing_division_match = filters.BooleanFilter(
        field_name="division_match",
        label="Missing EE Division?",
        lookup_expr="isnull",
        widget=CheckboxInput(),
    )
    missing_party_match = filters.BooleanFilter(
        field_name="party_match",
        label="Missing Party?",
        lookup_expr="isnull",
        widget=CheckboxInput(),
    )

    division_backend = backend_filter(
        "division_match", "EE Division match backend"
    )
    party_backend = backend_filter("party_match", "Party match backend")
    name_backend = backend_filter("name_match", "Name match backend")

    class Meta:
        model = EnrichedCouncillor
        fields = []  # noqa: RUF012
