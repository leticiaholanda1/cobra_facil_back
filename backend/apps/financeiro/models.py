from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from .base import RegistroFinanceiro

ZERO = Decimal("0.00")


class Parcela(RegistroFinanceiro):
    venda = models.ForeignKey("vendas.Venda", on_delete=models.PROTECT, related_name="parcelas", verbose_name="venda")
    numero = models.PositiveSmallIntegerField("número")
    vencimento = models.DateField("vencimento", db_index=True)
    valor_original = models.DecimalField("valor original", max_digits=14, decimal_places=2)
    criado_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "parcela"
        verbose_name_plural = "parcelas"
        ordering = ["vencimento", "id"]
        constraints = [
            models.UniqueConstraint(fields=["venda", "numero"], name="parcela_numero_unico"),
            models.CheckConstraint(condition=Q(numero__gt=0) & Q(valor_original__gt=0), name="parcela_valores_positivos"),
        ]

    @property
    def valor_pago(self):
        if hasattr(self, "pago_calculado"):
            return self.pago_calculado
        return self.pagamentos.filter(status=Pagamento.Status.VALIDO).aggregate(total=Sum("valor"))["total"] or ZERO

    @property
    def saldo_restante(self):
        return self.valor_original - self.valor_pago

    @property
    def status(self):
        saldo = self.saldo_restante
        if saldo == ZERO:
            return "paga"
        if self.vencimento < timezone.localdate():
            return "vencida"
        return "parcial" if saldo < self.valor_original else "pendente"

    @property
    def data_quitacao(self):
        if self.saldo_restante != ZERO:
            return None
        return self.pagamentos.filter(status=Pagamento.Status.VALIDO).order_by("-data_pagamento", "-id").values_list("data_pagamento", flat=True).first()

    def __str__(self):
        return f"Venda {self.venda_id} / parcela {self.numero}"


class Pagamento(RegistroFinanceiro):
    class Forma(models.TextChoices):
        DINHEIRO = "dinheiro", "Dinheiro"
        PIX = "pix", "PIX"
        CARTAO = "cartao", "Cartão"
        TRANSFERENCIA = "transferencia", "Transferência"
        OUTRO = "outro", "Outro"

    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        PARCELA = "parcela", "Parcela"

    class Status(models.TextChoices):
        VALIDO = "valido", "Válido"
        ESTORNADO = "estornado", "Estornado"

    venda = models.ForeignKey("vendas.Venda", on_delete=models.PROTECT, related_name="pagamentos", verbose_name="venda")
    parcela = models.ForeignKey(Parcela, on_delete=models.PROTECT, related_name="pagamentos", null=True, blank=True, verbose_name="parcela")
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    valor = models.DecimalField("valor", max_digits=14, decimal_places=2)
    data_pagamento = models.DateTimeField("data do pagamento", default=timezone.now)
    forma_pagamento = models.CharField("forma de pagamento", max_length=15, choices=Forma.choices)
    observacoes = models.TextField("observações", blank=True)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pagamentos_registrados", verbose_name="responsável")
    chave_idempotencia = models.UUIDField("chave de idempotência", unique=True, editable=False)
    requisicao_hash = models.CharField(max_length=64, editable=False)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.VALIDO)
    estornado_em = models.DateTimeField("estornado em", null=True, blank=True, editable=False)
    estornado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pagamentos_estornados", null=True, blank=True, editable=False)
    motivo_estorno = models.TextField("motivo do estorno", blank=True, editable=False)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        ordering = ["-data_pagamento", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(valor__gt=0), name="pagamento_valor_positivo"),
            models.CheckConstraint(condition=(Q(tipo="entrada", parcela__isnull=True) | Q(tipo="parcela", parcela__isnull=False)), name="pagamento_tipo_consistente"),
            models.UniqueConstraint(fields=["venda"], condition=Q(tipo="entrada"), name="pagamento_entrada_unica"),
            models.CheckConstraint(condition=(Q(status="valido", estornado_em__isnull=True, estornado_por__isnull=True, motivo_estorno="") | (Q(status="estornado", estornado_em__isnull=False, estornado_por__isnull=False) & ~Q(motivo_estorno=""))), name="pagamento_estorno_rastreavel"),
        ]

    def __str__(self):
        return f"Pagamento {self.pk} — R$ {self.valor}"
