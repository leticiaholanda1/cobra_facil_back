from django.db.models import Prefetch
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.financeiro.api import FinanceiroAPIMixin, MotivoSerializer, executar_servico, filtros, filtrar_status
from apps.financeiro.models import Parcela
from apps.financeiro.serializers import ParcelaSerializer
from apps.financeiro.services import anotacao_pago

from .models import Venda
from .serializers import VendaCreateSerializer, VendaSerializer
from .services import cancelar_venda, registrar_venda


class VendaViewSet(FinanceiroAPIMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = VendaSerializer
    queryset = Venda.objects.select_related("cliente").prefetch_related(
        "itens", Prefetch("parcelas", queryset=Parcela.objects.select_related("venda").annotate(**anotacao_pago()).order_by("vencimento", "id")),
    )

    def get_queryset(self):
        qs = super().get_queryset()
        params = filtros(self.request.query_params)
        if "cliente" in params:
            qs = qs.filter(cliente_id=params["cliente"])
        if "data_inicio" in params:
            qs = qs.filter(data_venda__gte=params["data_inicio"])
        if "data_fim" in params:
            qs = qs.filter(data_venda__lte=params["data_fim"])
        return filtrar_status(qs, params.get("status"), Venda.Status.values)

    def create(self, request):
        serializer = VendaCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["cliente_id"] = data.pop("cliente")
        venda = executar_servico(registrar_venda, usuario=request.user, **data)
        return Response(VendaSerializer(venda).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        venda = self.get_object()
        serializer = MotivoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        venda = executar_servico(cancelar_venda, venda_id=venda.pk, usuario=request.user, **serializer.validated_data)
        return Response(VendaSerializer(venda).data)

    @action(detail=True, methods=["get"])
    def parcelas(self, request, pk=None):
        venda = self.get_object()
        page = self.paginate_queryset(venda.parcelas.all())
        return self.get_paginated_response(ParcelaSerializer(page, many=True).data)
