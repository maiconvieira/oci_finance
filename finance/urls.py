# finance/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('receitas/', views.category_list_view, name='category_list'),
    path('receitas/<int:pk>/excluir/', views.category_delete_view, name='category_delete'),
    path('objetivos/', views.objective_list_view, name='objective_list'),
    path('objetivos/novo/', views.objective_form_view, name='objective_create'),
    path('objetivos/<int:pk>/editar/', views.objective_form_view, name='objective_update'),
    path('objetivos/<int:pk>/duplicar-proximo-periodo/', views.objective_duplicate_next_period_view, name='objective_duplicate_next_period'),
    path('objetivos/<int:pk>/pagar/', views.objective_settle_view, name='objective_settle'),
    path('objetivos/<int:pk>/ocultar/', views.objective_toggle_active_view, name='objective_toggle_active'),
    path('liquidacoes/', views.settlement_list_view, name='settlement_list'),
    path('liquidacoes/ler-comprovante/', views.parse_receipt_view, name='parse_receipt'),
]
