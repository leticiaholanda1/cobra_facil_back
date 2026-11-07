from decimal import Decimal

from rest_framework import serializers

from .api import EntradaEstritaSerializer
from .models import Pagamento, Parcela


class ParcelaSerializer(serializers.ModelSerializer):
    valor_pago = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    saldo_restante = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    status = serializers.CharField(read_only=True)
    data_quitacao = serializers.DateTimeField(read_only=True)
    cliente = serializers.IntegerField(source="venda.cliente_id", read_only=True)
    venda_status = serializers.CharField(source="venda.status", read_only=True)

    class Meta:
        model = Parcela
        fields = ("id", "venda", "cliente", "venda_status", "numero", "vencimento", "valor_original", "valor_pago", "saldo_restante", "status", "data_quitacao", "criado_em")
        read_only_fields = fields


class PagamentoSerializer(serializers.ModelSerializer):
    cliente = serializers.IntegerField(source="venda.cliente_id", read_only=True)

    class Meta:
        model = Pagamento
        fields = ("id", "venda", "cliente", "parcela", "tipo", "valor", "data_pagamento", "forma_pagamento", "observacoes", "responsavel", "chave_idempotencia", "status", "estornado_em", "estornado_por", "motivo_estorno", "criado_em")
        read_only_fields = fields


class PagamentoCreateSerializer(EntradaEstritaSerializer):
    parcela = serializers.IntegerField(min_value=1)
    valor = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    forma_pagamento = serializers.ChoiceField(choices=Pagamento.Forma.choices)
    chave_idempotencia = serializers.UUIDField()
    data_pagamento = serializers.DateTimeField(required=False)
    observacoes = serializers.CharField(required=False, allow_blank=True, default="")


class ResumoFinanceiroSerializer(serializers.Serializer):
    total_compras = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_entradas_recebidas = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_pago_parcelas = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_efetivamente_pago = serializers.DecimalField(max_digits=20, decimal_places=2)
    saldo_devedor = serializers.DecimalField(max_digits=20, decimal_places=2)
    saldo_entrada_estornada = serializers.DecimalField(max_digits=20, decimal_places=2)
    parcelas_pendentes = serializers.IntegerField()
    parcelas_vencidas = serializers.IntegerField()
    parcelas_quitadas = serializers.IntegerField()
