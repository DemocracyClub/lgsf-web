import abc
import csv

from councillors.constants import DATA_DIR
from councillors.mixins import CouncilMixin
from councillors.models import EEDivisionMatch, YNRNameMatch, YNRPartyMatch
from dc_name_matching import (
    BaseMatcher,
    CaseInsensitiveMatch,
    # JevMatch,
    CleanedFirstWordLastWordMatch,
    CleanedMatch,
    DehyphenedCleanedMatch,
    ExactMatch,
    ManyToOneMatcher,
    MatchBackend,
    Target,
)


class BaseCouncillorMatcher(CouncilMixin, metaclass=abc.ABCMeta):
    def __init__(self, council_id):
        self.matcher = None
        self.council_id = council_id

    @property
    def matcher_type(self):
        raise NotImplementedError

    @property
    def matcher_profile(self):
        raise NotImplementedError

    @property
    def scraped_clr_field(self):
        raise NotImplementedError

    @property
    def enriched_clr_field(self):
        raise NotImplementedError

    @abc.abstractmethod
    def get_inputs(self) -> list[str]:
        pass

    @abc.abstractmethod
    def get_targets(self) -> list[Target]:
        pass

    @abc.abstractmethod
    def get_backends(self) -> list[MatchBackend]:
        pass

    def build_matcher(self):
        targets = self.get_targets()
        inputs = self.get_inputs()
        return self.matcher_type(
            inputs,
            targets,
            profile=self.matcher_profile,
        )

    def match(self) -> type[BaseMatcher]:
        matcher = self.build_matcher()
        matcher.run(self.get_backends())
        self.matcher = matcher
        return matcher


class CouncillorDivisionMatcher(BaseCouncillorMatcher):
    matcher_type = ManyToOneMatcher
    match_class = EEDivisionMatch
    matcher_profile = "uk-divisions"
    scraped_clr_field = "raw_division"
    enriched_clr_field = "ee_division_id"

    def get_backends(self) -> list[MatchBackend]:
        return [
            ExactMatch(),
            CaseInsensitiveMatch(),
            CleanedMatch(),
            DehyphenedCleanedMatch(),
            # JevMatch(),
        ]

    def get_target_divisions_from_csv_rows(
        self,
        council_div_rows,
    ) -> list[Target]:
        return [
            Target(row["division_id"], row["division_name"])
            for row in council_div_rows
        ]

    def get_targets(self):
        council_div_rows = self.get_council_divisions(self.council_id.code)
        return self.get_target_divisions_from_csv_rows(council_div_rows)

    def get_inputs(self):
        scraped_clr_divs = []
        for clr in self.get_scraped_councillors(self.council_id):
            scraped_clr_divs.append(clr.raw_division)
        return scraped_clr_divs


class CouncillorPartyMatcher(BaseCouncillorMatcher):
    matcher_type = ManyToOneMatcher
    match_class = YNRPartyMatch
    matcher_profile = "uk-political-parties"
    scraped_clr_field = "raw_party"
    enriched_clr_field = "ynr_party_id"

    def get_backends(self) -> list[MatchBackend]:
        return [
            ExactMatch(),
            CaseInsensitiveMatch(),
            CleanedMatch(),
            # JevMatch(),
        ]

    def get_target_parties_from_csv(self, csv_file) -> list[Target]:
        reader = csv.DictReader(csv_file)
        return [Target(row["ec_id"], row["name"]) for row in reader]

    def get_targets(self):
        with open(DATA_DIR / "ynr_parties.csv") as f:
            return self.get_target_parties_from_csv(f)

    def get_inputs(self):
        scraped_clr_parties = []
        for clr in self.get_scraped_councillors(self.council_id):
            scraped_clr_parties.append(clr.raw_party)
        return scraped_clr_parties


class CouncillorNameMatcher(BaseCouncillorMatcher):
    matcher_type = ManyToOneMatcher
    match_class = YNRNameMatch
    matcher_profile = "councillor-names"
    matcher_results_dir = "raw_name_matches"
    scraped_clr_field = "raw_name"
    enriched_clr_field = "ynr_id"

    def get_backends(self) -> list[MatchBackend]:
        return [
            ExactMatch(),
            CaseInsensitiveMatch(),
            CleanedMatch(),
            CleanedFirstWordLastWordMatch(),
            # JevMatch(),
        ]

    def get_target_names_from_csv(self, csv_file) -> list[Target]:
        reader = csv.DictReader(csv_file)
        council_name = self.council_id.name
        return [
            Target(row["person_id"], row["person_name"])
            for row in reader
            if row["organisation_name"] == council_name
        ]

    def get_targets(self):
        with open(DATA_DIR / "ynr_names_plus.csv") as f:
            return self.get_target_names_from_csv(f)

    def get_inputs(self):
        councillor_names = []
        for clr in self.get_scraped_councillors(self.council_id):
            councillor_names.append(clr.raw_name)
        return councillor_names
