from django import template

register = template.Library()


@register.filter
def chunk_text(chunk, query=""):
    return chunk.text_for_display(query)
