from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.financeiro.base import RegistroFinanceiro


class Venda(RegistroFinanceiro):
    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CANCELADA = "cancelada", "Cancelada"

    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, related_name="vendas", verbose_name="cliente")
    data_venda = models.DateField("data da venda", default=timezone.localdate)
    valor_total = models.DecimalField("valor total", max_digits=14, decimal_places=2)
    valor_entrada = models.DecimalField("entrada", max_digits=14, decimal_places=2, default=0)
    valor_financiado = models.DecimalField("valor financiado", max_digits=14, decimal_places=2, editable=False)
    quantidade_parcelas = models.PositiveSmallIntegerField("quantidade de parcelas", default=0)
    primeiro_vencimento = models.DateField("primeiro vencimento", null=True, blank=True)
    observacoes = models.TextField("observações", blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.ATIVA)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vendas_registradas", verbose_name="responsável")
    chave_idempotencia = models.UUIDField("chave de idempotência", unique=True, editable=False)
    requisicao_hash = models.CharField(max_length=64, editable=False)
    cancelada_em = models.DateTimeField("cancelada em", null=True, blank=True, editable=False)
    cancelada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vendas_canceladas", null=True, blank=True, editable=False)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True, editable=False)
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "venda"
        verbose_name_plural = "vendas"
        ordering = ["-data_venda", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(valor_total__gt=0), name="venda_total_positivo"),
            models.CheckConstraint(condition=Q(valor_entrada__gte=0) & Q(valor_entrada__lte=F("valor_total")), name="venda_entrada_valida"),
            models.CheckConstraint(condition=Q(valor_financiado=F("valor_total") - F("valor_entrada")), name="venda_financiado_consistente"),
            models.CheckConstraint(condition=(Q(valor_financiado=0, quantidade_parcelas=0, primeiro_vencimento__isnull=True) | Q(valor_financiado__gt=0, quantidade_parcelas__gt=0, primeiro_vencimento__isnull=False)), name="venda_plano_valido"),
            models.CheckConstraint(condition=(Q(status="ativa", cancelada_em__isnull=True, cancelada_por__isnull=True, motivo_cancelamento="") | (Q(status="cancelada", cancelada_em__isnull=False, cancelada_por__isnull=False) & ~Q(motivo_cancelamento=""))), name="venda_cancelamento_rastreavel"),
        ]

    def __str__(self):
        return f"Venda {self.pk} — {self.cliente}"


class ItemVenda(RegistroFinanceiro):
    venda = models.ForeignKey(Venda, on_delete=models.PROTECT, related_name="itens", verbose_name="venda")
    descricao = models.CharField("descrição", max_length=255)
    quantidade = models.PositiveIntegerField("quantidade", validators=[MinValueValidator(1)])
    valor_unitario = models.DecimalField("valor unitário", max_digits=14, decimal_places=2)
    valor_total = models.DecimalField("valor total", max_digits=14, decimal_places=2, editable=False)
    observacoes = models.TextField("observações", blank=True)

    class Meta:
        verbose_name = "item da venda"
        verbose_name_plural = "itens da venda"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantidade__gt=0) & Q(valor_unitario__gt=0), name="item_valores_positivos"),
            models.CheckConstraint(condition=Q(valor_total=F("quantidade") * F("valor_unitario")), name="item_total_consistente"),
        ]

    def __str__(self):
        return self.descricao
