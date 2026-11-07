from django.contrib import admin

from .models import Pagamento, Parcela
from .services import anotacao_pago


class HistoricoAdmin(admin.ModelAdmin):
    """Consultation only. Financial writes are available through the API services."""

    list_per_page = 25
    actions = None
    exclude = ("requisicao_hash",)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Parcela)
class ParcelaAdmin(HistoricoAdmin):
    list_display = ("id", "cliente", "venda", "numero", "valor_original", "valor_pago", "saldo_restante", "vencimento", "status")
    list_filter = ("vencimento", "venda__status")
    search_fields = ("venda__cliente__nome", "venda__cliente__cpf")
    list_select_related = ("venda__cliente",)
    exclude = ()

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(**anotacao_pago())

    def get_readonly_fields(self, request, obj=None):
        return super().get_readonly_fields(request, obj) + ("valor_pago", "saldo_restante", "status", "data_quitacao")

    @admin.display(description="cliente")
    def cliente(self, obj):
        return obj.venda.cliente


@admin.register(Pagamento)
class PagamentoAdmin(HistoricoAdmin):
    list_display = ("id", "cliente", "venda", "parcela", "tipo", "valor", "forma_pagamento", "data_pagamento", "responsavel", "status")
    list_filter = ("tipo", "status", "forma_pagamento", "data_pagamento")
    search_fields = ("venda__cliente__nome", "venda__cliente__cpf")
    list_select_related = ("venda__cliente", "parcela", "responsavel")

    @admin.display(description="cliente")
    def cliente(self, obj):
        return obj.venda.cliente
