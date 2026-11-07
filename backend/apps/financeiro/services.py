from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.vendas.models import Venda
from apps.vendas.services import bloquear_venda

from .domain import ZERO, assinatura, chave_uuid, conferir_repeticao, dinheiro, exigir_usuario, salvar_idempotente
from .models import Pagamento, Parcela


@transaction.atomic
def registrar_pagamento(*, parcela_id, valor, forma_pagamento, usuario,
                       chave_idempotencia, observacoes="", data_pagamento=None):
    exigir_usuario(usuario)
    chave = chave_uuid(chave_idempotencia)
    valor = dinheiro(valor, "valor")
    if valor <= ZERO:
        raise ValidationError({"valor": "O pagamento deve ser maior que zero."})
    if forma_pagamento not in Pagamento.Forma.values:
        raise ValidationError({"forma_pagamento": "Forma de pagamento inválida."})
    if data_pagamento is not None and (timezone.is_naive(data_pagamento) or data_pagamento > timezone.now()):
        raise ValidationError({"data_pagamento": "Informe uma data com fuso horário que não esteja no futuro."})
    digest = assinatura({"parcela": parcela_id, "valor": valor, "forma": forma_pagamento,
                         "usuario": usuario.pk, "observacoes": observacoes, "data": data_pagamento})
    try:
        venda_id = Parcela.objects.values_list("venda_id", flat=True).get(pk=parcela_id)
    except Parcela.DoesNotExist:
        raise ValidationError({"parcela": "Parcela não encontrada."})
    venda = bloquear_venda(venda_id)
    parcela = Parcela.objects.select_for_update().get(pk=parcela_id)
    anterior = Pagamento.objects.filter(chave_idempotencia=chave).first()
    if anterior:
        return conferir_repeticao(anterior, digest)
    if venda.status != Venda.Status.ATIVA:
        raise ValidationError({"parcela": "Não é permitido pagar parcelas de vendas canceladas."})
    if valor > parcela.saldo_restante:
        raise ValidationError({"valor": "O pagamento não pode ultrapassar o saldo restante da parcela."})
    pagamento, _ = salvar_idempotente(Pagamento(
        venda=venda, parcela=parcela, tipo=Pagamento.Tipo.PARCELA, valor=valor,
        forma_pagamento=forma_pagamento, responsavel=usuario, observacoes=observacoes,
        data_pagamento=data_pagamento or timezone.now(), chave_idempotencia=chave, requisicao_hash=digest,
    ))
    return pagamento


@transaction.atomic
def estornar_pagamento(*, pagamento_id, usuario, motivo):
    exigir_usuario(usuario)
    motivo = motivo.strip()
    if not motivo:
        raise ValidationError({"motivo": "Informe o motivo do estorno."})
    try:
        venda_id = Pagamento.objects.values_list("venda_id", flat=True).get(pk=pagamento_id)
    except Pagamento.DoesNotExist:
        raise ValidationError({"pagamento": "Pagamento não encontrado."})
    bloquear_venda(venda_id)
    pagamento = Pagamento.objects.select_for_update().get(pk=pagamento_id)
    if pagamento.status == Pagamento.Status.ESTORNADO:
        if pagamento.motivo_estorno != motivo:
            raise ValidationError({"motivo": "O pagamento já foi estornado com outro motivo."})
        return pagamento
    pagamento.status = Pagamento.Status.ESTORNADO
    pagamento.estornado_em = timezone.now()
    pagamento.estornado_por = usuario
    pagamento.motivo_estorno = motivo
    pagamento.save(_via_servico=True, update_fields=["status", "estornado_em", "estornado_por", "motivo_estorno"])
    return pagamento


@transaction.atomic
def resumo_financeiro(cliente_id):
    # All financial writes also lock this row: these multiple aggregates see a consistent ledger.
    Cliente.objects.select_for_update().get(pk=cliente_id)
    vendas = Venda.objects.filter(cliente_id=cliente_id, status=Venda.Status.ATIVA)
    parcelas = Parcela.objects.filter(venda__in=vendas).annotate(
        **anotacao_pago()
    )
    pagamentos = Pagamento.objects.filter(venda__in=vendas, status=Pagamento.Status.VALIDO)
    from django.db.models import Sum
    total = vendas.aggregate(total=Sum("valor_total"))["total"] or ZERO
    entradas = pagamentos.filter(tipo=Pagamento.Tipo.ENTRADA).aggregate(total=Sum("valor"))["total"] or ZERO
    pago_parcelas = pagamentos.filter(tipo=Pagamento.Tipo.PARCELA).aggregate(total=Sum("valor"))["total"] or ZERO
    lista = list(parcelas)
    # A reversed entry is an open receivable until the sale is cancelled; never silently lose it.
    entradas_previstas = vendas.aggregate(total=Sum("valor_entrada"))["total"] or ZERO
    saldo_entrada = entradas_previstas - entradas
    return {
        "total_compras": total, "total_entradas_recebidas": entradas,
        "total_pago_parcelas": pago_parcelas, "total_efetivamente_pago": entradas + pago_parcelas,
        "saldo_devedor": sum((p.saldo_restante for p in lista), ZERO) + saldo_entrada,
        "saldo_entrada_estornada": saldo_entrada,
        "parcelas_pendentes": sum(p.status in ("pendente", "parcial") for p in lista),
        "parcelas_vencidas": sum(p.status == "vencida" for p in lista),
        "parcelas_quitadas": sum(p.status == "paga" for p in lista),
    }


def anotacao_pago():
    from django.db.models import DecimalField, Q, Sum, Value
    from django.db.models.functions import Coalesce
    return {"pago_calculado": Coalesce(
        Sum("pagamentos__valor", filter=Q(pagamentos__status=Pagamento.Status.VALIDO)),
        Value(ZERO), output_field=DecimalField(max_digits=14, decimal_places=2),
    )}
