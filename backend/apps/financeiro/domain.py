"""Small shared primitives used only by transactional domain services."""
import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")


def dinheiro(value, campo):
    try:
        if isinstance(value, (float, bool)):
            raise ValueError
        result = Decimal(value)
        if not result.is_finite() or result != result.quantize(CENTAVO) or abs(result) >= Decimal("1000000000000"):
            raise ValueError
        return result.quantize(CENTAVO)
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError({campo: "Informe um valor monetário válido com até duas casas decimais."})


def chave_uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"chave_idempotencia": "Informe uma chave UUID válida."})


def assinatura(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def exigir_usuario(usuario):
    if not usuario or not usuario.is_authenticated or not usuario.is_active:
        raise ValidationError({"responsavel": "Um usuário ativo deve registrar a operação."})


def conferir_repeticao(obj, digest):
    if obj.requisicao_hash != digest:
        raise ValidationError({"chave_idempotencia": "Esta chave já foi utilizada em outra operação ou com dados diferentes."})
    return obj


def salvar_idempotente(obj):
    # The unique database key also protects requests racing across different clients.
    try:
        with transaction.atomic():
            obj.save(_via_servico=True, force_insert=True)
        return obj, True
    except IntegrityError:
        anterior = type(obj).objects.filter(chave_idempotencia=obj.chave_idempotencia).first()
        if anterior is None:
            raise
        return conferir_repeticao(anterior, obj.requisicao_hash), False
