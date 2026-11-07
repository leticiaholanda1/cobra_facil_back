import re

from django.core.exceptions import ValidationError


def normalizar_cpf(value):
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not re.fullmatch(r"[0-9]{11}|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}", value):
        raise ValidationError("Informe um CPF válido com 11 dígitos.")
    cpf = re.sub(r"[^0-9]", "", value)
    if len(set(cpf)) == 1:
        raise ValidationError("Informe um CPF válido.")
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        digit = (total * 10 % 11) % 10
        if int(cpf[size]) != digit:
            raise ValidationError("Informe um CPF válido.")
    return cpf


def normalizar_cep(value):
    value = (value or "").strip()
    if not value:
        return ""
    if not re.fullmatch(r"[0-9]{8}|[0-9]{5}-[0-9]{3}", value):
        raise ValidationError("Informe um CEP válido com 8 dígitos.")
    return value.replace("-", "")


def validar_nome(value):
    if not value.strip():
        raise ValidationError("Informe o nome do cliente.")


def validar_telefone(value):
    digits = re.sub(r"[^0-9]", "", value)
    if not re.fullmatch(r"[0-9+() .-]+", value) or not 10 <= len(digits) <= 15:
        raise ValidationError("Informe um telefone válido com DDD (10 a 15 dígitos).")


def normalizar_estado(value):
    value = (value or "").strip().upper()
    if value and not re.fullmatch(r"[A-Z]{2}", value):
        raise ValidationError("Informe a sigla do estado com duas letras.")
    return value
