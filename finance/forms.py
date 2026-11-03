# finance/forms.py
from decimal import Decimal
from datetime import date
from django import forms
from django.db.models import Q
from core.models import Department, Person, PersonDepartment, GROUP_MILITANTE
from .models import ObjectiveCategory, FinancialObjective, ObjectiveSettlement


def resolve_target_cell_departments(selected_depts, manageable_dept_ids=None):
    """
    Como todo pagamento é feito no nível da Célula (d5):
    Para cada instância selecionada (d1, d2, d3, d4 ou a própria Célula d5),
    retorna a lista de tuplas (cell_dept, origin_dept) correspondentes às Células (d5)
    subordinadas às instâncias selecionadas.
    Caso uma instância selecionada (ex: CR-SP) ainda não possua células d5 cadastradas abaixo dela,
    utiliza a própria instância selecionada para que o lançamento não se perca.
    """
    manageable_set = set(manageable_dept_ids) if manageable_dept_ids is not None else None
    resolved = []
    seen_cell_ids = set()

    for sel_dept in selected_depts:
        lvl = sel_dept.get_level()
        if lvl >= 5:
            if sel_dept.id not in seen_cell_ids:
                seen_cell_ids.add(sel_dept.id)
                resolved.append((sel_dept, None))
        else:
            desc_ids = sel_dept.get_all_descendant_ids()
            if manageable_set is not None:
                desc_ids = [i for i in desc_ids if i in manageable_set]
            desc_depts = list(
                Department.objects.filter(id__in=desc_ids, is_active=True)
                .select_related('parent')
                .order_by('code')
            )
            d5_cells = [d for d in desc_depts if d.get_level() >= 5]
            if d5_cells:
                for cell_dept in d5_cells:
                    if cell_dept.id not in seen_cell_ids:
                        seen_cell_ids.add(cell_dept.id)
                        resolved.append((cell_dept, sel_dept))
            else:
                if sel_dept.id not in seen_cell_ids:
                    seen_cell_ids.add(sel_dept.id)
                    resolved.append((sel_dept, sel_dept))

    return resolved


def get_visible_categories_for_user(user):
    """
    Retorna as Receitas (ObjectiveCategory) visíveis para o usuário com base nas instâncias que ele acessa.
    Independe de quem criou a receita: se o criador perder acesso, quem tem acesso à instância continua vendo e editando.
    """
    qs = ObjectiveCategory.objects.prefetch_related('target_departments').all().order_by('-is_active', 'name')
    if user.has_full_system_access():
        return list(qs)

    accessible_ids = set(user.get_accessible_department_ids())
    if not accessible_ids:
        return []

    visible = []
    for cat in qs:
        targets = list(cat.target_departments.all())
        if not targets:
            visible.append(cat)
            continue
        covered_ids = set()
        for t_dept in targets:
            covered_ids.update(t_dept.get_all_descendant_ids())
        if covered_ids & accessible_ids:
            visible.append(cat)
    return visible


def can_user_manage_category(user, category):
    """
    Verifica se o usuário atual pode editar/modificar uma Receita com base no seu acesso de gestão às instâncias.
    """
    if user.has_full_system_access():
        return True
    manageable_ids = set(user.get_manageable_department_ids())
    if not manageable_ids:
        return False
    user_min_lvl = user.get_highest_manageable_level()
    if category.replication_level < user_min_lvl:
        return False
    targets = list(category.target_departments.all())
    if not targets:
        return True
    target_ids = {d.id for d in targets}
    return bool(target_ids & manageable_ids)


class DepartmentReplicationChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        lvl = obj.get_level()
        if lvl >= 5:
            return f"Nível d{lvl} — {obj.code} ({obj.name} → apenas esta célula d5)"
        return f"Nível d{lvl} — {obj.code} ({obj.name} → herda automaticamente para as células d5 filhas)"


