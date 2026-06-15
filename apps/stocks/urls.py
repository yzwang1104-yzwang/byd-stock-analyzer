from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("stock/<str:code>/", views.stock_detail, name="stock_detail"),
    path("stock/<str:code>/predict/", views.stock_predict, name="stock_predict"),
    path("scan/", views.scan, name="scan"),
    path("positions/", views.positions, name="positions"),
]
