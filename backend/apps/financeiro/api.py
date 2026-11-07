from django.core.exceptions import ValidationError as DomainValidationError
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated


class FinanceiroPagination(PageNumberPagination):
    page_size = 25


class FinanceiroAPIMixin:
    permission_classes = [IsAuthenticated]
    pagination_class = FinanceiroPagination


class EntradaEstritaSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({field: "Campo não permitido nesta operação." for field in sorted(unknown)})
        return super().to_internal_value(data)


def executar_servico(service, **kwargs):
    try:
        return service(**kwargs)
    except DomainValidationError as exc:
        raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages})


class MotivoSerializer(EntradaEstritaSerializer):
    motivo = serializers.CharField(allow_blank=False)


class FiltrosSerializer(serializers.Serializer):
    cliente = serializers.IntegerField(min_value=1, required=False)
    venda = serializers.IntegerField(min_value=1, required=False)
    parcela = serializers.IntegerField(min_value=1, required=False)
    status = serializers.CharField(required=False)
    tipo = serializers.ChoiceField(choices=["entrada", "parcela"], required=False)
    venda_status = serializers.ChoiceField(choices=["ativa", "cancelada"], required=False)
    data_inicio = serializers.DateField(required=False)
    data_fim = serializers.DateField(required=False)
    vencimento_inicio = serializers.DateField(required=False)
    vencimento_fim = serializers.DateField(required=False)

    def validate(self, attrs):
        for inicio, fim in (("data_inicio", "data_fim"), ("vencimento_inicio", "vencimento_fim")):
            if inicio in attrs and fim in attrs and attrs[inicio] > attrs[fim]:
                raise serializers.ValidationError({fim: "A data final deve ser igual ou posterior à inicial."})
        return attrs


def filtros(query_params):
    serializer = FiltrosSerializer(data=query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def filtrar_status(qs, value, choices):
    if value is None:
        return qs
    if value not in choices:
        raise serializers.ValidationError({"status": "Situação inválida."})
    return qs.filter(status=value)
