from rest_framework import filters, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from .models import Cliente
from .serializers import ClienteSerializer


class ClientePagination(PageNumberPagination):
    page_size = 25


class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ClientePagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nome", "cpf", "telefone"]
    ordering_fields = ["nome", "criado_em"]
    ordering = ["nome", "id"]

    def get_queryset(self):
        queryset = super().get_queryset()
        ativo = self.request.query_params.get("ativo")
        if ativo is not None:
            values = {"true": True, "false": False, "1": True, "0": False}
            if ativo.lower() not in values:
                raise serializers.ValidationError({"ativo": "Use true, false, 1 ou 0."})
            queryset = queryset.filter(ativo=values[ativo.lower()])
        return queryset

    def perform_destroy(self, instance):
        instance.ativo = False
        instance.save(update_fields=["ativo", "atualizado_em"])

    @action(detail=True, methods=["get"], url_path="resumo-financeiro")
    def resumo_financeiro(self, request, pk=None):
        from apps.financeiro.serializers import ResumoFinanceiroSerializer
        from apps.financeiro.services import resumo_financeiro

        cliente = self.get_object()
        return Response(ResumoFinanceiroSerializer(resumo_financeiro(cliente.pk)).data)
