# core/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser, Group
from django.core.exceptions import ValidationError


# Nomes padronizados dos 6 Grupos / Perfis do sistema
GROUP_ADMIN = "00 - Administração"
GROUP_SECRETARIO = "01 - Secretário"
GROUP_FINANCEIRO = "02 - Financeiro"
GROUP_MILITANTE = "03 - Militante"
GROUP_CONTRIBUINTE = "04 - Contribuinte"
GROUP_CONTATO = "05 - Contato"

STANDARD_GROUP_NAMES = [
    GROUP_ADMIN,
    GROUP_SECRETARIO,
    GROUP_FINANCEIRO,
    GROUP_MILITANTE,
    GROUP_CONTRIBUINTE,
    GROUP_CONTATO,
]

# Permissões principais monitoradas na hierarquia de perfis
CORE_SYSTEM_PERMISSION_CODENAMES = {
    'view_department', 'add_department', 'change_department', 'delete_department',
    'view_person', 'add_person', 'change_person', 'delete_person',
    'view_financialobjective', 'add_financialobjective', 'change_financialobjective', 'delete_financialobjective',
    'view_objectivesettlement', 'add_objectivesettlement', 'change_objectivesettlement', 'delete_objectivesettlement',
}


def group_has_full_access(group):
    """
    Verifica se um Group confere perfil de Usuário Administrador
    (possui todas as permissões principais do sistema ou é o grupo administrativo raiz).
    """
    if group.name == GROUP_ADMIN:
        return True
    group_codenames = set(group.permissions.values_list('codename', flat=True))
    return CORE_SYSTEM_PERMISSION_CODENAMES.issubset(group_codenames)


def get_full_access_group_ids():
    """Retorna os IDs de todos os grupos de Usuário Administrador."""
    full_ids = []
    for g in Group.objects.prefetch_related('permissions').all():
        if group_has_full_access(g):
            full_ids.append(g.id)
    return full_ids


class Department(models.Model):
    """Instâncias: Administração (d1), CC (d2), CR (d3), Setor (d4), Célula (d5)."""
    name = models.CharField("Nome da Instância", max_length=150)
    code = models.CharField("Código / Sigla", max_length=30, unique=True)
    parent = models.ForeignKey(
        'self',
        verbose_name="Instância Superior",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children'
    )
    is_active = models.BooleanField("Ativo", default=True)

    def get_level(self):
        """Retorna a profundidade da instância na árvore (1 = raiz, 2 = filho da raiz, etc.)."""
        level = 1
        curr = self.parent
        visited = {self.pk} if self.pk else set()
        while curr is not None:
            if curr.pk in visited:
                break
            if curr.pk:
                visited.add(curr.pk)
            level += 1
            curr = curr.parent
        return level

    def clean(self):
        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError("Uma instância não pode ser subordinada a si mesma.")
        curr = self.parent
        while curr is not None:
            if self.pk and curr.pk == self.pk:
                raise ValidationError("Relação cíclica detectada na árvore de instâncias.")
            curr = curr.parent

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def get_all_descendant_ids(self, include_inactive=False):
        """Retorna o ID desta instância e de todas as instâncias subordinadas abaixo dela."""
        descendant_ids = [self.id]
        qs_filter = {} if include_inactive else {'is_active': True}
        to_process = list(self.children.filter(**qs_filter).values_list('id', flat=True))
        while to_process:
            curr_id = to_process.pop()
            if curr_id not in descendant_ids:
                descendant_ids.append(curr_id)
                to_process.extend(
                    Department.objects.filter(parent_id=curr_id, **qs_filter).values_list('id', flat=True)
                )
        return descendant_ids

    def __str__(self):
        return f"{self.code} - {self.name}"


