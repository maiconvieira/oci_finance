# finance/views.py
import calendar
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Q, ProtectedError
from django.utils import timezone
from core.models import Department, Person, PersonDepartment, GROUP_MILITANTE, GROUP_CONTRIBUINTE
from core.views import (
    user_has_any_finance_perm,
    build_department_cascade_list,
)
from .models import ObjectiveCategory, FinancialObjective, ObjectiveSettlement
from .receipt_parser import extract_text_from_uploaded_file, parse_receipt_text
from .gdrive import upload_receipt_to_google_drive
from .forms import (
    ObjectiveCategoryForm,
    FinancialObjectiveForm,
    ObjectiveSettlementForm,
    resolve_target_cell_departments,
    get_visible_categories_for_user,
    can_user_manage_category,
)


def build_departments_by_level_meta(manageable_dept_ids):
    """
    Agrupa as instâncias gerenciáveis pelo usuário por nível hierárquico (1 a 5).
    """
    by_level = {'1': [], '2': [], '3': [], '4': [], '5': []}
    depts = (
        Department.objects.filter(id__in=manageable_dept_ids, is_active=True)
        .select_related('parent')
        .order_by('code')
    )
    for d in depts:
        lvl = d.get_level()
        by_level.setdefault(str(lvl), []).append({
            'id': d.id,
            'code': d.code,
            'name': d.name,
            'level': lvl,
        })
    return by_level


