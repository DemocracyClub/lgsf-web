from core.models import Council, Decision
from django import forms


def council_choices():
    councils = (
        Council.objects.filter(decision__isnull=False)
        .order_by("territory", "name")
        .values_list("code", "name")
        .distinct()
    )
    return [("", "All councils")] + list(councils)


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
    is_key_decision = forms.BooleanField(
        label="Key decisions only",
        required=False,
    )
    is_officer_decision = forms.BooleanField(
        label="Officer decisions only",
        required=False,
    )
    is_subject_to_call_in = forms.BooleanField(
        label="Subject to call-in only",
        required=False,
    )
    search_mode = forms.ChoiceField(
        label="Search mode",
        required=False,
        choices=[
            ("simple", "Simple search"),
            ("phrase", "Exact phrase"),
        ],
        initial="simple",
        widget=forms.RadioSelect,
    )
