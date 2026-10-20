import csv

from councillors.constants import DATA_DIR
from councillors.mixins import CouncilMixin
from councillors.models import EnrichedCouncillor
from django.db import transaction


class CouncillorReconciler(CouncilMixin):
    """
    Reconciles councillors for a given council with a list of matcher objects
    """

    def __init__(self, council_id, matchers):
        self.council_id = council_id
        self.matchers = matchers

    def reconcile(self):
        councillors = self.get_scraped_councillors(self.council_id)
        clr_to_match_objs = {clr: [] for clr in councillors}

        for matcher in self.matchers:
            self._get_clr_matches(clr_to_match_objs, matcher)

        with transaction.atomic():
            for clr, matches in clr_to_match_objs.items():
                enriched, _ = EnrichedCouncillor.objects.update_or_create(
                    base_councillor=clr,
                )

                for match in matches:
                    self._enrich_matches_with_csv_data(match)
                    match_class = type(match)
                    defaults = {
                        match.id_field: getattr(match, match.id_field),
                        match.value_field: getattr(match, match.value_field),
                        "match_backend": match.match_backend,
                        "match_confidence": match.match_confidence,
                    }
                    match_class.objects.update_or_create(
                        councillor=enriched,
                        defaults=defaults,
                    )

    def _enrich_matches_with_csv_data(self, match):
        if type(match).__name__ == "EEDivisionMatch":
            csv_name = "ee_divisions.csv"
            row_id_col = "division_id"
            row_value_col = "division_name"
        elif type(match).__name__ == "YNRPartyMatch":
            csv_name = "ynr_parties.csv"
            row_id_col = "ec_id"
            row_value_col = "name"
        elif type(match).__name__ == "YNRNameMatch":
            csv_name = "ynr_names_plus.csv"
            row_id_col = "person_id"
            row_value_col = "person_name"
        else:
            return

        with open(DATA_DIR / csv_name) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row[row_id_col] == getattr(match, match.id_field):
                    setattr(match, match.value_field, row[row_value_col])
                    break

    def _get_clr_matches(self, clr_to_match_objs, matcher):
        results = matcher.match()
        for clr, matches in clr_to_match_objs.items():
            input_field_value = getattr(clr, matcher.scraped_clr_field)
            match = results.match_for(input_field_value)
            if match:
                match_class = matcher.match_class
                obj_kwargs = {
                    match_class.id_field: match.target.id,
                    "match_backend": match.backend,
                    "match_confidence": match.confidence,
                }
                match_obj = match_class(**obj_kwargs)
                matches.append(match_obj)
            else:
                print(
                    f"failed to reconcile {matcher.scraped_clr_field} for councillor: {clr}"
                )
