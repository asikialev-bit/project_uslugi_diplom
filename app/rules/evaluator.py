from pydantic import BaseModel

from app.models import OrderScenario, ServiceOffer
from app.rules.comparability import ComparabilityAssessment, check_comparability
from app.rules.completeness import CompletenessAssessment, check_completeness


class OfferEvaluation(BaseModel):
    """Совокупный результат проверки полноты данных и сопоставимости."""

    comparability: ComparabilityAssessment
    completeness: CompletenessAssessment


def evaluate_offer(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> OfferEvaluation:
    """Выполняет независимую проверку полноты данных и сопоставимости."""
    return OfferEvaluation(
        comparability=check_comparability(offer, scenario),
        completeness=check_completeness(offer, scenario),
    )
