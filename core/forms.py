# core/forms.py
from django import forms
from django.contrib.auth.models import Group, Permission
from .models import (
    Department,
    Person,
    User,
    GROUP_MILITANTE,
    STANDARD_GROUP_NAMES,
    group_has_full_access,
)


def ensure_standard_groups():
    """Garante que os grupos iniciais existam caso a tabela de grupos esteja vazia."""
    if not Group.objects.exists():
        for name in STANDARD_GROUP_NAMES:
            Group.objects.get_or_create(name=name)


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['code', 'name', 'parent']
        widgets = {
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: CR-SUL, SETOR-01, CEL-SINSEJ',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Comitê Regional Sul',
            }),
            'parent': forms.Select(attrs={
                'class': 'form-select',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            manageable_ids = user.get_manageable_department_ids()
            qs = Department.objects.filter(id__in=manageable_ids, is_active=True).select_related('parent')

            if self.instance and self.instance.pk:
                descendant_ids = self.instance.get_all_descendant_ids(include_inactive=True)
                qs = qs.exclude(id__in=descendant_ids)

            self.fields['parent'].queryset = qs

            if not user.has_full_system_access():
                self.fields['parent'].required = True
                self.fields['parent'].empty_label = "Selecione a instância superior..."
            else:
                self.fields['parent'].required = False
                self.fields['parent'].empty_label = "— Nenhuma (Instância Raiz / Topo) —"


class PersonForm(forms.ModelForm):
    """
    Formulário de Pessoa + Controle de Escalonamento de Privilégios:
    - Usuários que não são administradores não visualizam grupos administradores
      e só podem atribuir grupos cujas permissões não ultrapassem o seu próprio perfil.
    """
    groups = forms.ModelMultipleChoiceField(
        label="Grupos / Perfis (selecione ao menos 1)",
        queryset=Group.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input person-group-checkbox'}),
        error_messages={
            'required': 'Toda pessoa deve estar vinculada a pelo menos 1 grupo.'
        }
    )

    has_login = forms.BooleanField(
        label="Habilitar acesso de Usuário (Login no Sistema)",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
    )
    username = forms.CharField(
        label="Nome de Usuário (Login)",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: joao.silva'})
    )
    password = forms.CharField(
        label="Senha de Acesso",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Digite a senha...'})
    )

    class Meta:
        model = Person
        fields = ['name', 'nickname', 'phone', 'email', 'responsible_militant', 'groups', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome completo da pessoa'}),
            'nickname': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apelido ou nome social'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(00) 00000-0000'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'responsible_militant': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.requesting_user = requesting_user
        ensure_standard_groups()

        if requesting_user is not None:
            # Filtra estritamente os grupos que o operador tem permissão para ver e conceder
            self.fields['groups'].queryset = requesting_user.get_assignable_groups_queryset()

            accessible_ids = requesting_user.get_accessible_department_ids()
            militant_qs = (
                Person.objects.visible_to(requesting_user)
                .filter(groups__name=GROUP_MILITANTE, is_active=True, departments__id__in=accessible_ids)
                .distinct()
                .order_by('name')
            )
            if self.instance and self.instance.pk:
                militant_qs = militant_qs.exclude(pk=self.instance.pk)
            self.fields['responsible_militant'].queryset = militant_qs
            self.fields['responsible_militant'].empty_label = "Selecione o militante responsável..."
        else:
            self.fields['groups'].queryset = Group.objects.all().order_by('name')

        if self.instance and self.instance.pk and self.instance.user:
            self.fields['has_login'].initial = self.instance.user.is_active
            self.fields['username'].initial = self.instance.user.username

    def clean(self):
        cleaned_data = super().clean()
        selected_groups = cleaned_data.get('groups')
        responsible_militant = cleaned_data.get('responsible_militant')
        has_login = cleaned_data.get('has_login')
        username = (cleaned_data.get('username') or '').strip()
        password = cleaned_data.get('password') or ''

        # Validação extra contra escalonamento de privilégios no backend
        if self.requesting_user and not self.requesting_user.has_full_system_access() and selected_groups:
            allowed_ids = set(self.requesting_user.get_assignable_groups_queryset().values_list('id', flat=True))
            for g in selected_groups:
                if g.id not in allowed_ids or group_has_full_access(g):
                    self.add_error(
                        'groups',
                        f"Você não tem permissão para atribuir o perfil '{g.name}', pois ele possui nível superior ao seu próprio usuário."
                    )

        selected_group_names = {g.name for g in selected_groups} if selected_groups else set()
        is_militant = GROUP_MILITANTE in selected_group_names
        is_full_access = any(group_has_full_access(g) for g in selected_groups) if selected_groups else False

        # Se NÃO for Militante e NÃO for Usuário Administrador, exige Militante Responsável
        if selected_groups and not is_militant and not is_full_access and not responsible_militant:
            self.add_error(
                'responsible_militant',
                'Para Contribuintes e Contatos, é obrigatório informar o Militante Responsável.'
            )

        if has_login:
            if not username:
                self.add_error('username', 'Informe o nome de usuário para habilitar o login no sistema.')
            else:
                existing_user_qs = User.objects.filter(username__iexact=username)
                if self.instance and self.instance.pk and self.instance.user_id:
                    existing_user_qs = existing_user_qs.exclude(pk=self.instance.user_id)
                if existing_user_qs.exists():
                    self.add_error('username', 'Este nome de usuário já está em uso por outra pessoa.')

            has_existing_user = bool(self.instance and self.instance.pk and self.instance.user_id)
            if not has_existing_user and not password:
                self.add_error('password', 'Defina uma senha inicial para criar o acesso de usuário.')

        return cleaned_data


class GroupRoleForm(forms.ModelForm):
    """
    Formulário para gerenciar os Grupos / Perfis e suas permissões no template do frontend.
    """
    permissions = forms.ModelMultipleChoiceField(
        label="Permissões concedidas ao Grupo",
        queryset=Permission.objects.filter(
            content_type__app_label__in=['core', 'finance', 'auth']
        ).select_related('content_type').order_by('content_type__app_label', 'codename'),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )

    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nome do grupo de perfil',
            }),
        }
