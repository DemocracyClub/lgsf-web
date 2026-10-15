from core import views
from django.urls import path

app_name = "core"

urlpatterns = [
    path("search", views.decision_search, name="decision-search"),
]