class ObjectiveCategoryForm(forms.ModelForm):
    """
    Formulário completo e personalizável de Cadastro de Receita:
    - O campo 'replication_department' permite selecionar diretamente em um único seletor
      o Nível / Instância (ex: d2 CC, d3 CR-PR, d3 CR-SP, d4 SETOR-Sind ou d5 Célula)
      e todas as células d5 filhas dessa instância herdam automaticamente a receita.
    """
    replication_department = DepartmentReplicationChoiceField(
        label="Nível que a Receita se Replicará para as Células (d5)",
        queryset=Department.objects.none(),
        required=True,
        empty_label=None,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = ObjectiveCategory
        fields = [
            'name',
            'code',
            'default_frequency',
            'use_unit_price',
            'unit_price_required',
            'default_unit_price',
            'use_quantity',
            'quantity_required',
            'default_quantity',
            'is_subscription',
            'use_editions_count',
            'editions_count_required',
            'default_editions_count',
            'use_initial_final_edition',
            'initial_final_edition_required',
            'default_initial_edition',
            'default_final_edition',
            'person_required',
            'use_notes',
            'notes_required',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Assinatura Semestral, Jornal Avulso, Revista, Rifa...',
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: ASSIN-SEM, JORNAL, REVISTA, RIFA',
            }),
            'default_frequency': forms.Select(attrs={'class': 'form-select'}),
            'use_unit_price': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'unit_price_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'default_unit_price': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'min': '0',
                'placeholder': '0,00',
            }),
            'use_quantity': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'quantity_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'default_quantity': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': '1',
                'placeholder': 'Ex: 10',
            }),
            'is_subscription': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'use_editions_count': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'editions_count_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'default_editions_count': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': '1',
                'placeholder': 'Ex: 12',
            }),
            'use_initial_final_edition': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'initial_final_edition_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'default_initial_edition': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': '1',
                'placeholder': 'Ex: 950',
            }),
            'default_final_edition': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': '1',
                'placeholder': 'Ex: 962',
            }),
            'person_required': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'use_notes': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'notes_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.requesting_user = requesting_user

        if requesting_user is not None:
            manageable_ids = requesting_user.get_manageable_department_ids()
            depts = list(
                Department.objects.filter(id__in=manageable_ids, is_active=True)
                .select_related('parent')
            )
            # Ordena do nível mais alto (d1/d2) até d5, e alfabeticamente por sigla
            depts.sort(key=lambda d: (d.get_level(), d.code))
            ordered_ids = [d.id for d in depts]
            # Preserva a ordem por nível nas escolhas do seletor
            self.fields['replication_department'].queryset = Department.objects.filter(
                id__in=ordered_ids, is_active=True
            ).select_related('parent')
            self.fields['replication_department'].choices = [
                (d.id, self.fields['replication_department'].label_from_instance(d))
                for d in depts
            ]

            if self.instance and self.instance.pk:
                existing_target = self.instance.target_departments.first()
                if existing_target:
                    self.fields['replication_department'].initial = existing_target.id
            elif not self.is_bound and depts:
                # Sugere como padrão a instância de nível d2 (CC) se o usuário for admin/d2, ou a primeira instância do seu nível
                d2_dept = next((d for d in depts if d.get_level() == 2), depts[0])
                self.fields['replication_department'].initial = d2_dept.id

    def clean(self):
        cleaned_data = super().clean()
        selected_dept = cleaned_data.get('replication_department')

        if self.requesting_user is not None and selected_dept is not None:
            min_allowed_level = self.requesting_user.get_highest_manageable_level()
            manageable_ids = set(self.requesting_user.get_manageable_department_ids())
            lvl = selected_dept.get_level()
            if selected_dept.id not in manageable_ids or lvl < min_allowed_level:
                self.add_error(
                    'replication_department',
                    f"Você não possui permissão para configurar replicação na instância '{selected_dept.code}'."
                )
            else:
                cleaned_data['replication_level'] = lvl
                cleaned_data['target_departments'] = [selected_dept]

        return cleaned_data