def add_one_month(orig_date):
    """Avança uma data em exatamente 1 mês (ajustando o dia final caso necessário, ex: 31/01 -> 28/02)."""
    if not orig_date:
        return None
    year = orig_date.year + (orig_date.month // 12)
    month = (orig_date.month % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(orig_date.day, max_day)
    return date(year, month, day)


def propagate_objective_to_descendants(parent_obj, allowed_dept_ids=None, min_replication_level=0):
    """
    Quando um objetivo é lançado em uma instância superior (ex: CC, CR ou Setor),
    replica/herda automaticamente esse objetivo para as instâncias subordinadas abaixo
    de acordo com o nível de replicação configurado na Receita.
    """
    descendant_ids = parent_obj.department.get_all_descendant_ids()
    child_ids = [d_id for d_id in descendant_ids if d_id != parent_obj.department_id]
    if allowed_dept_ids is not None:
        child_ids = [d_id for d_id in child_ids if d_id in allowed_dept_ids]

    child_depts = Department.objects.filter(id__in=child_ids, is_active=True).select_related('parent')

    created_count = 0
    for child_dept in child_depts:
        # Se a receita especificou um nível mínimo de replicação (ex: 3 = d3 para baixo),
        # só replica para instâncias cujo nível seja >= ao nível configurado
        if min_replication_level and child_dept.get_level() < min_replication_level:
            continue

        already_exists = FinancialObjective.objects.filter(
            parent_objective=parent_obj,
            department_id=child_dept.id,
            is_active=True,
        ).exists()
        if not already_exists:
            FinancialObjective.objects.create(
                title=parent_obj.title,
                category=parent_obj.category,
                frequency=parent_obj.frequency,
                reference_month=parent_obj.reference_month,
                department_id=child_dept.id,
                parent_objective=parent_obj,
                target_person=None,
                editions_count=parent_obj.editions_count,
                initial_edition=parent_obj.initial_edition,
                final_edition=parent_obj.final_edition,
                edition_number=parent_obj.edition_number,
                target_quantity=parent_obj.target_quantity,
                unit_price=parent_obj.unit_price,
                target_amount=parent_obj.target_amount,
                due_date=parent_obj.due_date,
                notes=parent_obj.notes,
                is_active=True,
            )
            created_count += 1
    return created_count


@login_required
def category_list_view(request):
    """
    Tela dedicada para Cadastrar, Editar e Personalizar Tipos / Nomes de Receita:
    - Todo pagamento é feito no nível da Célula (d5).
    - Permite escolher o nível de replicação (d2, d3, d4 ou d5, nunca superior ao acesso do usuário)
      e selecionar quais instâncias daquele nível terão o lançamento replicado para as suas Células (d5).
    - Se quem criou a receita perder acesso à instância, qualquer usuário que tenha acesso de gestão
      àquela instância pode visualizá-la e modificá-la.
    """
    if not user_has_any_finance_perm(request.user):
        messages.error(request, "Você não possui permissão para acessar o cadastro de receitas.")
        return redirect('home')

    manageable_dept_ids = set(request.user.get_manageable_department_ids())
    has_full_access = request.user.has_full_system_access()

    edit_id = request.GET.get('edit')
    editing_category = None
    if edit_id and edit_id.isdigit():
        candidate = get_object_or_404(ObjectiveCategory, id=int(edit_id))
        if can_user_manage_category(request.user, candidate):
            editing_category = candidate
        else:
            messages.error(request, "Você não possui acesso de gestão nas instâncias desta receita para editá-la.")
            return redirect('category_list')

    selected_target_dept_ids = []
    if editing_category:
        selected_target_dept_ids = list(editing_category.target_departments.values_list('id', flat=True))

    if request.method == 'POST':
        cat_id = request.POST.get('category_id')
        instance = get_object_or_404(ObjectiveCategory, id=int(cat_id)) if (cat_id and cat_id.isdigit()) else editing_category
        if instance and not can_user_manage_category(request.user, instance):
            messages.error(request, "Você não possui permissão de gestão nas instâncias desta receita.")
            return redirect('category_list')

        form = ObjectiveCategoryForm(request.POST, instance=instance, requesting_user=request.user)
        if form.is_valid():
            with transaction.atomic():
                saved_cat = form.save(commit=False)
                saved_cat.replication_level = form.cleaned_data.get('replication_level', 5)
                if not saved_cat.created_by_id:
                    saved_cat.created_by = request.user
                saved_cat.save()
                saved_cat.target_departments.set(form.cleaned_data.get('target_departments') or [])

            messages.success(request, f"Receita '{saved_cat.code} - {saved_cat.name}' salva com sucesso!")
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('category_list')
        else:
            selected_target_dept_ids = [
                int(x) for x in request.POST.getlist('target_departments') if str(x).isdigit()
            ]
            for field, errors in form.errors.items():
                for err in errors:
                    messages.error(request, err)
    else:
        form = ObjectiveCategoryForm(instance=editing_category, requesting_user=request.user)

    categories = get_visible_categories_for_user(request.user)
    for cat in categories:
        cat.can_user_edit = can_user_manage_category(request.user, cat)
        cat.target_depts_list = list(cat.target_departments.all().order_by('code'))

    user_max_level = request.user.get_highest_manageable_level()
    depts_by_level = build_departments_by_level_meta(manageable_dept_ids)

    context = {
        'categories': categories,
        'form': form,
        'editing_category': editing_category,
        'user_max_level': user_max_level,
        'depts_by_level_json': json.dumps(depts_by_level),
        'selected_target_dept_ids_json': json.dumps(selected_target_dept_ids),
    }
    return render(request, 'finance/category_list.html', context)


@login_required
def category_delete_view(request, pk):
    """Permite excluir uma receita (se não tiver lançamentos) ou ocultá-la."""
    if request.method == 'POST':
        if not user_has_any_finance_perm(request.user):
            return redirect('home')
        cat = get_object_or_404(ObjectiveCategory, pk=pk)
        if not can_user_manage_category(request.user, cat):
            messages.error(request, "Você não possui permissão de gestão nas instâncias desta receita.")
            return redirect('category_list')
        cat_name = f"{cat.code} - {cat.name}"
        try:
            cat.delete()
            messages.success(request, f"Receita '{cat_name}' removida com sucesso.")
        except ProtectedError:
            cat.is_active = not cat.is_active
            cat.save(update_fields=['is_active'])
            if cat.is_active:
                messages.success(request, f"Receita '{cat_name}' foi reativada.")
            else:
                messages.warning(
                    request,
                    f"A receita '{cat_name}' já possui lançamentos vinculados e por isso foi apenas ocultada."
                )
    return redirect('category_list')


@login_required
def objective_list_view(request):
    """
    Listagem principal de Objetivos Financeiros e Liquidações no template Bootstrap 5.
    """
    if not user_has_any_finance_perm(request.user):
        messages.error(request, "Você não possui permissão para acessar o Módulo Financeiro.")
        return redirect('home')

    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = set(request.user.get_manageable_department_ids())
    has_full_access = request.user.has_full_system_access()

    month_filter = request.GET.get('mes', '').strip()
    category_filter = request.GET.get('category', '').strip()
    frequency_filter = request.GET.get('frequency', '').strip()
    dept_filter = request.GET.get('department', '').strip()
    settled_filter = request.GET.get('settled', '').strip()
    search_query = request.GET.get('q', '').strip()
    show_inactive = request.GET.get('ocultos') == '1'

    objectives_qs = (
        FinancialObjective.objects.filter(department_id__in=accessible_dept_ids)
        .select_related(
            'category',
            'department',
            'origin_department',
            'target_person',
            'parent_objective__department',
        )
        .prefetch_related('settlements__collected_by')
    )

    if show_inactive:
        objectives_qs = objectives_qs.filter(is_active=False)
    else:
        objectives_qs = objectives_qs.filter(is_active=True)

    if month_filter:
        try:
            parts = month_filter.split('-')
            ref_date = date(int(parts[0]), int(parts[1]), 1)
            objectives_qs = objectives_qs.filter(reference_month=ref_date)
        except (ValueError, IndexError):
            pass

    if category_filter.isdigit():
        objectives_qs = objectives_qs.filter(category_id=int(category_filter))

    if frequency_filter in ['PONTUAL', 'MENSAL']:
        objectives_qs = objectives_qs.filter(frequency=frequency_filter)

    if dept_filter.isdigit() and int(dept_filter) in accessible_dept_ids:
        target_dept = Department.objects.filter(id=int(dept_filter)).first()
        if target_dept:
            sub_ids = [i for i in target_dept.get_all_descendant_ids() if i in accessible_dept_ids]
            objectives_qs = objectives_qs.filter(department_id__in=sub_ids)

    if settled_filter == '1':
        objectives_qs = objectives_qs.filter(is_settled=True)
    elif settled_filter == '0':
        objectives_qs = objectives_qs.filter(is_settled=False)

    if search_query:
        objectives_qs = objectives_qs.filter(
            Q(title__icontains=search_query)
            | Q(target_person__name__icontains=search_query)
            | Q(edition_number__icontains=search_query)
            | Q(category__name__icontains=search_query)
            | Q(department__code__icontains=search_query)
        )

    objectives_list = list(objectives_qs.order_by('is_settled', 'due_date', '-created_at'))

    can_add_obj = request.user.has_perm('finance.add_financialobjective')
    can_change_obj = request.user.has_perm('finance.change_financialobjective')
    can_delete_obj = request.user.has_perm('finance.delete_financialobjective') or can_change_obj
    can_add_settlement = request.user.has_perm('finance.add_objectivesettlement')

    total_expected = Decimal('0.00')
    total_paid_effective = Decimal('0.00')

    for obj in objectives_list:
        has_manage = (obj.department_id in manageable_dept_ids) or has_full_access
        obj.can_user_edit = can_change_obj and has_manage
        obj.can_user_toggle = can_delete_obj and has_manage
        obj.can_user_settle = can_add_settlement and has_manage
        obj.can_user_duplicate = (
            can_add_obj
            and has_manage
            and obj.frequency == 'PONTUAL'
            and obj.is_active
        )
        paid_val = obj.total_paid
        obj.paid_val = paid_val
        obj.diff_val = paid_val - obj.target_amount
        total_expected += obj.target_amount
        total_paid_effective += paid_val

    cascade_depts = build_department_cascade_list(accessible_dept_ids, manageable_dept_ids=manageable_dept_ids)
    categories = ObjectiveCategory.objects.filter(is_active=True).order_by('name')

    context = {
        'objectives': objectives_list,
        'categories': categories,
        'cascade_depts': cascade_depts,
        'month_filter': month_filter,
        'category_filter': int(category_filter) if category_filter.isdigit() else None,
        'frequency_filter': frequency_filter,
        'dept_filter': int(dept_filter) if dept_filter.isdigit() else None,
        'settled_filter': settled_filter,
        'search_query': search_query,
        'show_inactive': show_inactive,
        'total_expected': total_expected,
        'total_paid_effective': total_paid_effective,
        'total_difference': total_paid_effective - total_expected,
        'pending_count': sum(1 for o in objectives_list if not o.is_settled),
        'settled_count': sum(1 for o in objectives_list if o.is_settled),
        'can_add_objective': request.user.has_perm('finance.add_financialobjective') and (len(manageable_dept_ids) > 0 or has_full_access),
    }
    return render(request, 'finance/objective_list.html', context)


@login_required
def objective_form_view(request, pk=None):
    """
    Tela de lançamento/edição de Objetivos Financeiros:
    - Os campos exibidos, seus valores padrões e se são obrigatórios ou opcionais
      seguem 100% a personalização cadastrada na Receita escolhida.
    """
    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = set(request.user.get_manageable_department_ids())
    has_full_access = request.user.has_full_system_access()

    if pk is None:
        if not (request.user.has_perm('finance.add_financialobjective') and (manageable_dept_ids or has_full_access)):
            messages.error(request, "Você não possui permissão para lançar objetivos financeiros.")
            return redirect('objective_list')
        objective = None
    else:
        if not (request.user.has_perm('finance.change_financialobjective') and (manageable_dept_ids or has_full_access)):
            messages.error(request, "Você não possui permissão para editar objetivos financeiros.")
            return redirect('objective_list')
        objective = get_object_or_404(FinancialObjective, pk=pk, department_id__in=accessible_dept_ids)
        if objective.department_id not in manageable_dept_ids and not has_full_access:
            messages.error(request, "Você possui apenas visualização na instância deste objetivo.")
            return redirect('objective_list')

    if request.method == 'POST':
        form = FinancialObjectiveForm(request.POST, instance=objective, requesting_user=request.user)
        if form.is_valid():
            with transaction.atomic():
                saved_obj = form.save(commit=False)
                saved_obj.reference_month = form.cleaned_data.get('reference_month')
                if not saved_obj.created_by_id:
                    saved_obj.created_by = request.user
                origin_dept = saved_obj.category.get_origin_for_department(saved_obj.department)
                if origin_dept and origin_dept.id != saved_obj.department_id:
                    saved_obj.origin_department = origin_dept
                saved_obj.save()

            if objective is None:
                messages.success(
                    request,
                    f"Objetivo '{saved_obj.title}' lançado com sucesso para a célula '{saved_obj.department.code}'!"
                )
            else:
                messages.success(
                    request,
                    f"Objetivo '{saved_obj.title}' atualizado com sucesso!"
                )
            return redirect('objective_list')
    else:
        form = FinancialObjectiveForm(instance=objective, requesting_user=request.user)

    # Metadados completos das receitas cadastradas para o JavaScript montar o formulário sob medida
    categories_meta = {}
    for cat in get_visible_categories_for_user(request.user):
        if not cat.is_active and not (objective and objective.category_id == cat.id):
            continue
        inherited_dept_ids = list(cat.get_inherited_department_ids())
        if objective and objective.category_id == cat.id and objective.department_id:
            if objective.department_id not in inherited_dept_ids:
                inherited_dept_ids.append(objective.department_id)
        categories_meta[str(cat.id)] = {
            'name': cat.name,
            'code': cat.code,
            'default_frequency': cat.default_frequency,
            'use_unit_price': cat.use_unit_price,
            'unit_price_required': cat.unit_price_required,
            'default_unit_price': str(cat.default_unit_price or ''),
            'use_quantity': cat.use_quantity,
            'quantity_required': cat.quantity_required,
            'default_quantity': str(cat.default_quantity or ''),
            'is_subscription': cat.is_subscription,
            'use_editions_count': cat.use_editions_count,
            'editions_count_required': cat.editions_count_required,
            'default_editions_count': str(cat.default_editions_count or ''),
            'use_initial_final_edition': cat.use_initial_final_edition,
            'initial_final_edition_required': cat.initial_final_edition_required,
            'default_initial_edition': str(cat.default_initial_edition or ''),
            'default_final_edition': str(cat.default_final_edition or ''),
            'person_required': cat.person_required,
            'use_notes': cat.use_notes,
            'notes_required': cat.notes_required,
            'replication_level': cat.replication_level,
            'replication_label': cat.get_replication_level_display(),
            'allowed_dept_ids': inherited_dept_ids,
        }

    depts_with_children = [
        str(d.id) for d in Department.objects.filter(id__in=manageable_dept_ids, is_active=True)
        if d.children.filter(is_active=True).exists()
    ]
    depts_by_level = build_departments_by_level_meta(manageable_dept_ids)
    user_max_level = request.user.get_highest_manageable_level()

    # Mapa de Pessoas vinculadas por Instância (para filtrar o campo Pessoa ao selecionar a Instância)
    dept_people_map = {}
    visible_active_person_ids = set(
        Person.objects.visible_to(request.user).filter(is_active=True).values_list('id', flat=True)
    )
    allowed_dept_ids_for_form = set(form.fields['department'].queryset.values_list('id', flat=True))
    for d_id in allowed_dept_ids_for_form:
        dept_people_map[str(d_id)] = []

    links_qs = (
        PersonDepartment.objects.filter(
            department_id__in=allowed_dept_ids_for_form,
            person_id__in=visible_active_person_ids,
        )
        .select_related('person')
        .order_by('person__name')
    )
    for link in links_qs:
        key = str(link.department_id)
        dept_people_map.setdefault(key, []).append({
            'id': link.person_id,
            'name': link.person.name,
        })

    # Se estiver editando um lançamento existente cuja pessoa foi desvinculada da instância ou inativada,
    # mantém a pessoa vinculada à instância do lançamento até o momento da desvinculação
    if objective and objective.pk and objective.target_person_id and objective.department_id:
        hist_dept_key = str(objective.department_id)
        existing_list = dept_people_map.setdefault(hist_dept_key, [])
        if not any(item['id'] == objective.target_person_id for item in existing_list):
            existing_list.insert(0, {
                'id': objective.target_person_id,
                'name': f"{objective.target_person.name} (Vínculo histórico mantido na instância)",
            })

    context = {
        'form': form,
        'objective': objective,
        'categories_meta_json': json.dumps(categories_meta),
        'depts_with_children_json': json.dumps(depts_with_children),
        'dept_people_map_json': json.dumps(dept_people_map),
        'has_any_category': len(categories_meta) > 0,
    }
    return render(request, 'finance/objective_form.html', context)


@login_required
def objective_settle_view(request, pk):
    """
    Tela de Liquidação e Histórico de Pagamentos de um Objetivo Financeiro.
    """
    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = set(request.user.get_manageable_department_ids())
    has_full_access = request.user.has_full_system_access()

    objective = get_object_or_404(
        FinancialObjective.objects.select_related('category', 'department', 'target_person', 'parent_objective'),
        pk=pk,
        department_id__in=accessible_dept_ids,
    )

    can_settle = (
        request.user.has_perm('finance.add_objectivesettlement')
        and (objective.department_id in manageable_dept_ids or has_full_access)
    )

    if request.method == 'POST':
        if not can_settle:
            messages.error(request, "Você não possui permissão para registrar pagamentos nesta instância.")
            return redirect('objective_list')

        form = ObjectiveSettlementForm(
            request.POST,
            requesting_user=request.user,
            objective=objective,
        )
        if form.is_valid():
            with transaction.atomic():
                settlement = form.save(commit=False)
                settlement.objective = objective
                settlement.registered_by = request.user
                settlement.save()

                mark_settled = form.cleaned_data.get('mark_as_settled')
                objective.recalculate_settlement_status(force_settle=bool(mark_settled))

            diff = objective.total_paid - objective.target_amount
            if diff > 0:
                extra_msg = f" (Superou o objetivo em R$ {diff:.2f})"
            elif diff < 0 and objective.is_settled:
                extra_msg = f" (Quitado com valor efetivo R$ {abs(diff):.2f} abaixo do previsto)"
            else:
                extra_msg = ""

            messages.success(
                request,
                f"Pagamento efetivo de R$ {settlement.amount_paid:.2f} registrado com sucesso!{extra_msg}"
            )
            return redirect('objective_list')
    else:
        form = ObjectiveSettlementForm(
            requesting_user=request.user,
            objective=objective,
        )

    settlements = objective.settlements.filter(is_active=True).select_related('collected_by', 'registered_by').order_by('-payment_date', '-settled_at')

    context = {
        'objective': objective,
        'settlements': settlements,
        'form': form,
        'can_settle': can_settle,
    }
    return render(request, 'finance/objective_settle.html', context)


@login_required
def objective_toggle_active_view(request, pk):
    """Nada é excluído fisicamente: oculta (is_active=False) ou restaura (is_active=True) um Objetivo Financeiro."""
    if request.method == 'POST':
        manageable_dept_ids = set(request.user.get_manageable_department_ids())
        has_full_access = request.user.has_full_system_access()

        objective = get_object_or_404(
            FinancialObjective,
            pk=pk,
            department_id__in=request.user.get_accessible_department_ids(),
        )
        if objective.department_id not in manageable_dept_ids and not has_full_access:
            messages.error(request, "Você não possui permissão de gestão nesta instância.")
            return redirect('objective_list')

        objective.is_active = not objective.is_active
        if not objective.is_active:
            objective.unlinked_at = timezone.now()
            objective.save(update_fields=['is_active', 'unlinked_at'])
        else:
            objective.save(update_fields=['is_active'])

        if objective.is_active:
            messages.success(request, f"Objetivo '{objective.title}' reativado.")
        else:
            messages.warning(
                request,
                f"Objetivo '{objective.title}' deixou de estar ativo, mantendo o vínculo histórico com a instância '{objective.department.code}'."
            )
    return redirect('objective_list')


@login_required
def objective_duplicate_next_period_view(request, pk):
    """
    Duplica um objetivo Único (PONTUAL) para o período seguinte (mês subsequente),
    mantendo todos os valores, quantidades, edições, instância e pessoa vinculada
    (desde que o lançamento e a pessoa continuem ativos/vinculados à instância).
    """
    if request.method == 'POST':
        manageable_dept_ids = set(request.user.get_manageable_department_ids())
        has_full_access = request.user.has_full_system_access()

        if not request.user.has_perm('finance.add_financialobjective'):
            messages.error(request, "Você não possui permissão para lançar ou duplicar objetivos financeiros.")
            return redirect('objective_list')

        objective = get_object_or_404(
            FinancialObjective.objects.select_related('category', 'department', 'target_person'),
            pk=pk,
            department_id__in=request.user.get_accessible_department_ids(),
        )

        if objective.department_id not in manageable_dept_ids and not has_full_access:
            messages.error(request, "Você não possui permissão de gestão nesta instância para duplicar objetivos.")
            return redirect('objective_list')

        if objective.frequency != 'PONTUAL':
            messages.warning(request, "A duplicação manual para o período seguinte é exclusiva para objetivos Únicos (Pontuais).")
            return redirect('objective_list')

        if not objective.is_active:
            messages.warning(request, "Não é possível duplicar para o período seguinte um lançamento que deixou de estar ativo.")
            return redirect('objective_list')

        if objective.target_person_id:
            person_still_linked = (
                objective.target_person.is_active
                and PersonDepartment.objects.filter(
                    person_id=objective.target_person_id,
                    department_id=objective.department_id,
                ).exists()
            )
            if not person_still_linked:
                messages.error(
                    request,
                    f"Não é possível duplicar para o período seguinte: '{objective.target_person.name}' já foi desvinculado(a) ou inativado(a) na instância '{objective.department.code}'."
                )
                return redirect('objective_list')

        base_ref = objective.reference_month or objective.due_date.replace(day=1)
        next_ref_month = add_one_month(base_ref).replace(day=1)
        next_due_date = add_one_month(objective.due_date)

        with transaction.atomic():
            duplicated_obj = FinancialObjective.objects.create(
                title=objective.title,
                category=objective.category,
                frequency='PONTUAL',
                reference_month=next_ref_month,
                department=objective.department,
                parent_objective=None,
                target_person=objective.target_person,
                editions_count=objective.editions_count,
                initial_edition=objective.initial_edition,
                final_edition=objective.final_edition,
                edition_number=objective.edition_number,
                target_quantity=objective.target_quantity,
                unit_price=objective.unit_price,
                target_amount=objective.target_amount,
                due_date=next_due_date,
                notes=objective.notes,
                is_settled=False,
                is_active=True,
            )

            propagated_count = 0
            rep_level = duplicated_obj.category.replication_level
            if objective.inherited_objectives.filter(is_active=True).exists() and rep_level != 5:
                propagated_count = propagate_objective_to_descendants(
                    duplicated_obj,
                    allowed_dept_ids=manageable_dept_ids if not has_full_access else None,
                    min_replication_level=rep_level,
                )

        extra_rep = f" e replicado para {propagated_count} sub-instância(s)" if propagated_count > 0 else ""
        messages.success(
            request,
            f"Objetivo único '{duplicated_obj.title}' duplicado para o período {next_ref_month.strftime('%m/%Y')} "
            f"(vencimento em {next_due_date.strftime('%d/%m/%Y')}){extra_rep}!"
        )

    return redirect('objective_list')


@login_required
def parse_receipt_view(request):
    """
    Endpoint AJAX para ler um comprovante enviado (PDF, IMAGEM ou TXT) e/ou texto extraído no cliente
    e retornar dia e hora do pagamento, nome do responsável pelo pagamento, conta de origem e valor.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método inválido.'}, status=405)

    uploaded_file = request.FILES.get('receipt_file')
    client_text = (request.POST.get('extracted_text') or '').strip()

    backend_text, method = extract_text_from_uploaded_file(uploaded_file) if uploaded_file else ('', 'none')
    combined_text = '\n'.join(part for part in (backend_text, client_text) if part).strip()

    parsed = parse_receipt_text(combined_text)
    captured_fields = [
        k for k in ('payment_date', 'payment_time', 'payer_name', 'payer_account', 'amount')
        if parsed.get(k)
    ]

    return JsonResponse({
        'payment_date': parsed.get('payment_date', ''),
        'payment_time': parsed.get('payment_time', ''),
        'payer_name': parsed.get('payer_name', ''),
        'payer_account': parsed.get('payer_account', ''),
        'amount': parsed.get('amount', ''),
        'method': method,
        'has_text': bool(combined_text),
        'captured_count': len(captured_fields),
        'captured_all': len(captured_fields) == 5,
    })


@login_required
def settlement_list_view(request):
    """
    Tela de Liquidação de Pagamentos e Histórico Consolidado:
    1. Selecionar a Célula (d5) e a Pessoa (Militante).
    2. Inserir Comprovante de Pagamento (PDF, IMAGEM ou TXT) com leitura automática de:
       - Dia e Hora do pagamento
       - Nome do responsável pelo pagamento
       - Conta que está realizando o pagamento
       - Valor
       (Caso não seja possível capturar automaticamente, os campos devem ser preenchidos).
    3. Listar os objetivos em aberto da Célula, do Militante e dos Contribuintes sob responsabilidade do Militante,
       permitindo pagamento por quantidade e/ou valor fracionado, tag para marcar que o objetivo foi liquidado
       e campo para observações.
    """
    if not user_has_any_finance_perm(request.user):
        messages.error(request, "Você não possui permissão para acessar as Liquidações.")
        return redirect('home')

    accessible_dept_ids = request.user.get_accessible_department_ids()
    manageable_dept_ids = set(request.user.get_manageable_department_ids())
    has_full_access = request.user.has_full_system_access()
    can_register_settlement = (
        request.user.has_perm('finance.add_objectivesettlement')
        and (bool(manageable_dept_ids) or has_full_access)
    )

    # Células (d5) disponíveis para liquidação
    target_scope_ids = list(manageable_dept_ids) if manageable_dept_ids else accessible_dept_ids
    all_scope_depts = list(
        Department.objects.filter(id__in=target_scope_ids, is_active=True)
        .select_related('parent')
        .order_by('code')
    )
    cell_departments = [d for d in all_scope_depts if d.get_level() >= 5]
    if not cell_departments:
        # Fallback caso não haja nível 5 cadastrado ainda: usa instâncias folha
        parent_ids = {d.parent_id for d in all_scope_depts if d.parent_id}
        cell_departments = [d for d in all_scope_depts if d.id not in parent_ids] or all_scope_depts

    cell_ids = [c.id for c in cell_departments]

    # Pessoas ativas vinculadas a cada célula + contribuintes sob responsabilidade de cada militante
    visible_people = list(
        Person.objects.visible_to(request.user)
        .filter(is_active=True)
        .prefetch_related('groups', 'departments', 'assigned_people')
        .order_by('name')
    )
    people_by_cell_map = {str(cid): [] for cid in cell_ids}
    person_dept_links = PersonDepartment.objects.filter(
        department_id__in=cell_ids,
        person__is_active=True,
    ).select_related('person')

    person_by_id = {p.id: p for p in visible_people}
    for link in person_dept_links:
        p = person_by_id.get(link.person_id)
        if not p:
            continue
        group_names = [g.name for g in p.groups.all()]
        is_mil = GROUP_MILITANTE in group_names
        dependents = [
            {'id': dep.id, 'name': dep.name}
            for dep in p.assigned_people.all()
            if dep.is_active
        ]
        people_by_cell_map.setdefault(str(link.department_id), []).append({
            'id': p.id,
            'name': p.name,
            'is_militant': is_mil,
            'dependents': dependents,
        })

    # Ordena para exibir Militantes primeiro dentro da célula
    for cid_str, plist in people_by_cell_map.items():
        plist.sort(key=lambda item: (0 if item['is_militant'] else 1, item['name']))

    # Objetivos em aberto (is_settled=False e is_active=True) nas células acessíveis
    open_objectives_qs = (
        FinancialObjective.objects.filter(
            is_active=True,
            is_settled=False,
            department_id__in=accessible_dept_ids,
        )
        .select_related(
            'category',
            'department',
            'target_person',
            'target_person__responsible_militant',
        )
        .prefetch_related('settlements')
        .order_by('due_date', 'title')
    )

    open_objectives_data = []
    open_objectives_by_id = {}
    for obj in open_objectives_qs:
        open_objectives_by_id[obj.id] = obj
        paid_val = obj.total_paid
        rem_val = obj.remaining_amount
        paid_qty = obj.total_quantity_paid
        rem_qty = obj.remaining_quantity

        resp_militant_id = (
            obj.target_person.responsible_militant_id
            if obj.target_person and obj.target_person.responsible_militant_id
            else None
        )
        resp_militant_name = (
            obj.target_person.responsible_militant.name
            if obj.target_person and obj.target_person.responsible_militant
            else ''
        )

        open_objectives_data.append({
            'id': obj.id,
            'title': obj.title,
            'category_name': obj.category.name,
            'category_code': obj.category.code,
            'frequency_display': obj.get_frequency_display(),
            'department_id': obj.department_id,
            'department_code': obj.department.code,
            'department_name': obj.department.name,
            'target_person_id': obj.target_person_id,
            'target_person_name': obj.target_person.name if obj.target_person else '',
            'responsible_militant_id': resp_militant_id,
            'responsible_militant_name': resp_militant_name,
            'reference_month': obj.reference_month.strftime('%m/%Y') if obj.reference_month else '',
            'due_date': obj.due_date.strftime('%d/%m/%Y') if obj.due_date else '',
            'target_quantity': obj.target_quantity,
            'total_quantity_paid': paid_qty,
            'remaining_quantity': rem_qty,
            'unit_price': str(obj.unit_price) if obj.unit_price is not None else '',
            'target_amount': f"{obj.target_amount:.2f}",
            'total_paid': f"{paid_val:.2f}",
            'remaining_amount': f"{rem_val:.2f}",
            'initial_edition': obj.initial_edition,
            'final_edition': obj.final_edition,
            'edition_number': obj.edition_number or '',
        })

    # Estado inicial / preservado do formulário de liquidação
    default_cell_id = str(cell_departments[0].id) if len(cell_departments) == 1 else request.GET.get('cell_id', '')
    form_state = {
        'selected_cell_id': default_cell_id,
        'selected_person_id': request.GET.get('person_id', ''),
        'payment_date': date.today().strftime('%Y-%m-%d'),
        'payment_time': '',
        'payer_name': '',
        'payer_account': '',
        'receipt_total_amount': '',
        'receipt_reference': '',
    }

    if request.method == 'POST' and request.POST.get('settlement_batch_submit') == '1':
        if not can_register_settlement:
            messages.error(request, "Você não possui permissão para registrar liquidações de pagamentos.")
            return redirect('settlement_list')

        sel_cell_id = (request.POST.get('selected_cell_id') or '').strip()
        sel_person_id = (request.POST.get('selected_person_id') or '').strip()
        pay_date_str = (request.POST.get('payment_date') or '').strip()
        pay_time_str = (request.POST.get('payment_time') or '').strip()
        payer_name = (request.POST.get('payer_name') or '').strip()
        payer_account = (request.POST.get('payer_account') or '').strip()
        receipt_amount_str = (request.POST.get('receipt_total_amount') or '').strip().replace(',', '.')
        receipt_reference = (request.POST.get('receipt_reference') or '').strip()
        receipt_file = request.FILES.get('receipt_file')

        form_state.update({
            'selected_cell_id': sel_cell_id,
            'selected_person_id': sel_person_id,
            'payment_date': pay_date_str,
            'payment_time': pay_time_str,
            'payer_name': payer_name,
            'payer_account': payer_account,
            'receipt_total_amount': receipt_amount_str,
            'receipt_reference': receipt_reference,
        })

        errors = []
        cell_obj = None
        person_obj = None

        if not sel_cell_id.isdigit() or int(sel_cell_id) not in cell_ids:
            errors.append("Selecione uma Célula válida para realizar a liquidação.")
        else:
            cell_obj = Department.objects.filter(id=int(sel_cell_id)).first()
            if cell_obj and cell_obj.id not in manageable_dept_ids and not has_full_access:
                errors.append("Você não possui permissão de gestão na célula selecionada.")

        if not sel_person_id.isdigit():
            errors.append("Selecione a Pessoa / Militante da célula.")
        else:
            person_obj = Person.objects.filter(id=int(sel_person_id), is_active=True).first()
            if not person_obj:
                errors.append("Pessoa selecionada inválida.")
            elif cell_obj and not PersonDepartment.objects.filter(person=person_obj, department=cell_obj).exists():
                errors.append(f"A pessoa '{person_obj.name}' não está vinculada à célula '{cell_obj.code}'.")

        if not receipt_file:
            errors.append("Insira o comprovante de pagamento (PDF, IMAGEM ou TXT).")
        else:
            fname_lower = receipt_file.name.lower()
            allowed_exts = ('.pdf', '.txt', '.png', '.jpg', '.jpeg', '.webp', '.bmp')
            if not any(fname_lower.endswith(ext) for ext in allowed_exts):
                errors.append("Formato de comprovante inválido. Envie um arquivo PDF, IMAGEM (PNG/JPG/WEBP) ou TXT.")

        parsed_pay_date = None
        if not pay_date_str:
            errors.append("Informe o Dia (Data) do pagamento.")
        else:
            try:
                parsed_pay_date = datetime.strptime(pay_date_str, '%Y-%m-%d').date()
            except ValueError:
                errors.append("Data do pagamento inválida.")

        parsed_pay_time = None
        if not pay_time_str:
            errors.append("Informe a Hora do pagamento.")
        else:
            for fmt in ('%H:%M', '%H:%M:%S'):
                try:
                    parsed_pay_time = datetime.strptime(pay_time_str, fmt).time()
                    break
                except ValueError:
                    continue
            if not parsed_pay_time:
                errors.append("Hora do pagamento inválida (use o formato HH:MM).")

        if not payer_name:
            errors.append("Informe o Nome do Responsável pelo Pagamento.")

        if not payer_account:
            errors.append("Informe a Conta que está realizando o pagamento.")

        parsed_receipt_total = None
        if not receipt_amount_str:
            errors.append("Informe o Valor do comprovante de pagamento.")
        else:
            try:
                parsed_receipt_total = Decimal(receipt_amount_str)
                if parsed_receipt_total <= Decimal('0.00'):
                    errors.append("O Valor do comprovante deve ser maior que zero.")
            except (InvalidOperation, ValueError):
                errors.append("Valor do comprovante inválido.")

        # Coleta os objetivos selecionados/preenchidos para liquidação
        submitted_obj_ids = request.POST.getlist('objective_ids')
        items_to_settle = []
        for raw_oid in submitted_obj_ids:
            if not str(raw_oid).isdigit():
                continue
            oid = int(raw_oid)
            obj = open_objectives_by_id.get(oid)
            if not obj:
                continue

            raw_amt = (request.POST.get(f'obj_amount_{oid}') or '').strip().replace(',', '.')
            raw_qty = (request.POST.get(f'obj_qty_{oid}') or '').strip()
            is_marked_settled = request.POST.get(f'obj_settled_{oid}') == '1'
            item_notes = (request.POST.get(f'obj_notes_{oid}') or '').strip()

            amt_val = Decimal('0.00')
            if raw_amt:
                try:
                    amt_val = Decimal(raw_amt)
                except (InvalidOperation, ValueError):
                    errors.append(f"Valor inválido informado para o objetivo '{obj.title}'.")
                    continue

            qty_val = None
            if raw_qty:
                if raw_qty.isdigit() and int(raw_qty) > 0:
                    qty_val = int(raw_qty)
                elif raw_qty != '0':
                    errors.append(f"Quantidade inválida informada para o objetivo '{obj.title}'.")
                    continue

            if amt_val > Decimal('0.00') or is_marked_settled:
                if amt_val <= Decimal('0.00') and is_marked_settled:
                    # Se marcou como liquidado e não digitou valor fracionado, assume o saldo restante
                    amt_val = obj.remaining_amount if obj.remaining_amount > Decimal('0.00') else obj.target_amount
                items_to_settle.append({
                    'objective': obj,
                    'amount_paid': amt_val,
                    'quantity_paid': qty_val,
                    'mark_settled': is_marked_settled,
                    'notes': item_notes,
                })

        if not items_to_settle:
            errors.append(
                "Informe o valor (ou quantidade) pago ou marque a tag 'Liquidado' em pelo menos um objetivo em aberto."
            )

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            # Envia o comprovante para a pasta do Google Drive (se configurado no .env)
            prefix = f"{cell_obj.code}_{parsed_pay_date.strftime('%Y%m%d')}_{person_obj.name.split()[0]}"
            gdrive_res = upload_receipt_to_google_drive(receipt_file, filename_prefix=prefix)
            final_ref = receipt_reference
            if gdrive_res.get('success') and gdrive_res.get('web_view_link'):
                final_ref = gdrive_res['web_view_link'] if not final_ref else f"{final_ref} | {gdrive_res['web_view_link']}"
            elif gdrive_res.get('error'):
                messages.warning(
                    request,
                    f"Aviso: O comprovante foi salvo localmente, mas houve uma falha ao enviar ao Google Drive: {gdrive_res['error']}"
                )

            with transaction.atomic():
                settled_count = 0
                total_allocated = Decimal('0.00')
                for item in items_to_settle:
                    target_obj = item['objective']
                    settlement = ObjectiveSettlement.objects.create(
                        objective=target_obj,
                        amount_paid=item['amount_paid'],
                        quantity_paid=item['quantity_paid'],
                        payment_date=parsed_pay_date,
                        payment_time=parsed_pay_time,
                        payer_name=payer_name,
                        payer_account=payer_account,
                        receipt_total_amount=parsed_receipt_total,
                        receipt_file=receipt_file,
                        collected_by=person_obj,
                        registered_by=request.user,
                        receipt_reference=final_ref[:100],
                        notes=item['notes'],
                    )
                    target_obj.recalculate_settlement_status(force_settle=item['mark_settled'])
                    settled_count += 1
                    total_allocated += settlement.amount_paid

            gdrive_msg = " e enviado para o Google Drive" if gdrive_res.get('success') else ""
            messages.success(
                request,
                f"Liquidação registrada com sucesso{gdrive_msg}! {settled_count} objetivo(s) processado(s) "
                f"(Total alocado: R$ {total_allocated:.2f} | Comprovante: R$ {parsed_receipt_total:.2f})."
            )
            return redirect(f"{request.path}?cell_id={cell_obj.id}&person_id={person_obj.id}")

    month_filter = request.GET.get('mes', '').strip()
    dept_filter = request.GET.get('department', '').strip()
    search_query = request.GET.get('q', '').strip()

    settlements_qs = (
        ObjectiveSettlement.objects.filter(
            is_active=True,
            objective__department_id__in=accessible_dept_ids,
        )
        .select_related(
            'objective__category',
            'objective__department',
            'objective__target_person',
            'objective__target_person__responsible_militant',
            'collected_by',
            'registered_by',
        )
    )

    if month_filter:
        try:
            parts = month_filter.split('-')
            settlements_qs = settlements_qs.filter(
                payment_date__year=int(parts[0]),
                payment_date__month=int(parts[1]),
            )
        except (ValueError, IndexError):
            pass

    if dept_filter.isdigit() and int(dept_filter) in accessible_dept_ids:
        target_dept = Department.objects.filter(id=int(dept_filter)).first()
        if target_dept:
            sub_ids = [i for i in target_dept.get_all_descendant_ids() if i in accessible_dept_ids]
            settlements_qs = settlements_qs.filter(objective__department_id__in=sub_ids)

    if search_query:
        settlements_qs = settlements_qs.filter(
            Q(objective__title__icontains=search_query)
            | Q(objective__target_person__name__icontains=search_query)
            | Q(collected_by__name__icontains=search_query)
            | Q(payer_name__icontains=search_query)
            | Q(payer_account__icontains=search_query)
            | Q(receipt_reference__icontains=search_query)
            | Q(notes__icontains=search_query)
        )

    settlements_list = list(settlements_qs.order_by('-payment_date', '-settled_at'))
    total_paid_sum = sum((s.amount_paid for s in settlements_list), Decimal('0.00'))

    cascade_depts = build_department_cascade_list(accessible_dept_ids)

    context = {
        'settlements': settlements_list,
        'total_paid_sum': total_paid_sum,
        'cascade_depts': cascade_depts,
        'month_filter': month_filter,
        'dept_filter': int(dept_filter) if dept_filter.isdigit() else None,
        'search_query': search_query,
        'can_register_settlement': can_register_settlement,
        'cell_departments': cell_departments,
        'people_by_cell_json': json.dumps(people_by_cell_map),
        'open_objectives_json': json.dumps(open_objectives_data),
        'form_state': form_state,
    }
    return render(request, 'finance/settlement_list.html', context)
