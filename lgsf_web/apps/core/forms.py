from core.models import Decision
from django import forms


def council_choices():
    councils = (
        Decision.objects.order_by("council")
        .values_list("council", flat=True)
        .distinct()
    )
    return [("", "All councils")] + [(council, council) for council in councils]


def status_choices():
    statuses = (
        Decision.objects.exclude(status="")
        .order_by("status")
        .values_list("status", flat=True)
        .distinct()
    )
    return [("", "All statuses")] + [(status, status) for status in statuses]


class DecisionSearchForm(forms.Form):
    q = forms.CharField(
        label="Search",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search decisions…"}),
    )
    council = forms.ChoiceField(
        label="Council",
        required=False,
        choices=council_choices,
    )
    status = forms.ChoiceField(
        label="Status",
        required=False,
        choices=status_choices,
    )