class User(AbstractUser):
    """Usuários com credencial de acesso para logar no sistema."""
    def has_full_system_access(self):
        """
        Retorna True se o usuário for um Usuário Administrador
        (superuser ou membro de grupo administrador com todas as permissões).
        """
        if self.is_superuser:
            return True
        for g in self.groups.prefetch_related('permissions').all():
            if group_has_full_access(g):
                return True
        if hasattr(self, 'person_profile') and self.person_profile.is_active:
            for g in self.person_profile.groups.prefetch_related('permissions').all():
                if group_has_full_access(g):
                    return True
        return False

    def get_effective_permission_codenames(self):
        """Retorna o conjunto de codenames de permissões que o próprio usuário possui."""
        if self.has_full_system_access():
            return set(CORE_SYSTEM_PERMISSION_CODENAMES)
        codenames = set(self.groups.values_list('permissions__codename', flat=True))
        codenames.update(self.user_permissions.values_list('codename', flat=True))
        if hasattr(self, 'person_profile') and self.person_profile.is_active:
            codenames.update(self.person_profile.groups.values_list('permissions__codename', flat=True))
        codenames.discard(None)
        return codenames

    def get_assignable_groups_queryset(self):
        """
        Retorna os grupos que este usuário pode visualizar e atribuir a outras pessoas:
        - Usuário Administrador: pode ver e atribuir todos os grupos.
        - Usuário NÃO Administrador:
          1. Nunca vê grupos administradores.
          2. Nunca pode atribuir um grupo que possua qualquer permissão que ele próprio não tenha
             (impede conceder acesso a um perfil maior que o do próprio usuário).
        """
        all_groups = Group.objects.prefetch_related('permissions').all().order_by('name')
        if self.has_full_system_access():
            return all_groups

        user_perms = self.get_effective_permission_codenames()
        allowed_group_ids = []
        for g in all_groups:
            if group_has_full_access(g):
                continue
            group_perms = {p.codename for p in g.permissions.all()}
            # Só permite se todas as permissões do grupo estiverem contidas nas permissões do usuário
            if group_perms.issubset(user_perms):
                allowed_group_ids.append(g.id)

        return Group.objects.filter(id__in=allowed_group_ids).order_by('name')

    def get_accessible_department_ids(self):
        """
        Retorna todos os IDs de departamentos que o usuário pode VISUALIZAR (ou gerir).
        Usuários Administradores acessam tudo sem precisar estar vinculados a uma instância.
        """
        if self.has_full_system_access():
            return list(Department.objects.filter(is_active=True).values_list('id', flat=True))
        if hasattr(self, 'person_profile') and self.person_profile.is_active:
            accessible_ids = set()
            for link in self.person_profile.department_links.select_related('department').filter(department__is_active=True):
                accessible_ids.update(link.department.get_all_descendant_ids())
            return list(accessible_ids)
        return []

    def get_manageable_department_ids(self):
        """
        Retorna os IDs de departamentos onde o usuário possui ACESSO TOTAL ('MANAGE').
        Usuários Administradores gerenciam todas as instâncias.
        """
        if self.has_full_system_access():
            return list(Department.objects.filter(is_active=True).values_list('id', flat=True))
        if hasattr(self, 'person_profile') and self.person_profile.is_active:
            manageable_ids = set()
            for link in self.person_profile.department_links.select_related('department').filter(
                role='MANAGE', department__is_active=True
            ):
                manageable_ids.update(link.department.get_all_descendant_ids())
            return list(manageable_ids)
        return []

    def get_highest_manageable_level(self):
        """
        Retorna o nível mais alto (menor número: 1=d1, 2=d2, 3=d3, 4=d4, 5=d5)
        em que o usuário possui acesso de gestão (MANAGE).
        Se for Usuário Administrador, retorna 1.
        """
        if self.has_full_system_access():
            return 1
        manageable_ids = self.get_manageable_department_ids()
        if not manageable_ids:
            return 5
        depts = Department.objects.filter(id__in=manageable_ids, is_active=True).select_related('parent')
        levels = [d.get_level() for d in depts]
        return min(levels) if levels else 5


class PersonQuerySet(models.QuerySet):
    def visible_to(self, requesting_user):
        """
        Oculta Usuários Administradores (e seus grupos administradores) de operadores que não são administradores.
        """
        if requesting_user and requesting_user.has_full_system_access():
            return self
        admin_group_ids = get_full_access_group_ids()
        return self.exclude(user__is_superuser=True).exclude(groups__id__in=admin_group_ids).distinct()

    def militants(self):
        """Filtra pessoas que pertencem ao grupo 04 - Militante."""
        return self.filter(groups__name=GROUP_MILITANTE).distinct()


class Person(models.Model):
    """
    Cadastro universal de todas as pessoas.
    """
    name = models.CharField("Nome Completo", max_length=200)
    nickname = models.CharField("Apelido / Nome Social", max_length=100, blank=True, help_text="Apelido ou nome social")
    phone = models.CharField("Telefone / WhatsApp", max_length=30, blank=True)
    email = models.EmailField("E-mail", blank=True, null=True)

    departments = models.ManyToManyField(
        Department,
        through='PersonDepartment',
        related_name='people',
        help_text="Instâncias às quais a pessoa está associada."
    )

    groups = models.ManyToManyField(
        Group, blank=False, related_name='people',
        help_text="Perfis de funções, classificação e permissões que esta pessoa possui."
    )

    responsible_militant = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_people',
        limit_choices_to={'groups__name': GROUP_MILITANTE, 'is_active': True},
        help_text="Militante responsável pelo acompanhamento."
    )

    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='person_profile'
    )

    is_active = models.BooleanField("Ativo (Visível)", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PersonQuerySet.as_manager()

    @property
    def is_militante(self):
        return any(g.name == GROUP_MILITANTE for g in self.groups.all())

    @property
    def has_full_access_group(self):
        return any(group_has_full_access(g) for g in self.groups.all())

    def get_groups_display_short(self):
        return ", ".join(g.name for g in self.groups.all())

    def sync_user_groups(self):
        """Espelha os grupos da Person para o User correspondente."""
        if self.user:
            self.user.groups.set(self.groups.all())

    def __str__(self):
        return self.name


class PersonDepartment(models.Model):
    """
    Vínculo entre Pessoa e Instância com nível de atuação em cascata:
    - VIEW: Apenas Visualização nesta instância e suas subordinadas.
    - MANAGE: Acesso Total (Criar/Editar/Ocultar) nesta instância e suas subordinadas.
    """
    ROLE_CHOICES = (
        ('MANAGE', 'Acesso Total (Gerir)'),
        ('VIEW', 'Apenas Visualização'),
    )

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='department_links')
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='person_links')
    role = models.CharField("Nível de Atuação na Instância", max_length=15, choices=ROLE_CHOICES, default='MANAGE')

    class Meta:
        unique_together = ('person', 'department')
        verbose_name = "Vínculo de Instância da Pessoa"
        verbose_name_plural = "Vínculos de Instâncias das Pessoas"

    def __str__(self):
        return f"{self.person.name} -> {self.department.code} ({self.get_role_display()})"
