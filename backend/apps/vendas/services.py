import calendar
from datetime import date
from decimal import ROUND_DOWN
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.financeiro.domain import (
    CENTAVO, ZERO, assinatura, chave_uuid, conferir_repeticao, dinheiro,
    exigir_usuario, salvar_idempotente,
)
from apps.financeiro.models import Pagamento, Parcela

from .models import ItemVenda, Venda


def vencimento_mensal(primeiro, offset):
    """Anchor every due date on the original day, clamped to the month's last day."""
    month_index = primeiro.year * 12 + primeiro.month - 1 + offset
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(primeiro.day, calendar.monthrange(year, month)[1]))


@transaction.atomic
def registrar_venda(*, cliente_id, itens, valor_entrada, quantidade_parcelas,
                    usuario, chave_idempotencia, primeiro_vencimento=None,
                    valor_total=None, data_venda=None, forma_entrada=None, observacoes=""):
    exigir_usuario(usuario)
    chave = chave_uuid(chave_idempotencia)
    if not itens:
        raise ValidationError({"itens": "Informe ao menos um item."})
    linhas = []
    for item in itens:
        descricao = item.get("descricao", "").strip()
        quantidade = item.get("quantidade")
        if not descricao or len(descricao) > 255:
            raise ValidationError({"itens": "Informe uma descrição com até 255 caracteres."})
        if type(quantidade) is not int or not 1 <= quantidade <= 2147483647:
            raise ValidationError({"itens": "A quantidade de cada item deve ser um inteiro positivo."})
        unitario = dinheiro(item.get("valor_unitario"), "valor_unitario")
        total_item = dinheiro(unitario * quantidade, "itens")
        if unitario <= ZERO:
            raise ValidationError({"itens": "O valor unitário deve ser maior que zero."})
        linhas.append({"descricao": descricao, "quantidade": quantidade,
                       "valor_unitario": unitario, "valor_total": total_item,
                       "observacoes": item.get("observacoes", "")})
    total = dinheiro(sum((linha["valor_total"] for linha in linhas), ZERO), "valor_total")
    if valor_total is not None and dinheiro(valor_total, "valor_total") != total:
        raise ValidationError({"valor_total": "O total informado deve corresponder à soma dos itens."})
    entrada = dinheiro(valor_entrada, "valor_entrada")
    if entrada < ZERO or entrada > total:
        raise ValidationError({"valor_entrada": "A entrada deve estar entre zero e o total da venda."})
    financiado = total - entrada
    if type(quantidade_parcelas) is not int or not 0 <= quantidade_parcelas <= 1200:
        raise ValidationError({"quantidade_parcelas": "Informe um inteiro entre 0 e 1200."})
    if financiado == ZERO:
        if quantidade_parcelas != 0 or primeiro_vencimento is not None:
            raise ValidationError({"quantidade_parcelas": "Venda à vista exige zero parcelas e nenhum vencimento."})
    elif not quantidade_parcelas or not isinstance(primeiro_vencimento, date):
        raise ValidationError({"primeiro_vencimento": "Venda financiada exige parcelas e primeiro vencimento."})
    elif financiado < CENTAVO * quantidade_parcelas:
        raise ValidationError({"quantidade_parcelas": "Não é possível gerar parcelas menores que um centavo."})
    if entrada > ZERO and forma_entrada not in Pagamento.Forma.values:
        raise ValidationError({"forma_entrada": "Informe a forma de recebimento da entrada."})
    if entrada == ZERO and forma_entrada is not None:
        raise ValidationError({"forma_entrada": "Não informe forma de entrada quando a entrada for zero."})
    if financiado:
        try:
            vencimento_mensal(primeiro_vencimento, quantidade_parcelas - 1)
        except (ValueError, OverflowError):
            raise ValidationError({"primeiro_vencimento": "O plano ultrapassa o limite de datas suportado."})
    # Omitted sale dates remain omitted in the hash, so retries work across midnight.
    digest = assinatura({"cliente": cliente_id, "itens": linhas, "entrada": entrada,
                         "parcelas": quantidade_parcelas, "primeiro": primeiro_vencimento,
                         "data": data_venda, "forma": forma_entrada, "observacoes": observacoes,
                         "usuario": usuario.pk})
    try:
        cliente = Cliente.objects.select_for_update().get(pk=cliente_id)
    except Cliente.DoesNotExist:
        raise ValidationError({"cliente": "Cliente não encontrado."})
    anterior = Venda.objects.filter(chave_idempotencia=chave).first()
    if anterior:
        return conferir_repeticao(anterior, digest)
    if not cliente.ativo:
        raise ValidationError({"cliente": "O cliente deve estar ativo para registrar uma venda."})
    venda, nova = salvar_idempotente(Venda(
        cliente=cliente, valor_total=total, valor_entrada=entrada, valor_financiado=financiado,
        quantidade_parcelas=quantidade_parcelas, primeiro_vencimento=primeiro_vencimento,
        data_venda=data_venda or timezone.localdate(), observacoes=observacoes,
        responsavel=usuario, chave_idempotencia=chave, requisicao_hash=digest,
    ))
    if not nova:
        return venda
    for linha in linhas:
        ItemVenda(venda=venda, **linha).save(_via_servico=True)
    if entrada > ZERO:
        Pagamento(
            venda=venda, tipo=Pagamento.Tipo.ENTRADA, valor=entrada,
            forma_pagamento=forma_entrada, responsavel=usuario,
            chave_idempotencia=uuid4(), requisicao_hash=digest,
        ).save(_via_servico=True)
    if financiado:
        base = (financiado / quantidade_parcelas).quantize(CENTAVO, rounding=ROUND_DOWN)
        for index in range(quantidade_parcelas):
            valor = base if index < quantidade_parcelas - 1 else financiado - base * (quantidade_parcelas - 1)
            Parcela(venda=venda, numero=index + 1,
                    vencimento=vencimento_mensal(primeiro_vencimento, index),
                    valor_original=valor).save(_via_servico=True)
    return venda


def bloquear_venda(venda_id):
    """All financial writes lock customer → sale → installment → payment."""
    try:
        cliente_id = Venda.objects.values_list("cliente_id", flat=True).get(pk=venda_id)
        Cliente.objects.select_for_update().get(pk=cliente_id)
        return Venda.objects.select_for_update().get(pk=venda_id)
    except (Venda.DoesNotExist, Cliente.DoesNotExist):
        raise ValidationError({"venda": "Venda não encontrada."})


@transaction.atomic
def cancelar_venda(*, venda_id, usuario, motivo):
    exigir_usuario(usuario)
    motivo = motivo.strip()
    if not motivo:
        raise ValidationError({"motivo": "Informe o motivo do cancelamento."})
    venda = bloquear_venda(venda_id)
    if venda.status == Venda.Status.CANCELADA:
        if venda.motivo_cancelamento != motivo:
            raise ValidationError({"motivo": "A venda já foi cancelada com outro motivo."})
        return venda
    if venda.pagamentos.filter(status=Pagamento.Status.VALIDO).exists():
        raise ValidationError({"venda": "Estorne todos os recebimentos, inclusive a entrada, antes de cancelar. Não há reembolso automático."})
    venda.status = Venda.Status.CANCELADA
    venda.cancelada_em = timezone.now()
    venda.cancelada_por = usuario
    venda.motivo_cancelamento = motivo
    venda.save(_via_servico=True, update_fields=["status", "cancelada_em", "cancelada_por", "motivo_cancelamento", "atualizado_em"])
    return venda
