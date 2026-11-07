from django.core.exceptions import ValidationError
from django.db import models

from .validators import (
    normalizar_cep, normalizar_cpf, normalizar_estado, validar_nome, validar_telefone,
)


class Cliente(models.Model):
    nome = models.CharField("nome", max_length=200, validators=[validar_nome])
    cpf = models.CharField("CPF", max_length=11, blank=True, null=True, unique=True)
    telefone = models.CharField("telefone", max_length=20, validators=[validar_telefone])
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True, validators=[validar_telefone])
    email = models.EmailField("e-mail", blank=True)
    cep = models.CharField("CEP", max_length=8, blank=True)
    logradouro = models.CharField("logradouro", max_length=255, blank=True)
    numero = models.CharField("número", max_length=20, blank=True)
    complemento = models.CharField("complemento", max_length=255, blank=True)
    bairro = models.CharField("bairro", max_length=100, blank=True)
    cidade = models.CharField("cidade", max_length=100, blank=True)
    estado = models.CharField("estado", max_length=2, blank=True)
    observacoes = models.TextField("observações", blank=True)
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("data de cadastro", auto_now_add=True)
    atualizado_em = models.DateTimeField("última atualização", auto_now=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome", "id"]
        indexes = [models.Index(fields=["nome"], name="cliente_nome_idx")]

    def __str__(self):
        return self.nome

    def clean_fields(self, exclude=None):
        # Normalize before Django checks field lengths and CPF uniqueness.
        errors = {}
        for field, normalize in (
            ("cpf", normalizar_cpf), ("cep", normalizar_cep),
            ("estado", normalizar_estado),
        ):
            if field not in (exclude or ()):
                try:
                    setattr(self, field, normalize(getattr(self, field)))
                except ValidationError as exc:
                    errors[field] = exc.messages
        self.nome = self.nome.strip()
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as exc:
            for field, messages in exc.message_dict.items():
                errors.setdefault(field, messages)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
