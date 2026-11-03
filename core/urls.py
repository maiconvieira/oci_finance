# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    # Departamentos / Instâncias
    path('departamentos/', views.department_list_view, name='department_list'),
    path('departamentos/salvar/', views.department_save_view, name='department_create'),
    path('departamentos/<int:pk>/salvar/', views.department_save_view, name='department_update'),
    path('departamentos/<int:pk>/ocultar/', views.department_delete_view, name='department_delete'),
    # Pessoas e Acesso de Usuários
    path('pessoas/', views.person_list_view, name='person_list'),
    path('pessoas/nova/', views.person_form_view, name='person_create'),
    path('pessoas/<int:pk>/editar/', views.person_form_view, name='person_update'),
    path('pessoas/<int:pk>/ocultar/', views.person_toggle_active_view, name='person_toggle_active'),
    # Administração do Sistema e Grupos / Subgrupos (100% Frontend)
    path('administracao/', views.system_admin_view, name='system_admin'),
    path('administracao/grupos/<int:pk>/excluir/', views.group_delete_view, name='group_delete'),
    # Autenticação
    path('logout/', views.logout_view, name='logout'),
]
