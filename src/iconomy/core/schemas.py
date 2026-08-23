from typing import Any

import falcon
import falcon.asgi
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError
from pydantic.alias_generators import to_camel
from pydantic_core import ErrorDetails

from iconomy.core.errors import ValidationError


class Schema(BaseModel):
    """Base for every payload crossing the API boundary.

    Fields are snake_case in Python and camelCase on the wire, which is the
    vocabulary the web client already speaks (see `front/src/types/domain.ts`).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    def to_media(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


def _describe(error: ErrorDetails) -> dict[str, Any]:
    location = [str(part) for part in error["loc"] if part != "body"]
    return {"field": ".".join(location) or "body", "message": error["msg"]}


async def read_body[T: Schema](req: falcon.asgi.Request, schema: type[T]) -> T:
    try:
        payload = await req.get_media()
    except falcon.MediaNotFoundError as ex:
        raise ValidationError("A JSON body is required.") from ex
    except falcon.MediaMalformedError as ex:
        raise ValidationError("The request body is not valid JSON.") from ex

    if not isinstance(payload, dict):
        raise ValidationError("The request body must be a JSON object.")

    try:
        return schema.model_validate(payload)
    except PydanticValidationError as ex:
        fields = [_describe(error) for error in ex.errors()]
        raise ValidationError("The request body failed validation.", fields=fields) from ex
