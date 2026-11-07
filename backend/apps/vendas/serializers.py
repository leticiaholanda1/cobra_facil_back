from decimal import Decimal

from rest_framework import serializers

from apps.financeiro.api import EntradaEstritaSerializer
from apps.financeiro.models import Pagamento
from apps.financeiro.serializers import ParcelaSerializer

from .models import ItemVenda, Venda


class ItemVendaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemVenda
        fields = ("id", "descricao", "quantidade", "valor_unitario", "valor_total", "observacoes")
        read_only_fields = fields


class VendaSerializer(serializers.ModelSerializer):
    itens = ItemVendaSerializer(many=True, read_only=True)
    parcelas = ParcelaSerializer(many=True, read_only=True)

    class Meta:
        model = Venda
        fields = ("id", "cliente", "data_venda", "valor_total", "valor_entrada", "valor_financiado", "quantidade_parcelas", "primeiro_vencimento", "observacoes", "status", "responsavel", "chave_idempotencia", "cancelada_em", "cancelada_por", "motivo_cancelamento", "criado_em", "atualizado_em", "itens", "parcelas")
        read_only_fields = fields


class ItemVendaCreateSerializer(EntradaEstritaSerializer):
    descricao = serializers.CharField(max_length=255)
    quantidade = serializers.IntegerField(min_value=1, max_value=2147483647)
    valor_unitario = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    observacoes = serializers.CharField(required=False, allow_blank=True, default="")


class VendaCreateSerializer(EntradaEstritaSerializer):
    cliente = serializers.IntegerField(min_value=1)
    itens = ItemVendaCreateSerializer(many=True, allow_empty=False)
    valor_total = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False)
    valor_entrada = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    quantidade_parcelas = serializers.IntegerField(min_value=0, max_value=1200)
    primeiro_vencimento = serializers.DateField(required=False, allow_null=True)
    forma_entrada = serializers.ChoiceField(choices=Pagamento.Forma.choices, required=False, allow_null=True)
    chave_idempotencia = serializers.UUIDField()
    data_venda = serializers.DateField(required=False)
    observacoes = serializers.CharField(required=False, allow_blank=True, default="")
