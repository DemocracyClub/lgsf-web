from core import views
from django.urls import path

app_name = "core"

urlpatterns = [
    path("search", views.decision_search, name="decision-search"),
    path("vector-search", views.vector_search, name="vector-search"),
    path(
        "decision/<int:pk>",
        views.DecisionDetailView.as_view(),
        name="decision-detail",
    ),
]
