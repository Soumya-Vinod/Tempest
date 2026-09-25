"""Minimal GeoJSON (RFC 7946) models, EPSG:4326, [lon, lat] order."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Position = Annotated[list[float], Field(min_length=2, max_length=3)]
Ring = Annotated[list[Position], Field(min_length=4)]
Line = Annotated[list[Position], Field(min_length=2)]


class _Geometry(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(_Geometry):
    type: Literal["Point"] = "Point"
    coordinates: Position


class LineString(_Geometry):
    type: Literal["LineString"] = "LineString"
    coordinates: Line


class MultiLineString(_Geometry):
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[Line]


class Polygon(_Geometry):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[Ring]


class MultiPolygon(_Geometry):
    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: list[list[Ring]]


AreaGeometry = Annotated[Polygon | MultiPolygon, Field(discriminator="type")]
InfraGeometry = Annotated[Point | LineString | MultiLineString, Field(discriminator="type")]


class Feature(BaseModel):
    """Base Feature. Subclasses declare `geometry` and `properties`; Feature.id == properties.id."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"] = "Feature"
    id: str

    @model_validator(mode="after")
    def _id_matches_properties(self) -> Self:
        props: Any = getattr(self, "properties", None)
        if props is not None and getattr(props, "id", self.id) != self.id:
            raise ValueError("Feature.id must equal properties.id")
        return self


class FeatureCollection[F: Feature](BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[F]
