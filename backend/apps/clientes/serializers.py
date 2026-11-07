from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Cliente
from .validators import normalizar_cep, normalizar_cpf, normalizar_estado


class CPFField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalizar_cpf(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)


class ClienteSerializer(serializers.ModelSerializer):
    cpf = CPFField(
        required=False, allow_blank=True, allow_null=True,
        validators=[UniqueValidator(Cliente.objects.all(), message="Já existe um cliente com este CPF.")],
    )
    cep = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Cliente
        fields = (
            "id", "nome", "cpf", "telefone", "whatsapp", "email", "cep", "logradouro",
            "numero", "complemento", "bairro", "cidade", "estado", "observacoes", "ativo",
            "criado_em", "atualizado_em",
        )
        read_only_fields = ("id", "criado_em", "atualizado_em")

    def validate_cep(self, value):
        return normalizar_cep(value)

    def validate_estado(self, value):
        return normalizar_estado(value)

    def _save_validated(self, operation, *args):
        try:
            with transaction.atomic():
                return operation(*args)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        except IntegrityError:
            # Also cover competing requests that submit the same CPF.
            cpf = args[-1].get("cpf")
            if cpf and Cliente.objects.filter(cpf=cpf).exists():
                raise serializers.ValidationError({"cpf": ["Já existe um cliente com este CPF."]})
            raise

    def create(self, validated_data):
        return self._save_validated(super().create, validated_data)

    def update(self, instance, validated_data):
        return self._save_validated(super().update, instance, validated_data)
