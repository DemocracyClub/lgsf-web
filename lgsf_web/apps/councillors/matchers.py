import abc
import csv

from councillors.constants import DATA_DIR
from councillors.mixins import CouncilMixin
from councillors.models import EEDivisionMatch, YNRNameMatch, YNRPartyMatch
from dc_name_matching import (
    BaseMatcher,
    CaseInsensitiveMatch,
    CleanedMatch,
    ExactMatch,
    # JevMatch,
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

    # def generate_match_report(self) -> Group:
    #     matcher = self.matcher
    #     summary_table = self.create_summary_table()
    #     tables = []
    #     backends = Counter(m.backend for m in matcher.matches.values())
    #     summary_table.add_row(
    #         self.council_id,
    #         str(len(matcher.matches)),
    #         str(len(matcher.unmatched_inputs)),
    #         str(len(matcher.unmatched_targets)),
    #         str(self._count(matcher.suggestions)),
    #         ", ".join(f"{b}: {n}" for b, n in sorted(backends.items())),
    #     )
    #     tables.append(summary_table)

    #     matches_table = self.create_matches_table()
    #     unique_inputs = sorted(set(self.inputs))
    #     for input in unique_inputs:
    #         match = self.matcher.match_for(input)
    #         if match:
    #             matches_table.add_row(
    #                 self.council_id,
    #                 input,
    #                 match.target.label,
    #                 match.target.id,
    #                 match.backend,
    #                 ""
    #                 if match.confidence is None
    #                 else f"{match.confidence:.2f}",
    #             )
    #     tables.append(matches_table)

    #     if matcher.unmatched_inputs:
    #         suggestions_table = self.create_suggestions_table()
    #         for text in sorted(matcher.unmatched_inputs):
    #             found = matcher.suggestions.get(text) or []
    #             suggestions_table.add_row(
    #                 self.council_id,
    #                 str(text),
    #                 "\n".join(s.target.label for s in found),
    #                 "\n".join(s.target.id for s in found),
    #                 "\n".join(str(s.source) for s in found),
    #                 "\n".join(
    #                     "" if s.score is None else f"{s.score:.2f}"
    #                     for s in found
    #                 ),
    #             )
    #         tables.append(suggestions_table)

    #     return Group(*tables)

    # def create_suggestions_table(self):
    #     suggestions_table = Table(title="Unmatched inputs and suggestions")
    #     suggestions_table.add_column("Council", style="magenta")
    #     suggestions_table.add_column("Input", style="cyan")
    #     suggestions_table.add_column("Suggested Match label", style="green")
    #     suggestions_table.add_column("Suggested Match ID", style="green")
    #     suggestions_table.add_column("Source", style="yellow")
    #     suggestions_table.add_column(
    #         "Confidence", style="yellow", justify="right"
    #     )
    #     return suggestions_table

    # def create_matches_table(self):
    #     matches_table = Table(title="Matches")
    #     matches_table.add_column("Council", style="magenta")
    #     matches_table.add_column("Input", style="cyan")
    #     matches_table.add_column("Matched label", style="green")
    #     matches_table.add_column("Matched ID", style="green")
    #     matches_table.add_column("Backend", style="yellow")
    #     matches_table.add_column("Confidence", style="yellow", justify="right")
    #     return matches_table

    # def create_summary_table(self):
    #     table = Table(
    #         title=f"{self.council_id}: {self.__class__.__name__} Summary"
    #     )
    #     table.add_column("Council", style="magenta")
    #     table.add_column("Matches", style="green", justify="right")
    #     table.add_column("Unmatched inputs", style="red", justify="right")
    #     table.add_column("Unmatched targets", style="red", justify="right")
    #     table.add_column("Suggestions", style="yellow", justify="right")
    #     table.add_column("Matches by backend", style="cyan")
    #     return table

    # @staticmethod
    # def _count(value):
    #     """Size of a result that may be a flat collection or input -> list."""
    #     if isinstance(value, dict):
    #         return sum(
    #             len(v) if isinstance(v, (list, tuple, set)) else 1
    #             for v in value.values()
    #         )
    #     return len(value)

    # @staticmethod
    # def _default(o):
    #     if is_dataclass(o) and not isinstance(o, type):
    #         return asdict(o)
    #     raise TypeError(f"{type(o)} is not JSON serializable")


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
