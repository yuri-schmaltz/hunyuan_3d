from enum import Enum
from typing import Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class MeshOpsAction(str, Enum):
    DECIMATE = "decimate"
    CONVERT = "convert"


class BaseGenerationRequest(BaseModel):
    """Common parameters for all generation types."""
    seed: int = Field(1234, description="Random seed", examples=[1234])
    steps: int = Field(50, ge=1, le=100, description="Denoising steps", examples=[50, 5])
    guidance: float = Field(5.0, ge=1.0, le=20.0, description="Guidance scale", examples=[5.0, 7.5])
    octree_resolution: int = Field(
        256, ge=16, le=512, description="Voxel resolution", examples=[256, 384],
    )
    format: Literal['glb', 'obj', 'ply', 'stl'] = Field(
        'glb', description="Output mesh format", examples=['glb'],
    )
    texture: bool = Field(False, description="Generate texture?", examples=[False, True])
    face_count: int = Field(
        40000, ge=100, le=1000000,
        description="Target face count for reduction", examples=[40000],
    )

    model_config = ConfigDict(extra='forbid')


class TextTo3DRequest(BaseGenerationRequest):
    type: Literal['text_to_3d'] = 'text_to_3d'
    prompt: str = Field(
        ..., min_length=1, description="Text prompt",
        examples=["a cute cat with white fur"],
    )


class ImageTo3DRequest(BaseGenerationRequest):
    type: Literal['image_to_3d'] = 'image_to_3d'
    image: str = Field(
        ...,
        description="Base64 encoded image (optionally with a `data:image/...;base64,` prefix)",
        examples=["iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="],
    )
    remove_background: bool = Field(
        True, description="Remove background using rembg?", examples=[True],
    )


class MultiviewRequest(BaseGenerationRequest):
    type: Literal['multiview'] = 'multiview'
    front: str = Field(..., description="Front view base64", examples=["<base64 png>"])
    back: str = Field(..., description="Back view base64", examples=["<base64 png>"])
    left: str = Field(..., description="Left view base64", examples=["<base64 png>"])
    right: str = Field(..., description="Right view base64", examples=["<base64 png>"])


class TextureMeshRequest(BaseGenerationRequest):
    """Re-texture an existing mesh (GLB) using either a reference image or a text prompt.

    The mesh is supplied as a base64-encoded ``.glb`` payload; the image (optional)
    and prompt (optional) steer the texture synthesis. At least one of ``image``
    or ``prompt`` must be provided. ``texture`` is implicitly true for this job
    type and is forced to True by the manager before dispatch.
    """
    type: Literal['texture_mesh'] = 'texture_mesh'
    mesh: str = Field(..., description="Base64-encoded GLB of the mesh to re-texture")
    image: Optional[str] = Field(
        None, description="Optional base64 image used as the texture reference"
    )
    prompt: Optional[str] = Field(
        None, min_length=1, description="Optional text prompt used as the texture reference"
    )

    @property
    def has_reference(self) -> bool:
        return bool(self.image) or bool(self.prompt)


# Discriminated Union for polymorphic handling
JobRequest = Annotated[
    Union[TextTo3DRequest, ImageTo3DRequest, MultiviewRequest, TextureMeshRequest],
    Field(discriminator='type'),
]


class JobResponse(BaseModel):
    uid: str
    status: JobStatus
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    file_path: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    error: str
    code: int = 400


class MeshOpsRequest(BaseModel):
    job_uid: str = Field(..., description="UID of the source job to operate on", examples=["abc-123"])
    action: MeshOpsAction = Field(..., description="Mesh operation to apply", examples=[MeshOpsAction.DECIMATE])
    format: str = Field('glb', description="Output mesh format", examples=['glb'])
    ratio: float = Field(0.5, ge=0.01, le=1.0, description="For decimate: target ratio of faces to keep", examples=[0.5, 0.25])
    model_config = ConfigDict(use_enum_values=True)
