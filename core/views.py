# core/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from .models import (
    Department,
    Person,
    PersonDepartment,
    User,
    GROUP_MILITANTE,
    GROUP_CONTRIBUINTE,
    GROUP_CONTATO,
    get_full_access_group_ids,
    group_has_full_access,
)
from .forms import DepartmentForm, PersonForm, GroupRoleForm, ensure_standard_groups
from finance.models import FinancialObjective, ObjectiveSettlement


def user_has_any_department_perm(user):
    return (
        user.has_perm('core.view_department')
        or user.has_perm('core.add_department')
        or user.has_perm('core.change_department')
        or user.has_perm('core.delete_department')
    )


def user_has_any_person_perm(user):
    return (
        user.has_perm('core.view_person')
        or user.has_perm('core.add_person')
        or user.has_perm('core.change_person')
        or user.has_perm('core.delete_person')
    )


def user_has_any_finance_perm(user):
    return (
        user.has_perm('finance.view_financialobjective')
        or user.has_perm('finance.add_financialobjective')
        or user.has_perm('finance.change_financialobjective')
        or user.has_perm('finance.delete_financialobjective')
        or user.has_perm('finance.view_objectivesettlement')
        or user.has_perm('finance.add_objectivesettlement')
        or user.has_perm('finance.change_objectivesettlement')
        or user.has_perm('finance.delete_objectivesettlement')
    )


def build_department_cascade_list(accessible_dept_ids, manageable_dept_ids=None, direct_roles_map=None, show_inactive=False):
    """
    Constrói uma lista ordenada em profundidade (do nível mais alto para o mais baixo)
    com recuo em cascata relativo ao topo de cada subárvore acessível ao usuário.
    Também informa se o usuário tem Acesso Total ('can_manage') ou Apenas Visualização em cada instância.
    """
    manageable_set = set(manageable_dept_ids or [])
    direct_roles_map = direct_roles_map or {}

    qs = Department.objects.filter(id__in=accessible_dept_ids).select_related('parent')
    if not show_inactive:
        qs = qs.filter(is_active=True)

    depts = list(
        qs.annotate(
            people_count=Count('people', filter=Q(people__is_active=True), distinct=True),
            children_count=Count('children', filter=Q(children__is_active=True), distinct=True),
            objectives_count=Count('financial_objectives', distinct=True),
        ).order_by('code')
    )
    dept_map = {d.id: d for d in depts}
    children_map = {d.id: [] for d in depts}
    roots = []

    for d in depts:
        if d.parent_id and d.parent_id in dept_map:
            children_map[d.parent_id].append(d)
        else:
            roots.append(d)

    roots.sort(key=lambda x: (x.get_level(), x.code))
    for parent_id in children_map:
        children_map[parent_id].sort(key=lambda x: x.code)

    cascade_list = []

    def traverse(dept, relative_depth, path_codes):
        global_level = dept.get_level()
        current_path = path_codes + [dept.code]
        direct_role = direct_roles_map.get(dept.id)
        cascade_list.append({
            'department': dept,
            'global_level': global_level,
            'level_tag': f"d{global_level}",
            'relative_depth': relative_depth,
            'indent_px': relative_depth * 28,
            'is_direct': dept.id in direct_roles_map,
            'direct_role': direct_role,
            'can_manage': dept.id in manageable_set,
            'has_children_in_scope': len(children_map.get(dept.id, [])) > 0,
            'path_display': " › ".join(current_path),
        })
        for child in children_map.get(dept.id, []):
            traverse(child, relative_depth + 1, current_path)

    for root in roots:
        traverse(root, 0, [])

    return cascade_list


