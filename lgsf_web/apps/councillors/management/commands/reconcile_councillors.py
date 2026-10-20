from councillors.constants import ALL_COUNCILS
from councillors.matchers import (
    CouncillorDivisionMatcher,
    CouncillorNameMatcher,
    CouncillorPartyMatcher,
)
from councillors.reconciler import CouncillorReconciler
from dc_name_matching import BaseMatcher
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Reconcile scraped councillor data with other DC sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--divisions",
            action="store_true",
            help="attempt to reconcile scraped councillor divisions to EE divisions",
        )
        parser.add_argument(
            "--parties",
            action="store_true",
            help="attempt to reconcile scraped councillor parties to YNR parties",
        )
        parser.add_argument(
            "--names",
            action="store_true",
            help="attempt to reconcile scraped councillor names to YNR names",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--council_id",
            type=str,
            help="The ID of the council to sync",
        )
        group.add_argument(
            "--all-councils",
            action="store_true",
            help="Sync all councils",
        )

    def get_council_ids(self):
        # TODO: get council IDs from source synced to EE
        return ALL_COUNCILS

    def handle(self, *args, **options):
        req_opts = ["divisions", "parties", "names"]
        if not any(options[opt] for opt in req_opts):
            self.stderr.write(
                "At least one of --divisions, --parties, or --names must be specified."
            )
            return
        if options["council_id"]:
            council_id = options["council_id"]
            matchers = self.get_matchers_for_council(council_id, options)
            reconciler = CouncillorReconciler(council_id, matchers)
            reconciler.reconcile()
        else:
            for council_id in self.get_council_ids():
                matchers = self.get_matchers_for_council(council_id, options)
                reconciler = CouncillorReconciler(council_id, matchers)
                reconciler.reconcile()

    def get_matchers_for_council(
        self, council_id, options
    ) -> list[type[BaseMatcher]]:
        matchers = []
        if options["divisions"]:
            div_matcher = CouncillorDivisionMatcher(council_id)
            matchers.append(div_matcher)
        if options["parties"]:
            party_matcher = CouncillorPartyMatcher(council_id)
            matchers.append(party_matcher)
        if options["names"]:
            name_matcher = CouncillorNameMatcher(council_id)
            matchers.append(name_matcher)
        return matchers
