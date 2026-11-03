# core/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Department, User, Person, PersonDepartment


class PersonDepartmentInline(admin.TabularInline):
    model = PersonDepartment
    extra = 1


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'parent', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(id__in=request.user.get_accessible_department_ids())


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_groups', 'display_departments', 'responsible_militant', 'user', 'is_active')
    list_filter = ('groups', 'is_active')
    search_fields = ('name', 'nickname', 'phone', 'email')
    filter_horizontal = ('groups',)
    inlines = [PersonDepartmentInline]

    @admin.display(description='Grupos / Perfis')
    def display_groups(self, obj):
        return ", ".join(g.name for g in obj.groups.all())

    @admin.display(description='Instâncias')
    def display_departments(self, obj):
        return ", ".join(
            f"{link.department.code} ({link.get_role_display()})"
            for link in obj.department_links.select_related('department').all()
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request).prefetch_related('department_links__department', 'groups')
        return qs.visible_to(request.user)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.sync_user_groups()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.exclude(is_superuser=True)
