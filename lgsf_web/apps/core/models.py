import re

from django.conf import settings
from django.db import models
from django.utils.html import escape
from django.utils.safestring import mark_safe
from modelsearch import index
from modelsearch.queryset import SearchableQuerySetMixin
from pgvector.django import HnswIndex, VectorField


class DecisionQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


class DocumentManager(models.Manager):
    # Also applies to related managers (decision.documents) and prefetches,
    # but not select_related: defer "document__text" there.
    # I reckon we will probably want to delete "text"
    # but for now, just defer it by default
    def get_queryset(self):
        return super().get_queryset().defer("text")


class ChunkQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


class Decision(index.Indexed, models.Model):
    # Council.code (e.g. "AGY") matches data/<CODE>/Decisions/
    council = models.ForeignKey("Council", on_delete=models.PROTECT)
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

    objects = DecisionQuerySet.as_manager()

    search_fields = (
        index.SearchField("raw_title", boost=3),
        index.SearchField("text", boost=3),
        # index.SearchField('raw_decision_maker'),
        ###
        # filters
        index.FilterField("council"),
        index.FilterField("status"),
        index.FilterField("is_key_decision"),
        index.FilterField("is_officer_decision"),
        index.FilterField("is_subject_to_call_in"),
        index.FilterField("publication_date"),
        ###
        # related fields
        index.RelatedFields(
            "documents",
            [
                index.SearchField("title", boost=2),
            ],
        ),
    )

    # At least for now, we probably DON'T want to rebuild the index
    # using signals for performance reasons.
    # Insert data, then rebuild with
    # rebuild_modelsearch_index as a post-process
    #
    # Ideally, we would set this globally using the AUTO_UPDATE setting
    # but this is not respected due to a bug
    # https://github.com/wagtail/django-modelsearch/issues/119
    search_auto_update = False

    def __str__(self):
        return f"{self.council_id}/{self.raw_identifier}: {self.raw_title}"


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

    # TODO: probably delete
    text = models.TextField(blank=True)

    objects = DocumentManager()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["decision", "storage_key"],
                name="unique_decision_document_storage_key",
            ),
        )

    @property
    def s3_url(self):
        return f"https://{settings.LGSF_DATA_BUCKET}.s3.eu-west-2.amazonaws.com/data/{self.decision.council_id}/Decisions/documents/{self.storage_key}"

    def __str__(self):
        return self.title or self.storage_key


class Chunk(index.Indexed, models.Model):
    document = models.ForeignKey(
        Document, related_name="chunks", on_delete=models.CASCADE
    )

    chunk_id = models.CharField(max_length=1024, unique=True)
    parent_id = models.CharField(max_length=1024)
    chunk_index = models.PositiveIntegerField()
    chunk_count = models.PositiveIntegerField()

    context = models.TextField()
    text = models.TextField()
    text_hash = models.CharField(max_length=255)
    word_count = models.PositiveIntegerField()

    date = models.DateField()
    embed = models.BooleanField()
    source_type = models.CharField(max_length=255)
    type = models.CharField(max_length=255)
    metadata = models.JSONField()

    objects = ChunkQuerySet.as_manager()

    search_fields = (
        index.SearchField("text"),
        # filters, mirroring Decision so decision filters can apply to chunk searches
        index.RelatedFields(
            "document",
            [
                index.RelatedFields(
                    "decision",
                    [
                        index.FilterField("council"),
                        index.FilterField("status"),
                        index.FilterField("is_key_decision"),
                        index.FilterField("is_officer_decision"),
                        index.FilterField("is_subject_to_call_in"),
                        index.FilterField("publication_date"),
                    ],
                ),
            ],
        ),
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="unique_document_chunk_index",
            ),
        )
        ordering = ("document", "chunk_index")

    def text_for_display(self, query="", max_words=60, lead_words=15):
        """
        HTML snippet of `text` with words from `query` bolded.

        The snippet starts shortly before the first match. If nothing
        matches (e.g. a vector-only hit), it is the start of the text.
        """
        tokens = list(re.finditer(r"\S+", self.text))
        terms = {t for t in re.split(r"\W+", str(query or "")) if len(t) > 2}
        pattern = None
        if terms:
            longest_first = sorted(terms, key=len, reverse=True)
            pattern = re.compile(
                r"\b(?:" + "|".join(map(re.escape, longest_first)) + ")",
                re.IGNORECASE,
            )

        start = 0
        if pattern:
            for i, token in enumerate(tokens):
                if pattern.search(token.group()):
                    start = max(0, i - lead_words)
                    break
        end = min(len(tokens), start + max_words)

        if not tokens:
            return mark_safe("")
        snippet = self.text[tokens[start].start() : tokens[end - 1].end()]

        html = []
        position = 0
        for match in pattern.finditer(snippet) if pattern else ():
            html.append(escape(snippet[position : match.start()]))
            html.append(f"<strong>{escape(match.group())}</strong>")
            position = match.end()
        html.append(escape(snippet[position:]))

        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(tokens) else ""
        return mark_safe(prefix + "".join(html) + suffix)

    def __str__(self):
        return self.chunk_id


class Embedding(models.Model):
    chunk = models.OneToOneField(
        Chunk, related_name="embedding", on_delete=models.CASCADE
    )
    model = models.CharField(max_length=255)
    token_count = models.PositiveIntegerField()
    embedding = VectorField(dimensions=1024)

    class Meta:
        indexes = (
            HnswIndex(
                name="embedding_hnsw_cosine_idx",
                fields=["embedding"],
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=64,
            ),
        )

    def __str__(self):
        return f"{self.model}: {self.chunk_id}"


class DecisionEmbedding(models.Model):
    """
    The mean of a decision's chunk embeddings, less its council's mean.

    Without taking away the council's mean, a decision's nearest
    neighbours are mostly from the same council, alike in their templates
    and phrasing rather than their subject. Made by
    compute_decision_embeddings.
    """

    decision = models.OneToOneField(
        Decision, related_name="embedding", on_delete=models.CASCADE
    )
    model = models.CharField(max_length=255)
    # No HNSW index: at a few thousand rows a sequential scan takes a
    # few milliseconds, and keeping the index up to date made
    # compute_decision_embeddings take ten times as long.
    embedding = VectorField(dimensions=1024)

    def __str__(self):
        return f"{self.model}: {self.decision_id}"


class Council(models.Model):
    # a bad representation of a council that is definitely wrong
    code = models.CharField(max_length=3, blank=False, primary_key=True)
    name = models.CharField(max_length=255, blank=False)
    territory = models.CharField(max_length=3, blank=False)

    def __str__(self):
        return self.name