class FinancialObjectiveForm(forms.ModelForm):
    """
    Formulário para lançamento e edição de Objetivos Financeiros:
    - Todo lançamento e pagamento é feito na Célula (d5).
    - As células abaixo da instância configurada na Receita herdam automaticamente
      a permissão de usar aquela Receita (sem precisar selecionar células manualmente na receita).
    """
    reference_month_input = forms.CharField(
        label="Período / Ciclo Mensal (Mês/Ano)",
        required=True,
        widget=forms.TextInput(attrs={
            'type': 'month',
            'class': 'form-control',
        }),
    )

    class Meta:
        model = FinancialObjective
        fields = [
            'category',
            'title',
            'frequency',
            'department',
            'target_person',
            'editions_count',
            'initial_edition',
            'final_edition',
            'edition_number',
            'target_quantity',
            'unit_price',
            'target_amount',
            'due_date',
            'notes',
            'is_active',
        ]
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Opcional: descrição complementar (se vazio, usa o nome da receita)',
            }),
            'frequency': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'target_person': forms.Select(attrs={'class': 'form-select'}),
            'editions_count': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Qtd de edições',
            }),
            'initial_edition': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Ex: 950',
            }),
            'final_edition': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Ex: 962',
            }),
            'edition_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Edição 952',
            }),
            'target_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Quantidade',
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0,00',
            }),
            'target_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0,00',
            }),
            'due_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Observações adicionais...',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.requesting_user = requesting_user
        if requesting_user is not None:
            visible_cat_ids = [c.id for c in get_visible_categories_for_user(requesting_user) if c.is_active]
            if self.instance and self.instance.pk and self.instance.category_id:
                visible_cat_ids.append(self.instance.category_id)
            self.fields['category'].queryset = ObjectiveCategory.objects.filter(id__in=visible_cat_ids).order_by('name')
        else:
            self.fields['category'].queryset = ObjectiveCategory.objects.filter(is_active=True).order_by('name')

        self.fields['category'].empty_label = "Selecione a Receita cadastrada..."
        self.fields['title'].required = False
        self.fields['target_amount'].required = False

        if requesting_user is not None:
            manageable_ids = requesting_user.get_manageable_department_ids()
            accessible_ids = requesting_user.get_accessible_department_ids()

            all_manageable_depts = list(
                Department.objects.filter(id__in=manageable_ids, is_active=True)
                .select_related('parent')
                .order_by('code')
            )
            # Todo pagamento ocorre na Célula (d5): lista as Células (d5) que o usuário tem acesso de gestão
            d5_cell_ids = [d.id for d in all_manageable_depts if d.get_level() >= 5]
            if not d5_cell_ids:
                d5_cell_ids = [d.id for d in all_manageable_depts]

            dept_q = Q(id__in=d5_cell_ids, is_active=True)
            if self.instance and self.instance.pk and self.instance.department_id:
                dept_q |= Q(id=self.instance.department_id)
            dept_qs = Department.objects.filter(dept_q).select_related('parent').order_by('code')
            self.fields['department'].queryset = dept_qs
            self.fields['department'].empty_label = "Selecione a Célula (d5)..."

            # Se o usuário tiver acesso de gestão a apenas 1 célula (ex: Secretário de Célula), pré-seleciona automaticamente
            if not (self.instance and self.instance.pk) and not self.is_bound and len(d5_cell_ids) == 1:
                self.fields['department'].initial = d5_cell_ids[0]

            base_visible_people = Person.objects.visible_to(requesting_user)
            if requesting_user.has_full_system_access():
                active_people_q = Q(is_active=True)
            else:
                active_people_q = Q(is_active=True, departments__id__in=accessible_ids)

            if self.instance and self.instance.pk and self.instance.target_person_id:
                # Preserva a pessoa vinculada ao objetivo mesmo se ela tiver sido inativada ou desvinculada da instância posteriormente
                active_people_q |= Q(id=self.instance.target_person_id)

            self.fields['target_person'].queryset = (
                base_visible_people.filter(active_people_q).distinct().order_by('name')
            )
            self.fields['target_person'].empty_label = "— Meta Geral da Célula (Sem pessoa específica) —"

        if self.instance and self.instance.pk:
            ref_date = self.instance.reference_month or self.instance.due_date
            if ref_date:
                self.fields['reference_month_input'].initial = ref_date.strftime('%Y-%m')
        else:
            today = date.today()
            self.fields['reference_month_input'].initial = today.strftime('%Y-%m')
            if not self.initial.get('due_date'):
                self.fields['due_date'].initial = today.strftime('%Y-%m-%d')

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        editions_count = cleaned_data.get('editions_count')
        initial_edition = cleaned_data.get('initial_edition')
        final_edition = cleaned_data.get('final_edition')
        target_quantity = cleaned_data.get('target_quantity')
        unit_price = cleaned_data.get('unit_price')
        target_amount = cleaned_data.get('target_amount')
        target_person = cleaned_data.get('target_person')
        department = cleaned_data.get('department')
        ref_month_str = (cleaned_data.get('reference_month_input') or '').strip()

        if category and department:
            is_preserved_cat = (
                self.instance
                and self.instance.pk
                and self.instance.category_id == category.id
                and self.instance.department_id == department.id
            )
            if not category.is_available_for_department(department) and not is_preserved_cat:
                self.add_error(
                    'category',
                    f"A célula '{department.code} - {department.name}' não herdou permissão para utilizar a receita '{category.name}'."
                )

        if department and target_person:
            is_currently_linked = PersonDepartment.objects.filter(
                person=target_person,
                department=department,
            ).exists()
            is_preserved_historical_link = (
                self.instance
                and self.instance.pk
                and self.instance.department_id == department.id
                and self.instance.target_person_id == target_person.id
            )
            if not is_currently_linked and not is_preserved_historical_link:
                self.add_error(
                    'target_person',
                    f"A pessoa '{target_person.name}' não está vinculada à instância '{department.code} - {department.name}'."
                )

        if ref_month_str:
            try:
                parts = ref_month_str.split('-')
                cleaned_data['reference_month'] = date(int(parts[0]), int(parts[1]), 1)
            except (ValueError, IndexError):
                self.add_error('reference_month_input', 'Informe um mês/ano válido no formato AAAA-MM.')

        # Valida obrigatoriedades personalizadas definidas no cadastro da Receita
        if category:
            if not cleaned_data.get('title'):
                cleaned_data['title'] = category.name

            if category.use_unit_price and category.unit_price_required and not unit_price:
                self.add_error('unit_price', f"A receita '{category.name}' exige o preenchimento do Valor Unitário.")

            if category.use_quantity and category.quantity_required and not target_quantity:
                self.add_error('target_quantity', f"A receita '{category.name}' exige o preenchimento da Quantidade.")

            if category.use_editions_count and category.editions_count_required and not editions_count:
                self.add_error('editions_count', f"A receita '{category.name}' exige a Quantidade de Edições.")

            if category.use_initial_final_edition and category.initial_final_edition_required:
                if not initial_edition:
                    self.add_error('initial_edition', f"A receita '{category.name}' exige a Edição Inicial.")
                if not final_edition:
                    self.add_error('final_edition', f"A receita '{category.name}' exige a Edição Final.")

            if initial_edition and final_edition and final_edition < initial_edition:
                self.add_error('final_edition', 'A Edição Final deve ser maior ou igual à Edição Inicial.')

            if category.person_required and not target_person:
                self.add_error('target_person', f"A receita '{category.name}' exige selecionar uma Pessoa Vinculada.")

            notes_val = (cleaned_data.get('notes') or '').strip()
            if category.use_notes and category.notes_required and not notes_val:
                self.add_error('notes', f"A receita '{category.name}' exige o preenchimento do campo Observação.")

        # Cálculo automático de valor total se informou quantidade e valor unitário
        if target_quantity and unit_price:
            calculated = Decimal(target_quantity) * unit_price
            if not target_amount:
                cleaned_data['target_amount'] = calculated
        elif unit_price and not target_quantity and not target_amount:
            cleaned_data['target_amount'] = unit_price

        if not cleaned_data.get('target_amount') or cleaned_data.get('target_amount') <= 0:
            self.add_error('target_amount', 'Informe o Valor Objetivo Total maior que zero.')

        return cleaned_data


