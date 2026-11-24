from pydantic import BaseModel

from app.models import OrderScenario, ServiceOffer
from app.rules.comparability import ComparabilityAssessment, check_comparability
from app.rules.completeness import CompletenessAssessment, check_completeness
from app.rules.similarity import SimilarityAssessment, evaluate_similarity


class OfferEvaluation(BaseModel):
    """Совокупный результат проверки полноты данных, сопоставимости и сходства."""

    comparability: ComparabilityAssessment
    completeness: CompletenessAssessment
    similarity: SimilarityAssessment


def evaluate_offer(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> OfferEvaluation:
    """Выполняет независимую проверку полноты данных, сопоставимости и сходства."""
    return OfferEvaluation(
        comparability=check_comparability(offer, scenario),
        completeness=check_completeness(offer, scenario),
        similarity=evaluate_similarity(offer, scenario),
    )
