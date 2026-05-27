from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, final

from domain.entities.form import FormField, SemanticType


class ClassifierPortError(RuntimeError):
    """Erro base para falhas do port de classificacao semantica."""


class ClassifierContractError(ClassifierPortError):
    """Sinaliza que um adapter violou o contrato do classificador."""


class ClassifierPort(ABC):
    """Contrato para classificadores semanticos de campos de formulario.

    O objetivo deste port e isolar a camada de dominio de qualquer mecanismo
    concreto de classificacao. Implementacoes podem usar heuristicas, LLMs,
    cache, regras por portal ou uma composicao dessas estrategias, desde que
    entreguem a mesma saida esperada pelo restante do fluxo:

    - receber campos extraidos do DOM;
    - inferir o ``SemanticType`` de cada campo;
    - devolver campos prontos para a etapa de geracao/preenchimento;
    - nao expor detalhes de provedor externo para o dominio.

    Ambiguidade faz parte do problema. Quando a classificacao nao for confiavel,
    o adapter deve usar ``SemanticType.UNKNOWN`` em vez de deixar o campo sem
    ``semantic_type``.
    """

    @final
    async def classify(self, fields: Sequence[FormField]) -> list[FormField]:
        """Classifica campos preservando quantidade, ordem e metadados do DOM.

        Contrato do resultado:

        - a lista retornada deve ter a mesma quantidade e ordem da entrada;
        - cada item retornado deve ser um ``FormField``;
        - ``semantic_type`` deve estar sempre preenchido;
        - todos os demais atributos do campo devem ser preservados;
        - ``generated_value`` nao deve ser preenchido aqui.
        """
        original_fields = list(fields)
        original_snapshots = [field.model_dump() for field in original_fields]

        classified_fields = await self._classify(original_fields)
        self._ensure_contract(original_snapshots, classified_fields)

        return classified_fields

    @abstractmethod
    async def _classify(self, fields: Sequence[FormField]) -> list[FormField]:
        """Implementa a estrategia concreta de classificacao.

        Implementacoes devem retornar um ``FormField`` para cada entrada, com
        ``semantic_type`` preenchido com um valor de ``SemanticType``. Use
        ``SemanticType.UNKNOWN`` para campos sem inferencia segura.
        """
        raise NotImplementedError

    async def choose_option(self, field: FormField, profile_summary: str = "") -> str | None:
        """Escolhe a melhor opcao para um campo de escolha nao classificado.

        Fallback usado pelo orquestrador quando ``semantic_type`` ficou ``UNKNOWN``
        para um radio/select com mais de duas opcoes (ex.: "Tipo de Fornecedor",
        "Porte de Empresa"), evitando o chute cego em "Nao". Recebe o campo (com
        ``options``) e um resumo do perfil da empresa; deve retornar o texto de
        UMA das opcoes ou ``None`` quando nao houver correspondencia segura.

        Implementacao padrao nao decide (retorna ``None``). Adapters com LLM
        sobrescrevem.
        """
        return None

    @staticmethod
    def unknown(field: FormField) -> FormField:
        """Cria uma copia do campo marcada como nao classificada."""
        return field.model_copy(update={"semantic_type": SemanticType.UNKNOWN})

    @staticmethod
    def _ensure_contract(
        original_snapshots: list[dict[str, Any]],
        classified_fields: list[FormField],
    ) -> None:
        if not isinstance(classified_fields, list):
            raise ClassifierContractError(
                "Classifier adapters must return list[FormField]."
            )

        if len(classified_fields) != len(original_snapshots):
            raise ClassifierContractError(
                "Classifier adapters must preserve the number of fields."
            )

        for index, (original, classified) in enumerate(
            zip(original_snapshots, classified_fields)
        ):
            if not isinstance(classified, FormField):
                raise ClassifierContractError(
                    f"Classified item at index {index} is not a FormField."
                )

            if classified.semantic_type is None:
                raise ClassifierContractError(
                    f"Classified field at index {index} has no semantic_type."
                )

            if not isinstance(classified.semantic_type, SemanticType):
                raise ClassifierContractError(
                    f"semantic_type at index {index} is not a SemanticType."
                )

            classified_snapshot = classified.model_dump()
            original_without_semantics = {
                key: value for key, value in original.items() if key != "semantic_type"
            }
            classified_without_semantics = {
                key: value
                for key, value in classified_snapshot.items()
                if key != "semantic_type"
            }

            if classified_without_semantics != original_without_semantics:
                raise ClassifierContractError(
                    "Classifier adapters may only change semantic_type."
                )
