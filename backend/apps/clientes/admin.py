from django.contrib import admin

from .forms import ClienteAdminForm
from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    form = ClienteAdminForm
    list_display = ("nome", "cpf", "telefone", "cidade", "estado", "ativo", "criado_em")
    search_fields = ("nome", "cpf", "telefone")
    list_filter = ("ativo", "estado", "criado_em")
    ordering = ("nome", "id")
    list_per_page = 25
    readonly_fields = ("criado_em", "atualizado_em")
    fieldsets = (
        ("Identificação", {"fields": ("nome", "cpf", "ativo")}),
        ("Contato", {"fields": ("telefone", "whatsapp", "email")}),
        ("Endereço", {"fields": (
            "cep", "logradouro", "numero", "complemento", "bairro", "cidade", "estado",
        )}),
        ("Observações", {"fields": ("observacoes",)}),
        ("Datas", {"fields": ("criado_em", "atualizado_em")}),
    )

    def has_delete_permission(self, request, obj=None):
        return False
