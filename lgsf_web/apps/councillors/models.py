from django.db import models


class ScrapedCouncillor(models.Model):
    council = models.ForeignKey(
        "core.Council",
        on_delete=models.PROTECT,
        related_name="scraped_councillors",
    )
    photo_url = models.CharField(max_length=255)
    raw_division = models.CharField(max_length=255)
    raw_email = models.CharField(max_length=255)
    raw_identifier = models.CharField(max_length=255)
    raw_name = models.CharField(max_length=255)
    raw_party = models.CharField(max_length=255)
    url = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.council_id}-{self.raw_identifier}-{self.raw_name}"

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["raw_identifier", "raw_name"],
                name="unique_raw_identifier_raw_name",
            )
        ]


class EnrichedCouncillor(models.Model):
    base_councillor = models.OneToOneField(
        ScrapedCouncillor,
        on_delete=models.CASCADE,
        related_name="enriched",
    )

    def __str__(self):
        return f"{self.base_councillor}-Enriched"


class BaseMatch(models.Model):
    match_backend = models.CharField(max_length=255, blank=True)
    match_confidence = models.FloatField(null=True, blank=True)

    def councillor_match_field(related_name: str):
        return models.OneToOneField(
            EnrichedCouncillor,
            on_delete=models.CASCADE,
            related_name=related_name,
        )

    def __str__(self):
        id = getattr(self, self.id_field)
        value = getattr(self, self.value_field)
        return f"{id} - {value}"

    class Meta:
        abstract = True


class EEDivisionMatch(BaseMatch):
    id_field = "division_id"
    value_field = "division_name"
    clr_related_name = "division_match"
    councillor = BaseMatch.councillor_match_field(clr_related_name)

    division_id = models.IntegerField(null=True, blank=True)
    division_name = models.CharField(max_length=255, blank=True)


class YNRPartyMatch(BaseMatch):
    id_field = "party_id"
    value_field = "party_name"
    clr_related_name = "party_match"

    councillor = BaseMatch.councillor_match_field(clr_related_name)

    party_id = models.CharField(max_length=255, blank=True)
    party_name = models.CharField(max_length=255, blank=True)


class YNRNameMatch(BaseMatch):
    id_field = "person_id"
    value_field = "person_name"
    clr_related_name = "name_match"

    councillor = BaseMatch.councillor_match_field(clr_related_name)

    person_id = models.IntegerField(null=True, blank=True)
    person_name = models.CharField(max_length=255, blank=True)
