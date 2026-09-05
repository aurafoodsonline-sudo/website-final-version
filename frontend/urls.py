from django.urls import path

from . import views


app_name = "frontend"

urlpatterns = [
    path("", views.operations_console, name="operations-console"),
]
