import django_filters as filters
from councillors.models import EnrichedCouncillor
from django.core.validators import EMPTY_VALUES
from django.forms import RadioSelect


class EmptyStringFilter(filters.BooleanFilter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        exclude = self.exclude ^ (value is False)
        method = qs.exclude if exclude else qs.filter

        return method(**{self.field_name: ""})


class CompareFilterSet(filters.FilterSet):
    council_id = filters.CharFilter(
        field_name="base_councillor__council_id",
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

    class Meta:
        model = EnrichedCouncillor
        fields = []
