# Diretrizes Técnicas - OCI Finance

1. Stack: Python 3, Django, PostgreSQL remoto, Bootstrap 5 (CDN).
2. Modelo de Usuário: Customizado (`core.User`), herdando de `AbstractUser` e vinculado a `Department`.
3. Hierarquia Departamental:
   - Máximo estrito de 4 níveis.
   - Todo usuário só pode enxergar dados do seu próprio departamento e de seus descendentes diretos/indiretos.
   - Qualquer view de listagem ou relatório financeiro DEVE filtrar por `department_id__in=request.user.get_accessible_department_ids()`.
4. Segurança: Nunca use consultas abertas (`.objects.all()`) em modelos financeiros sem filtrar pelo escopo hierárquico.
5. Padrão de Templates: Todos os templates devem estender `templates/base.html` e usar componentes do Bootstrap 5.