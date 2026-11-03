# finance/models.py
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from core.models import Department, Person, GROUP_MILITANTE


class ObjectiveCategory(models.Model):
    """
    Cadastro Personalizável de Receita:
    Permite configurar para qualquer tipo de receita (Assinaturas, Jornais, Revistas, Rifas, Contribuições, etc.):
    - Nome, Sigla e Periodicidade padrão (Único ou Mensal)
    - Valor Unitário (se utiliza, valor padrão e se é obrigatório)
    - Quantidade de itens/exemplares (se utiliza, quantidade padrão e se é obrigatória)
    - Assinatura / Edições (se é assinatura, quantidade de edições, edição inicial e final e se são obrigatórios)
    - Nível de Replicação nas Instâncias Inferiores (nunca superior ao nível de acesso do usuário)
    """
    FREQUENCY_CHOICES = (
        ('PONTUAL', 'Único (Pontual)'),
        ('MENSAL', 'Mensal (Ciclo Mensal)'),
    )

    REPLICATION_LEVEL_CHOICES = (
        (1, 'Nível d1 (Administração Geral → replica para todas as Células d5)'),
        (2, 'Nível d2 (Comitê Central → replica para todas as Células d5)'),
        (3, 'Nível d3 (Comitê Regional → selecionar CR(s) para replicar às Células d5)'),
        (4, 'Nível d4 (Setor → selecionar Setor(es) para replicar às Células d5)'),
        (5, 'Nível d5 (Célula → apenas para a(s) Célula(s) selecionada(s))'),
    )

    name = models.CharField("Nome da Receita", max_length=120, unique=True)
    code = models.CharField("Sigla / Código", max_length=30, unique=True)
    default_frequency = models.CharField(
        "Periodicidade da Receita",
        max_length=15,
        choices=FREQUENCY_CHOICES,
        default='MENSAL',
    )

    # Configuração de Valor Unitário
    use_unit_price = models.BooleanField("Utilizar campo Valor Unitário", default=True)
    unit_price_required = models.BooleanField("Valor Unitário é obrigatório?", default=False)
    default_unit_price = models.DecimalField(
        "Valor Unitário Padrão (R$)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Configuração de Quantidade
    use_quantity = models.BooleanField("Utilizar campo Quantidade", default=False)
    quantity_required = models.BooleanField("Quantidade é obrigatória?", default=False)
    default_quantity = models.PositiveIntegerField(
        "Quantidade Padrão",
        null=True,
        blank=True,
    )

    # Configuração de Assinatura e Edições
    is_subscription = models.BooleanField("É uma Assinatura?", default=False)
    use_editions_count = models.BooleanField("Utilizar Quantidade de Edições", default=False)
    editions_count_required = models.BooleanField("Quantidade de Edições é obrigatória?", default=False)
    default_editions_count = models.PositiveIntegerField(
        "Quantidade de Edições Padrão",
        null=True,
        blank=True,
    )

    use_initial_final_edition = models.BooleanField("Utilizar Edição Inicial e Edição Final", default=False)
    initial_final_edition_required = models.BooleanField("Edição Inicial e Final são obrigatórias?", default=False)
    default_initial_edition = models.PositiveIntegerField("Edição Inicial Padrão", null=True, blank=True)
    default_final_edition = models.PositiveIntegerField("Edição Final Padrão", null=True, blank=True)

    # Configuração de Pessoa Vinculada
    person_required = models.BooleanField("Pessoa Vinculada é obrigatória?", default=False)

    # Nível em que a receita se replica para as Células (d5) inferiores (nunca superior ao nível do usuário)
    replication_level = models.PositiveSmallIntegerField(
        "Nível de Replicação para as Células (d5)",
        choices=REPLICATION_LEVEL_CHOICES,
        default=5,
        help_text="Define o nível hierárquico a partir do qual esta receita será replicada para as Células (d5) subordinadas."
    )
    target_departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name='revenue_categories',
        verbose_name="Instâncias Selecionadas para Replicação",
        help_text="Instâncias do nível selecionado cujas Células (d5) subordinadas terão este lançamento."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criado originalmente por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_revenue_categories',
    )

    # Configuração de Observação no lançamento da receita
    use_notes = models.BooleanField("Utilizar campo Observação", default=False)
    notes_required = models.BooleanField("Observação é obrigatória?", default=False)

    # Mantido para retrocompatibilidade interna
    category_type = models.CharField(max_length=20, default='CUSTOM', blank=True)
    is_active = models.BooleanField("Ativa (Visível)", default=True)

    def get_inherited_department_ids(self):
        """
        Retorna todos os IDs de instâncias (incluindo todas as Células d5 subordinadas)
        que herdam automaticamente a permissão de usar esta receita.
        """
        targets = list(self.target_departments.all())
        if not targets:
            return set(Department.objects.filter(is_active=True).values_list('id', flat=True))
        inherited_ids = set()
        for t_dept in targets:
            inherited_ids.update(t_dept.get_all_descendant_ids())
        return inherited_ids

    def is_available_for_department(self, dept):
        """Verifica se a instância/célula (d5) herdou a permissão de usar esta receita."""
        if not dept:
            return False
        return dept.id in self.get_inherited_department_ids()

    def get_origin_for_department(self, dept):
        """Retorna a instância de origem (ex: CC, CR-PR, SETOR-Sind) da qual a célula herdou esta receita."""
        if not dept:
            return None
        for t_dept in self.target_departments.all():
            if dept.id in t_dept.get_all_descendant_ids():
                return t_dept
        return None

    def __str__(self):
        return f"{self.code} - {self.name}"


