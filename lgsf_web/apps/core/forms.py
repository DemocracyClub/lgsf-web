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


class DecisionFilterForm(forms.Form):
    field_order = ("q",)

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

    def filter_decisions(self, queryset):
        data = self.cleaned_data

        if council := data["council"]:
            queryset = queryset.filter(council=council)

        if status := data["status"]:
            queryset = queryset.filter(status=status)

        if date_from := data["publication_date_from"]:
            queryset = queryset.filter(publication_date__gte=date_from)

        if date_to := data["publication_date_to"]:
            queryset = queryset.filter(publication_date__lte=date_to)

        if data["is_key_decision"]:
            queryset = queryset.filter(is_key_decision=True)

        if data["is_officer_decision"]:
            queryset = queryset.filter(is_officer_decision=True)

        if data["is_subject_to_call_in"]:
            queryset = queryset.filter(is_subject_to_call_in=True)

        return queryset


class VectorSearchForm(DecisionFilterForm):
    q = forms.CharField(
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Search chunks…"}),
    )


class DecisionSearchForm(DecisionFilterForm):
    q = forms.CharField(
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Search decisions…"}),
    )
    search_mode = forms.ChoiceField(
        label="Search mode",
        choices=[
            ("simple", "Simple search"),
            ("phrase", "Exact phrase"),
        ],
        initial="simple",
        widget=forms.RadioSelect,
    )
