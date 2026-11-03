# finance/admin.py
from django.contrib import admin
from .models import ObjectiveCategory, FinancialObjective, ObjectiveSettlement


@admin.register(ObjectiveCategory)
class ObjectiveCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category_type', 'default_unit_price', 'is_active')
    list_filter = ('category_type', 'is_active')


class SettlementInline(admin.TabularInline):
    model = ObjectiveSettlement
    extra = 1


@admin.register(FinancialObjective)
class FinancialObjectiveAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'category',
        'frequency',
        'reference_month',
        'department',
        'target_person',
        'target_amount',
        'due_date',
        'is_settled',
        'is_active',
    )
    list_filter = ('is_settled', 'frequency', 'category', 'department', 'is_active')
    search_fields = ('title', 'target_person__name', 'edition_number')
    inlines = [SettlementInline]


@admin.register(ObjectiveSettlement)
class ObjectiveSettlementAdmin(admin.ModelAdmin):
    list_display = ('objective', 'amount_paid', 'quantity_paid', 'payment_date', 'collected_by', 'registered_by')
    list_filter = ('payment_date', 'collected_by')
