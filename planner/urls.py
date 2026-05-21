from django.urls import path

from . import views

app_name = "planner"

urlpatterns = [
    path("", views.home, name="home"),
    path("projects/new/", views.project_new, name="project_new"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="project_delete"),
    path("projects/<int:pk>/doc/<str:doc>/", views.project_document, name="project_document"),
]
