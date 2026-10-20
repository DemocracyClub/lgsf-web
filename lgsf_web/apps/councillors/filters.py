import django_filters as filters
from councillors.models import (
    EEDivisionMatch,
    EnrichedCouncillor,
    YNRNameMatch,
    YNRPartyMatch,
)
from django.core.validators import EMPTY_VALUES
from django.forms import CheckboxSelectMultiple, RadioSelect


class EmptyStringFilter(filters.BooleanFilter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        exclude = self.exclude ^ (value is False)
        method = qs.exclude if exclude else qs.filter

        return method(**{self.field_name: ""})


def backend_choices(model):
    def choices():
        backends = (
            model.objects.exclude(match_backend="")
            .order_by("match_backend")
            .values_list("match_backend", flat=True)
            .distinct()
        )
        return [(b, b) for b in backends]

    return choices


def backend_filter(model, relation, label):
    return filters.MultipleChoiceFilter(
        field_name=f"{relation}__match_backend",
        label=label,
        choices=backend_choices(model),
        widget=CheckboxSelectMultiple,
    )


class CompareFilterSet(filters.FilterSet):
    council_id = filters.CharFilter(
        field_name="base_councillor__council__code",
        label="Council ID",
        lookup_expr="iexact",
    )
    name_match = filters.BooleanFilter(
        field_name="name_match",
        label="Missing Name?",
        lookup_expr="isnull",
        widget=RadioSelect(
            choices=(
                ("true", "Yes"),
                ("false", "No"),
                ("unknown", "Unknown"),
            ),
        ),
    )
    division_match = filters.BooleanFilter(
        field_name="division_match",
        label="Missing EE Division?",
        lookup_expr="isnull",
        widget=RadioSelect(
            choices=(
                ("true", "Yes"),
                ("false", "No"),
                ("unknown", "Unknown"),
            ),
        ),
    )
    party_match = filters.BooleanFilter(
        field_name="party_match",
        label="Missing Party?",
        lookup_expr="isnull",
        widget=RadioSelect(
            choices=(
                ("true", "Yes"),
                ("false", "No"),
                ("unknown", "Unknown"),
            ),
        ),
    )
    division_backend = backend_filter(
        EEDivisionMatch, "division_match", "EE Division match backend"
    )
    party_backend = backend_filter(
        YNRPartyMatch, "party_match", "Party match backend"
    )
    name_backend = backend_filter(
        YNRNameMatch, "name_match", "Name match backend"
    )

    class Meta:
        model = EnrichedCouncillor
        fields = []  # noqa: RUF012
