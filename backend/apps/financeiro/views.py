from django.db.models import F
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .api import FinanceiroAPIMixin, MotivoSerializer, executar_servico, filtros, filtrar_status
from .models import Pagamento, Parcela
from .serializers import PagamentoCreateSerializer, PagamentoSerializer, ParcelaSerializer
from .services import anotacao_pago, estornar_pagamento, registrar_pagamento


class ParcelaViewSet(FinanceiroAPIMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ParcelaSerializer
    queryset = Parcela.objects.select_related("venda").annotate(**anotacao_pago()).order_by("vencimento", "id")

    def get_queryset(self):
        qs = super().get_queryset()
        params = filtros(self.request.query_params)
        for param, lookup in (("cliente", "venda__cliente_id"), ("venda", "venda_id"),
                              ("venda_status", "venda__status"),
                              ("vencimento_inicio", "vencimento__gte"), ("vencimento_fim", "vencimento__lte")):
            if param in params:
                qs = qs.filter(**{lookup: params[param]})
        situacao = params.get("status")
        hoje = timezone.localdate()
        if situacao == "paga":
            qs = qs.filter(pago_calculado=F("valor_original"))
        elif situacao == "vencida":
            qs = qs.filter(pago_calculado__lt=F("valor_original"), vencimento__lt=hoje)
        elif situacao == "parcial":
            qs = qs.filter(pago_calculado__gt=0, pago_calculado__lt=F("valor_original"), vencimento__gte=hoje)
        elif situacao == "pendente":
            qs = qs.filter(pago_calculado=0, vencimento__gte=hoje)
        elif situacao is not None:
            raise serializers.ValidationError({"status": "Use pendente, parcial, vencida ou paga."})
        return qs


class PagamentoViewSet(FinanceiroAPIMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PagamentoSerializer
    queryset = Pagamento.objects.select_related("venda", "parcela", "responsavel")

    def get_queryset(self):
        qs = super().get_queryset()
        params = filtros(self.request.query_params)
        for param, lookup in (("cliente", "venda__cliente_id"), ("venda", "venda_id"), ("parcela", "parcela_id"),
                              ("tipo", "tipo"), ("data_inicio", "data_pagamento__date__gte"),
                              ("data_fim", "data_pagamento__date__lte")):
            if param in params:
                qs = qs.filter(**{lookup: params[param]})
        return filtrar_status(qs, params.get("status"), Pagamento.Status.values)

    def create(self, request):
        serializer = PagamentoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["parcela_id"] = data.pop("parcela")
        pagamento = executar_servico(registrar_pagamento, usuario=request.user, **data)
        return Response(PagamentoSerializer(pagamento).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def estornar(self, request, pk=None):
        pagamento = self.get_object()
        serializer = MotivoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pagamento = executar_servico(estornar_pagamento, pagamento_id=pagamento.pk, usuario=request.user, **serializer.validated_data)
        return Response(PagamentoSerializer(pagamento).data)
