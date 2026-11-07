from django import forms

from .models import Cliente
from .validators import normalizar_cep, normalizar_cpf


class ClienteAdminForm(forms.ModelForm):
    cpf = forms.CharField(label="CPF", required=False, max_length=14)
    cep = forms.CharField(label="CEP", required=False, max_length=9)

    class Meta:
        model = Cliente
        fields = "__all__"

    def clean_cpf(self):
        return normalizar_cpf(self.cleaned_data["cpf"])

    def clean_cep(self):
        return normalizar_cep(self.cleaned_data["cep"])