class FinancialObjective(models.Model):
    """
    Camada 1: Objetivos Financeiros (Únicos ou Mensais, com ciclo mensal).
    Os campos exigidos e exibidos são governados pela Receita (ObjectiveCategory) escolhida.
    """
    FREQUENCY_CHOICES = (
        ('PONTUAL', 'Único (Pontual)'),
        ('MENSAL', 'Mensal (Ciclo Mensal)'),
    )

    title = models.CharField(
        "Descrição / Identificação do Lançamento",
        max_length=200,
        help_text="Se deixado em branco, assume automaticamente o nome da Receita."
    )
    category = models.ForeignKey(
        ObjectiveCategory,
        verbose_name="Receita",
        on_delete=models.PROTECT,
        related_name='objectives'
    )
    frequency = models.CharField(
        "Periodicidade",
        max_length=15,
        choices=FREQUENCY_CHOICES,
        default='MENSAL'
    )
    reference_month = models.DateField(
        "Mês de Referência (Ciclo Mensal)",
        null=True,
        blank=True,
    )

    department = models.ForeignKey(
        Department,
        verbose_name="Célula / Instância do Lançamento",
        on_delete=models.CASCADE,
        related_name='financial_objectives',
    )

    origin_department = models.ForeignKey(
        Department,
        verbose_name="Instância de Origem (Replicação)",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originated_objectives',
    )

    parent_objective = models.ForeignKey(
        'self',
        verbose_name="Objetivo de Origem (Instância Superior)",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inherited_objectives',
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criado originalmente por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_financial_objectives',
    )

    target_person = models.ForeignKey(
        Person,
        verbose_name="Pessoa Vinculada",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='financial_objectives',
    )

    # Campos de Edições / Assinaturas
    editions_count = models.PositiveIntegerField(
        "Quantidade de Edições",
        null=True,
        blank=True,
    )
    initial_edition = models.PositiveIntegerField(
        "Edição Inicial",
        null=True,
        blank=True,
    )
    final_edition = models.PositiveIntegerField(
        "Edição Final",
        null=True,
        blank=True,
    )
    edition_number = models.CharField(
        "Nº / Identificação da Edição",
        max_length=50,
        blank=True,
    )

    # Campos de Quantidade e Valor Unitário
    target_quantity = models.PositiveIntegerField(
        "Quantidade",
        null=True,
        blank=True,
    )
    unit_price = models.DecimalField(
        "Valor Unitário (R$)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    target_amount = models.DecimalField(
        "Valor Objetivo Total (R$)",
        max_digits=12,
        decimal_places=2,
    )
    due_date = models.DateField("Data de Vencimento")
    is_settled = models.BooleanField("Quitado / Liquidado", default=False)
    is_active = models.BooleanField("Ativo (Visível)", default=True)
    unlinked_at = models.DateTimeField(
        "Desvinculado / Inativado em",
        null=True,
        blank=True,
        help_text="Registra o momento em que o lançamento deixou de estar ativo ou a pessoa foi desvinculada da instância, mantendo o vínculo histórico."
    )

    notes = models.TextField("Observações", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.title and self.category_id:
            self.title = self.category.name
        if self.target_quantity and self.unit_price and not self.target_amount:
            self.target_amount = Decimal(self.target_quantity) * self.unit_price
        if self.due_date and not self.reference_month:
            self.reference_month = self.due_date.replace(day=1)
        if not self.is_active and not self.unlinked_at:
            self.unlinked_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def total_paid(self):
        val = self.settlements.filter(is_active=True).aggregate(total=models.Sum('amount_paid'))['total']
        return val or Decimal('0.00')

    @property
    def total_quantity_paid(self):
        val = self.settlements.filter(is_active=True).aggregate(total=models.Sum('quantity_paid'))['total']
        return int(val or 0)

    @property
    def remaining_amount(self):
        rem = self.target_amount - self.total_paid
        return rem if rem > Decimal('0.00') else Decimal('0.00')

    @property
    def remaining_quantity(self):
        if not self.target_quantity:
            return None
        rem = int(self.target_quantity) - self.total_quantity_paid
        return rem if rem > 0 else 0

    @property
    def difference_amount(self):
        return self.total_paid - self.target_amount

    def recalculate_settlement_status(self, force_settle=None):
        if force_settle is True:
            self.is_settled = True
        elif force_settle is False:
            self.is_settled = False
        else:
            if self.total_paid >= self.target_amount:
                self.is_settled = True
        self.save(update_fields=['is_settled'])

    def __str__(self):
        status_txt = "Quitado" if self.is_settled else "Pendente"
        person_txt = f" - {self.target_person.name}" if self.target_person else f" - [{self.department.code}]"
        return f"[{status_txt}] {self.title}{person_txt} (R$ {self.target_amount})"


class ObjectiveSettlement(models.Model):
    """
    Camada 2: Liquidação / Registro do Pagamento Efetivo Realizado.
    """
    objective = models.ForeignKey(
        FinancialObjective,
        verbose_name="Objetivo Financeiro",
        on_delete=models.CASCADE,
        related_name='settlements',
    )

    amount_paid = models.DecimalField(
        "Valor Efetivo do Pagamento (R$)",
        max_digits=12,
        decimal_places=2,
    )
    quantity_paid = models.PositiveIntegerField(
        "Quantidade Paga / Vendida",
        null=True,
        blank=True,
    )
    payment_date = models.DateField("Data do Pagamento")
    payment_time = models.TimeField("Hora do Pagamento", null=True, blank=True)

    payer_name = models.CharField(
        "Nome do Responsável pelo Pagamento",
        max_length=200,
        blank=True,
    )
    payer_account = models.CharField(
        "Conta que realizou o Pagamento",
        max_length=200,
        blank=True,
    )
    receipt_total_amount = models.DecimalField(
        "Valor Total do Comprovante (R$)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    receipt_file = models.FileField(
        "Comprovante de Pagamento (PDF, Imagem ou TXT)",
        upload_to='comprovantes/%Y/%m/',
        null=True,
        blank=True,
    )

    collected_by = models.ForeignKey(
        Person,
        verbose_name="Centralizado / Recolhido por (Militante)",
        on_delete=models.PROTECT,
        related_name='collected_settlements',
    )

    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Registrado por",
        on_delete=models.PROTECT,
    )

    receipt_reference = models.CharField(
        "Comprovante / Referência",
        max_length=100,
        blank=True,
    )
    notes = models.TextField("Observações", blank=True)
    settled_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField("Ativo", default=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.objective.recalculate_settlement_status()

    def __str__(self):
        return f"Pagamento Efetivo R$ {self.amount_paid} para {self.objective.title}"
