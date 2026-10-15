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
    publication_date_from = forms.DateField(
        label="From",
        required=False,
        input_formats=["%d/%m/%Y", "%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%d/%m/%Y"),
    )
    publication_date_to = forms.DateField(
        label="To",
        required=False,
        input_formats=["%d/%m/%Y", "%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%d/%m/%Y"),
    )