def home_view(request):
    """Página raiz do sistema com suporte a login na sidebar e resumo hierárquico baseado nas permissões."""
    if request.method == 'POST' and 'login_submit' in request.POST:
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Bem-vindo(a), {user.get_full_name() or user.username}!")
            return redirect('home')
        else:
            messages.error(request, "Usuário ou senha inválidos.")

    context = {}

    if request.user.is_authenticated:
        accessible_dept_ids = request.user.get_accessible_department_ids()

        can_access_departments = user_has_any_department_perm(request.user)
        can_access_people = user_has_any_person_perm(request.user)
        can_access_finance = user_has_any_finance_perm(request.user)

        context.update({
            'can_access_departments': can_access_departments,
            'can_access_people': can_access_people,
            'can_access_finance': can_access_finance,
        })

        if can_access_departments:
            departments_qs = Department.objects.filter(id__in=accessible_dept_ids, is_active=True)
            context['accessible_departments_count'] = departments_qs.count()

        if can_access_people:
            if request.user.has_full_system_access():
                people_qs = Person.objects.visible_to(request.user).filter(is_active=True)
            else:
                people_qs = (
                    Person.objects.visible_to(request.user)
                    .filter(is_active=True, departments__id__in=accessible_dept_ids)
                    .distinct()
                )
            context.update({
                'total_people_count': people_qs.count(),
                'militantes_count': people_qs.filter(groups__name=GROUP_MILITANTE).distinct().count(),
                'contribuintes_count': people_qs.filter(groups__name=GROUP_CONTRIBUINTE).distinct().count(),
                'contatos_count': people_qs.filter(groups__name=GROUP_CONTATO).distinct().count(),
                'recent_people': (
                    people_qs.prefetch_related('department_links__department', 'groups')
                    .select_related('responsible_militant')
                    .order_by('-created_at')[:5]
                ),
            })

        if can_access_finance:
            objectives_qs = FinancialObjective.objects.filter(department_id__in=accessible_dept_ids)
            settlements_qs = ObjectiveSettlement.objects.filter(objective__department_id__in=accessible_dept_ids)

            total_expected = objectives_qs.aggregate(total=Sum('target_amount'))['total'] or 0
            total_collected = settlements_qs.aggregate(total=Sum('amount_paid'))['total'] or 0

            context.update({
                'pending_objectives_count': objectives_qs.filter(is_settled=False).count(),
                'settled_objectives_count': objectives_qs.filter(is_settled=True).count(),
                'total_expected': total_expected,
                'total_collected': total_collected,
                'recent_objectives': objectives_qs.select_related('category', 'department', 'target_person').order_by('is_settled', 'due_date')[:5],
            })

    return render(request, 'home.html', context)


# ==============================================================================
# GESTÃO DE DEPARTAMENTOS / INSTÂNCIAS (CASCATA + SOFT DELETE + PAPÉIS VIEW/MANAGE)
# ==============================================================================

@login_required
def department_list_view(request):
    if not user_has_any_department_perm(request.user):
        messages.error(request, "Você não possui permissão para acessar o módulo de Instâncias / Departamentos.")
        return redirect('home')

    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = request.user.get_manageable_department_ids()
    show_inactive = request.GET.get('ocultos') == '1'

    if show_inactive and request.user.is_superuser:
        accessible_dept_ids = list(Department.objects.values_list('id', flat=True))

    direct_roles_map = {}
    if hasattr(request.user, 'person_profile'):
        direct_roles_map = dict(
            request.user.person_profile.department_links.values_list('department_id', 'role')
        )

    has_any_manage_scope = len(manageable_dept_ids) > 0
    can_add = request.user.has_perm('core.add_department') and has_any_manage_scope
    can_change = request.user.has_perm('core.change_department') and has_any_manage_scope
    can_delete = request.user.has_perm('core.delete_department') and has_any_manage_scope

    edit_id = request.GET.get('edit')
    parent_preselect_id = request.GET.get('parent')
    editing_dept = None
    form = None

    if edit_id and can_change:
        editing_dept = get_object_or_404(Department, id=edit_id, id__in=manageable_dept_ids)
        form = DepartmentForm(instance=editing_dept, user=request.user)
    elif can_add:
        initial = {}
        if parent_preselect_id and parent_preselect_id.isdigit() and int(parent_preselect_id) in manageable_dept_ids:
            initial['parent'] = int(parent_preselect_id)
        form = DepartmentForm(initial=initial, user=request.user)

    cascade_items = build_department_cascade_list(
        accessible_dept_ids,
        manageable_dept_ids=manageable_dept_ids,
        direct_roles_map=direct_roles_map,
        show_inactive=show_inactive,
    )

    context = {
        'cascade_items': cascade_items,
        'total_accessible': len(cascade_items),
        'form': form,
        'editing_dept': editing_dept,
        'can_add_dept': can_add,
        'can_change_dept': can_change,
        'can_delete_dept': can_delete,
        'show_inactive': show_inactive,
    }
    return render(request, 'core/department_list.html', context)


