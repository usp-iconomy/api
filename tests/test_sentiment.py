import pytest

from iconomy.circulation.models import Sentiment
from iconomy.circulation.sentiment import KeywordSentimentClassifier

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "text",
    [
        "Obrigada pela facilitação incrível!",
        "Parabéns pelo trabalho excelente.",
        "Que gratidão imensa, você é maravilhosa.",
        "Fiquei muito feliz com a aula, adorei!",
    ],
)
async def test_positive_messages_classify_as_positive(text: str) -> None:
    classifier = KeywordSentimentClassifier()
    assert await classifier.classify(text) == Sentiment.POSITIVE


@pytest.mark.parametrize(
    "text",
    [
        "Fiquei muito triste com a situação.",
        "A decepção foi grande, péssima experiência.",
        "Essa aula foi horrível, não gostei.",
        "Que raiva, isso está totalmente errado!",
    ],
)
async def test_negative_messages_classify_as_negative(text: str) -> None:
    classifier = KeywordSentimentClassifier()
    assert await classifier.classify(text) == Sentiment.NEGATIVE


@pytest.mark.parametrize(
    "text",
    [
        "Encontro às quinze horas na sala B.",
        "Material enviado conforme combinado.",
        "Posso levar o livro na próxima semana.",
    ],
)
async def test_neutral_messages_classify_as_neutral(text: str) -> None:
    classifier = KeywordSentimentClassifier()
    assert await classifier.classify(text) == Sentiment.NEUTRAL


async def test_accent_insensitive() -> None:
    classifier = KeywordSentimentClassifier()
    # "parabéns" sem acento ainda bate em "paraben".
    assert await classifier.classify("Parabens pelo trabalho") == Sentiment.POSITIVE


async def test_tie_resolves_to_neutral() -> None:
    classifier = KeywordSentimentClassifier()
    # Uma palavra positiva e uma negativa — empate = neutral.
    assert await classifier.classify("Obrigada mas foi ruim") == Sentiment.NEUTRAL
