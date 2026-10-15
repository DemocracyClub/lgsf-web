from django.db import models


class Decision(models.Model):
    # Three-letter LGSF council code, e.g. "AGY" (matches data/<CODE>/Decisions/)
    council = models.CharField(max_length=3)
    raw_identifier = models.CharField(max_length=255)
    raw_title = models.CharField(max_length=1024, blank=True)
    raw_date = models.DateField(null=True, blank=True)
    raw_decision_maker = models.CharField(max_length=1024, blank=True)

    publication_date = models.DateField(null=True, blank=True)
    purpose = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, blank=True)
    text = models.TextField(blank=True)
    url = models.URLField(max_length=2048)

    is_key_decision = models.BooleanField(default=False, null=True)
    is_officer_decision = models.BooleanField(default=False, null=True)
    is_subject_to_call_in = models.BooleanField(default=False, null=True)

    # "source" is the page this decision was scraped from, as opposed to `url` above
    source_url = models.URLField(max_length=2048, blank=True)
    source_etag = models.CharField(max_length=255, null=True, blank=True)
    # Stored as-is (HTTP date format), not parsed
    source_last_modified = models.CharField(
        max_length=255, null=True, blank=True
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["council", "raw_identifier"],
                name="unique_council_decision",
            ),
        )

    def __str__(self):
        return f"{self.council}/{self.raw_identifier}: {self.raw_title}"


class Document(models.Model):
    decision = models.ForeignKey(
        Decision, related_name="documents", on_delete=models.CASCADE
    )

    attachment_id = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=1024, blank=True)
    url = models.URLField(max_length=2048)

    content_type = models.CharField(max_length=255, blank=True)
    content_length = models.PositiveIntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=255, blank=True)
    etag = models.CharField(max_length=255, blank=True)
    # Stored as-is (HTTP date format), not parsed
    last_modified = models.CharField(max_length=255, null=True, blank=True)

    storage_backend = models.CharField(max_length=255, blank=True)
    storage_key = models.CharField(max_length=1024, blank=True)

    def __str__(self):
        return self.title or self.storage_key
