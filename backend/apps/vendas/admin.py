from django.contrib import admin

from apps.financeiro.admin import HistoricoAdmin
from apps.financeiro.models import Parcela

from .models import ItemVenda, Venda


class HistoricoInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ItemVendaInline(HistoricoInline):
    model = ItemVenda
    fields = ("descricao", "quantidade", "valor_unitario", "valor_total", "observacoes")
    readonly_fields = fields
    show_change_link = False


class ParcelaInline(HistoricoInline):
    model = Parcela
    fields = ("numero", "vencimento", "valor_original", "valor_pago", "saldo_restante", "status")
    readonly_fields = fields


@admin.register(Venda)
class VendaAdmin(HistoricoAdmin):
    list_display = ("id", "cliente", "data_venda", "valor_total", "valor_entrada", "valor_financiado", "status")
    list_filter = ("status", "data_venda")
    search_fields = ("cliente__nome", "cliente__cpf")
    list_select_related = ("cliente",)
    inlines = (ItemVendaInline, ParcelaInline)