@login_required
def department_save_view(request, pk=None):
    if request.method != 'POST':
        return redirect('department_list')

    manageable_dept_ids = request.user.get_manageable_department_ids()

    if pk is None and not (request.user.has_perm('core.add_department') and manageable_dept_ids):
        messages.error(request, "Você não tem permissão de gestão para cadastrar novas instâncias.")
        return redirect('department_list')

    if pk is not None and not (request.user.has_perm('core.change_department') and manageable_dept_ids):
        messages.error(request, "Você não tem permissão de gestão para editar instâncias.")
        return redirect('department_list')

    instance = None
    if pk is not None:
        instance = get_object_or_404(Department, pk=pk, id__in=manageable_dept_ids)

    form = DepartmentForm(request.POST, instance=instance, user=request.user)
    if form.is_valid():
        try:
            dept = form.save()
            if instance is None:
                messages.success(request, f"Instância '{dept.code} - {dept.name}' cadastrada com sucesso!")
            else:
                messages.success(request, f"Instância '{dept.code} - {dept.name}' atualizada com sucesso!")
            return redirect('department_list')
        except Exception as exc:
            messages.error(request, f"Erro ao salvar instância: {exc}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)

    return redirect('department_list')


@login_required
def department_delete_view(request, pk):
    """Nada é excluído fisicamente: oculta (is_active=False) ou reativa (is_active=True) a instância."""
    if request.method == 'POST':
        manageable_dept_ids = request.user.get_manageable_department_ids()
        if not (request.user.has_perm('core.delete_department') or request.user.has_perm('core.change_department')):
            messages.error(request, "Você não tem permissão para ocultar/reativar instâncias.")
            return redirect('department_list')

        dept = get_object_or_404(Department, pk=pk, id__in=manageable_dept_ids)
        if dept.is_active:
            active_children = dept.children.filter(is_active=True).count()
            if active_children > 0:
                messages.error(
                    request,
                    f"Não é possível ocultar '{dept.code}' enquanto ela possuir {active_children} sub-instância(s) ativa(s)."
                )
                return redirect('department_list')
            dept.is_active = False
            dept.save(update_fields=['is_active'])
            messages.warning(request, f"Instância '{dept.code} - {dept.name}' foi ocultada da listagem ativa.")
        else:
            dept.is_active = True
            dept.save(update_fields=['is_active'])
            messages.success(request, f"Instância '{dept.code} - {dept.name}' foi reativada com sucesso.")
    return redirect('department_list')


# ==============================================================================
# GESTÃO DE PESSOAS E USUÁRIOS (USANDO OS 6 GRUPOS PARA PERFIS E FILTROS ANALÍTICOS)
# ==============================================================================

@login_required
def person_list_view(request):
    """
    Listagem e filtros de Pessoas no template do frontend:
    - Filtra por Grupo (01 a 06), Instância, Busca textual e Ativos/Ocultos.
    """
    if not user_has_any_person_perm(request.user):
        messages.error(request, "Você não possui permissão para acessar o módulo de Cadastro de Pessoas.")
        return redirect('home')

    ensure_standard_groups()
    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = set(request.user.get_manageable_department_ids())

    group_filter = request.GET.get('group', '').strip()
    dept_filter = request.GET.get('department', '').strip()
    search_query = request.GET.get('q', '').strip()
    show_inactive = request.GET.get('ocultos') == '1'

    has_full_access = request.user.has_full_system_access()

    base_people_qs = Person.objects.visible_to(request.user)
    if not has_full_access:
        base_people_qs = base_people_qs.filter(departments__id__in=accessible_dept_ids)

    people_qs = (
        base_people_qs
        .prefetch_related('department_links__department', 'groups')
        .select_related('responsible_militant', 'user')
        .distinct()
    )

    if show_inactive:
        people_qs = people_qs.filter(is_active=False)
    else:
        people_qs = people_qs.filter(is_active=True)

    if group_filter.isdigit():
        people_qs = people_qs.filter(groups__id=int(group_filter))

    if dept_filter.isdigit() and int(dept_filter) in accessible_dept_ids:
        people_qs = people_qs.filter(departments__id=int(dept_filter))

    if search_query:
        people_qs = people_qs.filter(
            Q(name__icontains=search_query)
            | Q(nickname__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(user__username__icontains=search_query)
        )

    people_list = list(people_qs.order_by('name'))

    can_change_perm = request.user.has_perm('core.change_person')
    can_delete_perm = request.user.has_perm('core.delete_person') or can_change_perm

    for p in people_list:
        person_dept_ids = {link.department_id for link in p.department_links.all()}
        has_manage_on_person = bool(person_dept_ids & manageable_dept_ids) or has_full_access
        p.can_user_edit = can_change_perm and has_manage_on_person
        p.can_user_toggle_active = can_delete_perm and has_manage_on_person

    # Contadores por Grupo dentro do escopo visível para os cards analíticos
    base_scope_qs = Person.objects.visible_to(request.user).filter(is_active=True)
    if not has_full_access:
        base_scope_qs = base_scope_qs.filter(departments__id__in=accessible_dept_ids)
    base_scope_qs = base_scope_qs.distinct()

    # Operadores não administradores só enxergam os grupos que não são administradores e compatíveis com seu nível
    if has_full_access:
        visible_groups = list(Group.objects.all().order_by('name'))
    else:
        admin_group_ids = set(get_full_access_group_ids())
        visible_groups = list(Group.objects.exclude(id__in=admin_group_ids).order_by('name'))

    group_cards = []
    for g in visible_groups:
        count = base_scope_qs.filter(groups__id=g.id).distinct().count()
        group_cards.append({
            'group': g,
            'count': count,
            'is_active_filter': group_filter.isdigit() and int(group_filter) == g.id,
        })

    cascade_depts = build_department_cascade_list(accessible_dept_ids, manageable_dept_ids=manageable_dept_ids)

    context = {
        'people': people_list,
        'cascade_depts': cascade_depts,
        'all_groups': visible_groups,
        'group_cards': group_cards,
        'group_filter': int(group_filter) if group_filter.isdigit() else None,
        'dept_filter': int(dept_filter) if dept_filter.isdigit() else None,
        'search_query': search_query,
        'show_inactive': show_inactive,
        'can_add_person': request.user.has_perm('core.add_person') and (len(manageable_dept_ids) > 0 or has_full_access),
        'total_active_count': base_scope_qs.count(),
    }
    return render(request, 'core/person_list.html', context)


@login_required
def person_form_view(request, pk=None):
    """
    Criação e Edição de Pessoa usando os 6 Grupos:
    - Se o grupo '04 - Militante' estiver marcado: permite vincular a qualquer instância (d1 a d5) com papel VIEW ou MANAGE.
    - Caso contrário (ex: '05 - Contribuinte' ou '06 - Contato'): vincula a uma Célula e exige Militante Responsável.
    """
    ensure_standard_groups()
    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = request.user.get_manageable_department_ids()
    manageable_set = set(manageable_dept_ids)

    if pk is None:
        if not (request.user.has_perm('core.add_person') and manageable_set):
            messages.error(request, "Você não possui permissão de gestão para cadastrar pessoas.")
            return redirect('person_list')
        person = None
    else:
        if not (request.user.has_perm('core.change_person') and (manageable_set or request.user.has_full_system_access())):
            messages.error(request, "Você não possui permissão para editar pessoas.")
            return redirect('person_list')
        qs_edit = Person.objects.visible_to(request.user)
        if not request.user.has_full_system_access():
            qs_edit = qs_edit.filter(departments__id__in=accessible_dept_ids)
        person = get_object_or_404(qs_edit.distinct(), pk=pk)
        person_dept_ids = set(person.department_links.values_list('department_id', flat=True))
        if not (person_dept_ids & manageable_set) and not request.user.has_full_system_access():
            messages.error(request, "Você possui apenas visualização nas instâncias desta pessoa e não pode editá-la.")
            return redirect('person_list')

    manageable_cascade = build_department_cascade_list(
        manageable_dept_ids,
        manageable_dept_ids=manageable_dept_ids,
    )

    cell_items = [
        item for item in manageable_cascade
        if item['global_level'] >= 5 or item['department'].children_count == 0
    ]

    militant_group = Group.objects.filter(name=GROUP_MILITANTE).first()
    militant_group_id = militant_group.id if militant_group else 0
    full_access_group_ids = set(get_full_access_group_ids())

    existing_links_map = {}
    if person:
        existing_links_map = dict(person.department_links.values_list('department_id', 'role'))

    if request.method == 'POST':
        form = PersonForm(request.POST, instance=person, requesting_user=request.user)
        posted_group_ids = {int(gid) for gid in request.POST.getlist('groups') if gid.isdigit()}
        is_militant_selected = militant_group_id in posted_group_ids
        is_full_access_selected = bool(posted_group_ids & full_access_group_ids)

        selected_links = {}
        dept_error = None

        if is_militant_selected or is_full_access_selected:
            selected_ids = request.POST.getlist('militant_departments')
            for raw_id in selected_ids:
                if raw_id.isdigit() and int(raw_id) in manageable_set:
                    d_id = int(raw_id)
                    role_val = request.POST.get(f'role_{d_id}', 'MANAGE')
                    if role_val not in ['MANAGE', 'VIEW']:
                        role_val = 'MANAGE'
                    selected_links[d_id] = role_val
            # Só exige instância obrigatória se NÃO tiver grupo de acesso total (01 - Administração)
            if not selected_links and not is_full_access_selected:
                dept_error = 'Para pessoas no grupo "03 - Militante", selecione pelo menos 1 instância de vínculo.'
        else:
            cell_id = request.POST.get('cell_department', '').strip()
            if cell_id.isdigit() and int(cell_id) in manageable_set:
                selected_links[int(cell_id)] = 'VIEW'
            else:
                dept_error = 'Selecione obrigatoriamente a Célula à qual o Contribuinte/Contato está vinculado.'

        if dept_error:
            messages.error(request, dept_error)

        if form.is_valid() and not dept_error:
            with transaction.atomic():
                saved_person = form.save(commit=False)

                has_login = form.cleaned_data.get('has_login')
                username = (form.cleaned_data.get('username') or '').strip()
                password = form.cleaned_data.get('password') or ''

                if has_login:
                    if saved_person.user:
                        user_obj = saved_person.user
                        user_obj.username = username
                        user_obj.email = saved_person.email or ''
                        user_obj.first_name = saved_person.name.split()[0] if saved_person.name else ''
                        user_obj.is_active = saved_person.is_active
                        if password:
                            user_obj.set_password(password)
                        user_obj.save()
                    else:
                        user_obj = User.objects.create_user(
                            username=username,
                            email=saved_person.email or '',
                            password=password,
                            first_name=saved_person.name.split()[0] if saved_person.name else '',
                            is_active=saved_person.is_active,
                        )
                        saved_person.user = user_obj
                else:
                    if saved_person.user:
                        user_obj = saved_person.user
                        user_obj.is_active = False
                        user_obj.save(update_fields=['is_active'])

                saved_person.save()
                if person and not request.user.has_full_system_access():
                    # Preserva grupos que a pessoa já possuía mas que estão acima do perfil do operador atual
                    assignable_ids = set(request.user.get_assignable_groups_queryset().values_list('id', flat=True))
                    preserved_ids = set(person.groups.exclude(id__in=assignable_ids).values_list('id', flat=True))
                    new_group_ids = {g.id for g in form.cleaned_data['groups']} | preserved_ids
                    saved_person.groups.set(new_group_ids)
                else:
                    form.save_m2m()
                saved_person.sync_user_groups()

                if person:
                    previous_dept_ids = set(
                        saved_person.department_links.filter(department_id__in=manageable_set)
                        .values_list('department_id', flat=True)
                    )
                    unlinked_dept_ids = previous_dept_ids - set(selected_links.keys())
                    if unlinked_dept_ids:
                        # Mantém todos os lançamentos até este momento vinculados à instância original
                        # e registra o momento da desvinculação da pessoa na instância
                        FinancialObjective.objects.filter(
                            target_person=saved_person,
                            department_id__in=unlinked_dept_ids,
                            unlinked_at__isnull=True,
                        ).update(unlinked_at=timezone.now())

                    if not saved_person.is_active:
                        FinancialObjective.objects.filter(
                            target_person=saved_person,
                            unlinked_at__isnull=True,
                        ).update(unlinked_at=timezone.now())

                    saved_person.department_links.filter(department_id__in=manageable_set).delete()
                for d_id, role_code in selected_links.items():
                    PersonDepartment.objects.update_or_create(
                        person=saved_person,
                        department_id=d_id,
                        defaults={'role': role_code},
                    )

            messages.success(
                request,
                f"Cadastro de '{saved_person.name}' salvo com sucesso!"
            )
            return redirect('person_list')
        else:
            existing_links_map = selected_links
    else:
        form = PersonForm(instance=person, requesting_user=request.user)

    for item in manageable_cascade:
        d_id = item['department'].id
        item['is_selected'] = d_id in existing_links_map
        item['selected_role'] = existing_links_map.get(d_id, 'MANAGE')

    selected_cell_id = next(iter(existing_links_map.keys()), None)

    context = {
        'form': form,
        'person': person,
        'manageable_cascade': manageable_cascade,
        'cell_items': cell_items,
        'selected_cell_id': selected_cell_id,
        'militant_group_id': militant_group_id,
        'full_access_group_ids_csv': ",".join(str(gid) for gid in full_access_group_ids),
    }
    return render(request, 'core/person_form.html', context)


@login_required
def person_toggle_active_view(request, pk):
    """Nada é excluído fisicamente: oculta (is_active=False) ou restaura (is_active=True) uma Pessoa."""
    if request.method == 'POST':
        manageable_set = set(request.user.get_manageable_department_ids())
        if not (request.user.has_perm('core.delete_person') or request.user.has_perm('core.change_person')):
            messages.error(request, "Você não possui permissão para ocultar ou reativar pessoas.")
            return redirect('person_list')

        qs_toggle = Person.objects.visible_to(request.user)
        if not request.user.has_full_system_access():
            qs_toggle = qs_toggle.filter(departments__id__in=request.user.get_accessible_department_ids())
        person = get_object_or_404(qs_toggle.distinct(), pk=pk)
        person_dept_ids = set(person.department_links.values_list('department_id', flat=True))
        if not (person_dept_ids & manageable_set) and not request.user.has_full_system_access():
            messages.error(request, "Você não possui acesso de gestão nas instâncias desta pessoa.")
            return redirect('person_list')

        person.is_active = not person.is_active
        person.save(update_fields=['is_active'])

        if not person.is_active:
            # Mantém todos os lançamentos vinculados às suas respectivas instâncias até o momento da inativação
            FinancialObjective.objects.filter(
                target_person=person,
                unlinked_at__isnull=True,
            ).update(unlinked_at=timezone.now())

        if person.user and not person.is_active:
            person.user.is_active = False
            person.user.save(update_fields=['is_active'])

        if person.is_active:
            messages.success(request, f"O cadastro de '{person.name}' foi reativado e voltou para a listagem ativa.")
        else:
            messages.warning(request, f"O cadastro de '{person.name}' foi ocultado (nenhum histórico foi apagado).")

    return redirect('person_list')


# ==============================================================================
# ADMINISTRAÇÃO DO SISTEMA E SUBGRUPOS / PERFIS (100% NO TEMPLATE DO FRONTEND)
# ==============================================================================

PERMISSION_LABELS_PT = {
    'view_department': 'Visualizar Instâncias / Departamentos',
    'add_department': 'Cadastrar Instâncias / Departamentos',
    'change_department': 'Editar Instâncias / Departamentos',
    'delete_department': 'Ocultar / Reativar Instâncias',
    'view_person': 'Visualizar Cadastro de Pessoas',
    'add_person': 'Cadastrar Novas Pessoas e Usuários',
    'change_person': 'Editar Pessoas, Grupos e Credenciais',
    'delete_person': 'Ocultar / Reativar Pessoas',
    'view_financialobjective': 'Visualizar Objetivos Financeiros',
    'add_financialobjective': 'Lançar Objetivos Financeiros',
    'change_financialobjective': 'Editar Objetivos Financeiros',
    'delete_financialobjective': 'Ocultar / Cancelar Objetivos Financeiros',
    'view_objectivesettlement': 'Visualizar Liquidações / Pagamentos',
    'add_objectivesettlement': 'Registrar Liquidações / Pagamentos',
    'change_objectivesettlement': 'Editar Liquidações / Pagamentos',
    'delete_objectivesettlement': 'Estornar / Ocultar Liquidações',
}


@login_required
def system_admin_view(request):
    """
    Painel de Administração do Sistema e Gestão de Grupos/Subgrupos (01 a 06)
    100% integrado ao template Bootstrap do frontend.
    """
    if not (request.user.has_full_system_access() or request.user.has_perm('auth.view_group') or request.user.has_perm('auth.change_group')):
        messages.error(request, "Você não possui permissão para acessar a Administração de Grupos e Permissões.")
        return redirect('home')

    ensure_standard_groups()

    edit_id = request.GET.get('edit')
    editing_group = None
    if edit_id and edit_id.isdigit():
        editing_group = get_object_or_404(Group, id=int(edit_id))

    if request.method == 'POST':
        group_id = request.POST.get('group_id')
        instance = get_object_or_404(Group, id=int(group_id)) if (group_id and group_id.isdigit()) else None
        form = GroupRoleForm(request.POST, instance=instance)
        if form.is_valid():
            saved_group = form.save()
            # Sincroniza todos os usuários vinculados às pessoas deste grupo
            for person in saved_group.people.select_related('user').all():
                person.sync_user_groups()
            messages.success(request, f"Grupo '{saved_group.name}' e suas permissões foram salvos com sucesso!")
            return redirect('system_admin')
    else:
        form = GroupRoleForm(instance=editing_group)

    # Organiza as permissões dos módulos principais agrupadas para exibição limpa em cards
    module_Sections = [
        {
            'title': 'Módulo de Instâncias (Departamentos)',
            'icon': 'bi-diagram-3-fill text-danger',
            'codenames': ['view_department', 'add_department', 'change_department', 'delete_department'],
        },
        {
            'title': 'Módulo de Pessoas & Usuários',
            'icon': 'bi-people-fill text-primary',
            'codenames': ['view_person', 'add_person', 'change_person', 'delete_person'],
        },
        {
            'title': 'Módulo Financeiro: Objetivos e Metas',
            'icon': 'bi-bullseye text-success',
            'codenames': ['view_financialobjective', 'add_financialobjective', 'change_financialobjective', 'delete_financialobjective'],
        },
        {
            'title': 'Módulo Financeiro: Liquidações e Pagamentos',
            'icon': 'bi-cash-coin text-warning',
            'codenames': ['view_objectivesettlement', 'add_objectivesettlement', 'change_objectivesettlement', 'delete_objectivesettlement'],
        },
    ]

    all_Target_codenames = [c for sec in module_Sections for c in sec['codenames']]
    perms_by_codename = {
        p.codename: p
        for p in Permission.objects.filter(codename__in=all_Target_codenames)
    }

    selected_perm_ids = set()
    if editing_group:
        selected_perm_ids = set(editing_group.permissions.values_list('id', flat=True))

    for sec in module_Sections:
        items = []
        for code in sec['codenames']:
            perm_obj = perms_by_codename.get(code)
            if perm_obj:
                items.append({
                    'id': perm_obj.id,
                    'codename': code,
                    'label': PERMISSION_LABELS_PT.get(code, perm_obj.name),
                    'checked': perm_obj.id in selected_perm_ids,
                })
        sec['permissions'] = items

    groups_qs = (
        Group.objects.prefetch_related('permissions')
        .annotate(
            people_count=Count('people', filter=Q(people__is_active=True), distinct=True),
            users_count=Count('user', filter=Q(user__is_active=True), distinct=True),
        )
        .order_by('name')
    )

    groups_data = []
    for g in groups_qs:
        g_codenames = set(g.permissions.values_list('codename', flat=True))
        groups_data.append({
            'group': g,
            'people_count': g.people_count,
            'users_count': g.users_count,
            'is_full_access': group_has_full_access(g),
            'perm_labels': [PERMISSION_LABELS_PT[c] for c in all_Target_codenames if c in g_codenames],
        })

    context = {
        'groups_data': groups_data,
        'editing_group': editing_group,
        'form': form,
        'module_sections': module_Sections,
        'can_delete_groups': request.user.has_full_system_access(),
    }
    return render(request, 'core/system_admin.html', context)


@login_required
def group_delete_view(request, pk):
    """Permite que Usuários Administradores excluam grupos."""
    if request.method == 'POST':
        if not request.user.has_full_system_access():
            messages.error(request, "Apenas usuários administradores podem excluir grupos.")
            return redirect('system_admin')

        group = get_object_or_404(Group, pk=pk)
        group_name = group.name
        group.delete()
        messages.success(request, f"O grupo '{group_name}' foi excluído com sucesso.")
    return redirect('system_admin')


def logout_view(request):
    """Encerra a sessão do usuário e retorna para a página raiz."""
    if request.method == 'POST':
        logout(request)
        messages.info(request, "Você saiu do sistema.")
    return redirect('home')
