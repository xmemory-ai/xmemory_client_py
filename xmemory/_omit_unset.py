"""A request model whose newer keys are left out of the dump while unset."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer


class OmitsUnsetKeys(BaseModel):
    """A model whose newer keys are left out of the dump while unset: a server that
    predates them rejects unknown keys, so a model that uses none of them must
    serialize as before."""

    # Each such key, with the value that means unset: ``None``, ``False`` for a flag,
    # or ``{}`` for a mapping.
    _omitted_while_unset: ClassVar[dict[str, Any]] = {}

    @model_serializer(mode="wrap")
    def _omit_unset_keys(self, handler: SerializerFunctionWrapHandler):
        # No return annotation: one would replace the model's serialization JSON schema
        # with a bare object.
        data = handler(self)
        for name, unset in self._omitted_while_unset.items():
            if getattr(self, name) == unset:
                data.pop(name, None)
        return data