class ObjectiveSettlementForm(forms.ModelForm):
    """
    Formulário para registrar o Pagamento Efetivo de um Objetivo:
    - Permite registrar valor efetivo igual, inferior ou superior ao valor esperado do objetivo.
    """
    mark_as_settled = forms.BooleanField(
        label="Concluir / Marcar objetivo como Quitado com este pagamento efetivo",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
    )

    class Meta:
        model = ObjectiveSettlement
        fields = ['amount_paid', 'quantity_paid', 'payment_date', 'collected_by', 'receipt_reference']
        widgets = {
            'amount_paid': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg fw-bold text-success',
                'step': '0.01',
                'min': '0.01',
                'placeholder': '0,00',
            }),
            'quantity_paid': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Opcional: qtd paga',
            }),
            'payment_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'collected_by': forms.Select(attrs={'class': 'form-select'}),
            'receipt_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Pix, Dinheiro, Recibo nº 102...',
            }),
        }

    def __init__(self, *args, requesting_user=None, objective=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.objective = objective

        if not self.initial.get('payment_date'):
            self.fields['payment_date'].initial = date.today().strftime('%Y-%m-%d')

        if objective and not self.is_bound:
            remaining = objective.target_amount - objective.total_paid
            default_val = remaining if remaining > 0 else objective.target_amount
            self.fields['amount_paid'].initial = default_val
            if objective.target_quantity:
                self.fields['quantity_paid'].initial = objective.target_quantity
            if objective.target_person and objective.target_person.responsible_militant_id:
                self.fields['collected_by'].initial = objective.target_person.responsible_militant_id
            elif objective.target_person and objective.target_person.is_militante:
                self.fields['collected_by'].initial = objective.target_person_id

        if requesting_user is not None:
            accessible_ids = requesting_user.get_accessible_department_ids()
            militant_qs = Person.objects.visible_to(requesting_user).filter(
                groups__name=GROUP_MILITANTE, is_active=True
            )
            if not requesting_user.has_full_system_access():
                militant_qs = militant_qs.filter(departments__id__in=accessible_ids)
            self.fields['collected_by'].queryset = militant_qs.distinct().order_by('name')
            self.fields['collected_by'].empty_label = "Selecione o militante que recolheu..."
