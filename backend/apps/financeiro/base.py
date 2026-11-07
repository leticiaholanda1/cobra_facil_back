from django.core.exceptions import ValidationError
from django.db import models


class HistoricoQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Registros financeiros não podem ser excluídos.")

    def update(self, **kwargs):
        raise ValidationError("Utilize os serviços financeiros para alterar lançamentos.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Utilize os serviços financeiros para registrar lançamentos.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Utilize os serviços financeiros para alterar lançamentos.")


class RegistroFinanceiro(models.Model):
    """Writes through domain services; normal ORM and Admin writes are blocked."""

    objects = HistoricoQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, _via_servico=False, **kwargs):
        if not _via_servico:
            raise ValidationError("Utilize os serviços financeiros para registrar esta operação.")
        self.full_clean(validate_unique=False)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Registros financeiros não podem ser excluídos.")
