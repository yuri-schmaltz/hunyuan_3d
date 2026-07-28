"""Tests for the unified ``GenerationRequest`` schema.

Covers:
- Each input field combination infers the right mode
- Validation rejects empty requests, mesh-only, partial views
- ``to_internal_request()`` produces a valid union member
- Rehydrate path understands both unified and legacy payloads
"""
from __future__ import annotations

import pytest
from hy3dgen.api.schemas import (
    GenerationRequest,
    TextTo3DRequest,
    ImageTo3DRequest,
    MultiviewRequest,
    TextureMeshRequest,
)
from hy3dgen.api.manager import _request_from_payload


class TestInferMode:
    def test_text_only(self):
        r = GenerationRequest(text="a small cube")
        assert r.infer_mode() == "text_to_3d"

    def test_image_only(self):
        r = GenerationRequest(image="<base64>")
        assert r.infer_mode() == "image_to_3d"

    def test_views(self):
        r = GenerationRequest(
            views={"front": "a", "back": "b", "left": "c", "right": "d"},
        )
        assert r.infer_mode() == "multiview"

    def test_mesh_with_text(self):
        r = GenerationRequest(mesh="<glb>", text="wooden")
        assert r.infer_mode() == "texture_mesh"

    def test_mesh_with_image(self):
        r = GenerationRequest(mesh="<glb>", image="<base64>")
        assert r.infer_mode() == "texture_mesh"

    def test_text_wins_over_image(self):
        """If both text and image are set, text wins and the image is ignored."""
        r = GenerationRequest(text="a chair", image="<base64>")
        assert r.infer_mode() == "text_to_3d"


class TestValidation:
    def test_empty_request_rejected(self):
        with pytest.raises(Exception) as exc:
            GenerationRequest()
        assert "at least one of" in str(exc.value).lower()

    def test_mesh_only_rejected(self):
        with pytest.raises(Exception) as exc:
            GenerationRequest(mesh="<glb>")
        assert "reference" in str(exc.value).lower() or "text" in str(exc.value).lower()

    def test_partial_views_rejected(self):
        with pytest.raises(Exception) as exc:
            GenerationRequest(views={"front": "a", "back": "b", "left": "c"})
        assert "right" in str(exc.value).lower() or "views" in str(exc.value).lower()

    def test_extra_fields_rejected(self):
        """The model is ``extra='forbid'`` so typos surface as 422s."""
        with pytest.raises(Exception):
            GenerationRequest(text="x", totally_unknown_field=1)  # type: ignore[call-arg]


class TestToInternalRequest:
    def test_text_to_internal(self):
        r = GenerationRequest(text="a small cube", steps=30)
        internal = r.to_internal_request()
        assert isinstance(internal, TextTo3DRequest)
        assert internal.prompt == "a small cube"
        assert internal.steps == 30

    def test_image_to_internal(self):
        r = GenerationRequest(image="<base64>", remove_background=False)
        internal = r.to_internal_request()
        assert isinstance(internal, ImageTo3DRequest)
        assert internal.image == "<base64>"
        assert internal.remove_background is False

    def test_views_to_internal(self):
        views = {"front": "a", "back": "b", "left": "c", "right": "d"}
        r = GenerationRequest(views=views)
        internal = r.to_internal_request()
        assert isinstance(internal, MultiviewRequest)
        assert internal.front == "a"
        assert internal.right == "d"

    def test_mesh_to_internal(self):
        r = GenerationRequest(mesh="<glb>", image="<ref>")
        internal = r.to_internal_request()
        assert isinstance(internal, TextureMeshRequest)
        assert internal.mesh == "<glb>"
        assert internal.image == "<ref>"

    def test_common_params_propagate(self):
        r = GenerationRequest(text="x", seed=42, octree_resolution=384, face_count=8000)
        internal = r.to_internal_request()
        assert internal.seed == 42
        assert internal.octree_resolution == 384
        assert internal.face_count == 8000


class TestRehydrateFromPayload:
    def test_legacy_payload_with_type_dispatches_correctly(self):
        """Pre-#7 payloads used the discriminated union; we still support them."""
        legacy = {
            "type": "text_to_3d",
            "prompt": "a small cube",
            "seed": 1234,
            "steps": 50,
            "guidance": 5.0,
            "octree_resolution": 256,
            "format": "glb",
            "texture": False,
            "face_count": 40000,
        }
        result = _request_from_payload(legacy)
        assert isinstance(result, TextTo3DRequest)
        assert result.prompt == "a small cube"

    def test_unified_payload_without_type_infers_mode(self):
        """Post-#7 payloads don't have a ``type`` field; we infer from inputs."""
        unified = {"text": "a small cube", "seed": 1234}
        result = _request_from_payload(unified)
        assert isinstance(result, TextTo3DRequest)
        assert result.prompt == "a small cube"

    def test_unified_multiview_payload(self):
        unified = {
            "views": {"front": "a", "back": "b", "left": "c", "right": "d"},
        }
        result = _request_from_payload(unified)
        assert isinstance(result, MultiviewRequest)

    def test_unified_texture_payload(self):
        unified = {"mesh": "<glb>", "image": "<ref>"}
        result = _request_from_payload(unified)
        assert isinstance(result, TextureMeshRequest)
