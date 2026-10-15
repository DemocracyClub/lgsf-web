from core.models import Decision
from django import forms


def council_choices():
    councils = (
        Decision.objects.order_by("council")
        .values_list("council", flat=True)
        .distinct()
    )
    return [("", "All councils")] + [(council, council) for council in councils]


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
