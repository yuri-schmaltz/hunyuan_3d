# Hunyuan 3D is licensed under the TENCENT HUNYUAN NON-COMMERCIAL LICENSE AGREEMENT
# except for the third-party components listed below.
# Hunyuan 3D does not impose any additional limitations beyond what is outlined
# in the repsective licenses of these third-party components.
# Users must comply with all terms and conditions of original licenses of these third-party
# components and must ensure that the usage of the third party components adheres to
# all relevant laws and regulations.

# For avoidance of doubts, Hunyuan 3D means the large language models and
# their software and algorithms, including trained model weights, parameters (including
# optimizer states), machine-learning model code, inference-enabling code, training-enabling code,
# fine-tuning enabling code and other elements of the foregoing made publicly available
# by Tencent in accordance with TENCENT HUNYUAN COMMUNITY LICENSE AGREEMENT.

bl_info = {
    "name": "Hunyuan3D-2 Generator",
    "author": "Tencent Hunyuan3D",
    "version": (1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Hunyuan3D-2 3D Generator",
    "description": "Generate/Texturing 3D models from text descriptions or images",
    "category": "3D View",
}
import base64
import os
import tempfile
import threading
import time

import bpy
import requests
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty


class Hunyuan3DProperties(bpy.types.PropertyGroup):
    prompt: StringProperty(
        name="Text Prompt",
        description="Describe what you want to generate",
        default=""
    )
    api_url: StringProperty(
        name="API URL",
        description="URL of the Text-to-3D API service",
        default="http://localhost:8080"
    )
    is_processing: BoolProperty(
        name="Processing",
        default=False
    )
    job_id: StringProperty(
        name="Job ID",
        default=""
    )
    status_message: StringProperty(
        name="Status Message",
        default=""
    )
    # Image path property
    image_path: StringProperty(
        name="Image",
        description="Select an image to upload",
        subtype='FILE_PATH'
    )
    # Octree resolution property
    octree_resolution: IntProperty(
        name="Octree Resolution",
        description="Octree resolution for the 3D generation",
        default=256,
        min=128,
        max=512,
    )
    num_inference_steps: IntProperty(
        name="Number of Inference Steps",
        description="Number of inference steps for the 3D generation",
        default=20,
        min=20,
        max=50
    )
    guidance_scale: FloatProperty(
        name="Guidance Scale",
        description="Guidance scale for the 3D generation",
        default=5.5,
        min=1.0,
        max=10.0
    )
    # Texture generation property
    texture: BoolProperty(
        name="Generate Texture",
        description="Whether to generate texture for the 3D model",
        default=False
    )


class Hunyuan3DOperator(bpy.types.Operator):
    bl_idname = "object.generate_3d"
    bl_label = "Generate 3D Model"
    bl_description = "Generate a 3D model from text description, an image or a selected mesh"

    job_id = ''
    prompt = ""
    api_url = ""
    image_path = ""
    octree_resolution = 256
    num_inference_steps = 20
    guidance_scale = 5.5
    texture = False  # Texture flag
    selected_mesh_base64 = ""
    selected_mesh = None  # Stores reference to the selected mesh object

    thread = None
    task_finished = False

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}

        if self.task_finished:
            print("Threaded task completed")
            self.task_finished = False
            props = context.scene.gen_3d_props
            props.is_processing = False

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        # Start worker thread
        props = context.scene.gen_3d_props
        self.prompt = props.prompt
        self.api_url = props.api_url
        self.image_path = props.image_path
        self.octree_resolution = props.octree_resolution
        self.num_inference_steps = props.num_inference_steps
        self.guidance_scale = props.guidance_scale
        self.texture = props.texture  # Get texture property value

        if self.prompt == "" and self.image_path == "":
            self.report({'WARNING'}, "Please enter some text or select an image first.")
            return {'FINISHED'}

        # Save reference to the selected mesh object
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                self.selected_mesh = obj
                break

        if self.selected_mesh:
            temp_glb_file = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
            temp_glb_file.close()
            bpy.ops.export_scene.gltf(filepath=temp_glb_file.name, use_selection=True)
            with open(temp_glb_file.name, "rb") as file:
                mesh_data = file.read()
            mesh_b64_str = base64.b64encode(mesh_data).decode()
            os.unlink(temp_glb_file.name)
            self.selected_mesh_base64 = mesh_b64_str

        props.is_processing = True

        # Convert relative path to absolute path relative to the Blender file directory
        blend_file_dir = os.path.dirname(bpy.data.filepath)
        self.report({'INFO'}, f"blend_file_dir {blend_file_dir}")
        self.report({'INFO'}, f"image_path {self.image_path}")
        if self.image_path.startswith('//'):
            self.image_path = self.image_path[2:]
            self.image_path = os.path.join(blend_file_dir, self.image_path)

        if self.selected_mesh and self.texture:
            props.status_message = "Texturing Selected Mesh...\n" \
                                   "This may take several minutes depending \n on your GPU power."
        else:
            mesh_type = 'Textured Mesh' if self.texture else 'White Mesh'
            prompt_type = 'Text Prompt' if self.prompt else 'Image'
            props.status_message = f"Generating {mesh_type} with {prompt_type}...\n" \
                                   "This may take several minutes depending \n on your GPU power."

        self.thread = threading.Thread(target=self.generate_model)
        self.thread.start()

        wm = context.window_manager
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def generate_model(self):
        # self.report() and other bpy.ops calls are not thread-safe in Blender;
        # only the worker thread may touch ``requests`` and the filesystem here.
        # UI updates are dispatched back to the main thread via bpy.app.timers.
        base_url = self.api_url.rstrip('/')
        api_root = f"{base_url}/v1"
        job_payload = self._build_job_payload()

        try:
            if job_payload is None:
                self._set_status_error(
                    "No input: provide a prompt, an image, or select a mesh to texture."
                )
                return

            # --- Submit job (async API: returns 202 + uid) ---
            response = requests.post(
                f"{api_root}/jobs",
                json=job_payload,
                timeout=30,
            )
            if response.status_code != 202:
                self._set_status_error(
                    f"Submit failed ({response.status_code}): {response.text[:200]}"
                )
                return

            uid = response.json().get("uid")
            if not uid:
                self._set_status_error("Submit succeeded but no uid in response.")
                return
            self.job_id = uid
            self._set_status_info(f"Job {uid[:8]} queued, waiting for backend…")

            # --- Poll until the job finishes ---
            result = self._poll_job(api_root, uid, timeout_s=900, interval_s=2.0)
            if not result:
                return  # _poll_job already set the error status
            file_path = result.get("file_path")
            if not file_path:
                self._set_status_error("Job completed but server returned no file_path.")
                return

            # --- Download the GLB (the static mount is /files/<basename>) ---
            basename = os.path.basename(file_path)
            with tempfile.TemporaryDirectory() as tmpdir:
                dest = os.path.join(tmpdir, basename)
                with requests.get(f"{base_url}/files/{basename}", stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=64 * 1024):
                            fh.write(chunk)

                # Import on the main thread (Blender bpy is not thread-safe).
                bpy.app.timers.register(
                    lambda: self._import_in_main_thread(dest)
                )

        except requests.RequestException as e:
            self._set_status_error(f"Network error: {e}")
        except Exception as e:
            self._set_status_error(f"Unexpected error: {e}")
        finally:
            self.task_finished = True
            self.selected_mesh_base64 = ""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _build_job_payload(self):
        """Build the discriminated-union body for POST /v1/jobs.

        Returns None if the user provided no usable input.
        """
        common = {
            "steps": self.num_inference_steps,
            "guidance": self.guidance_scale,
            "octree_resolution": self.octree_resolution,
            "seed": 1234,
            "format": "glb",
            "texture": self.texture,
        }
        if self.selected_mesh_base64 and self.texture:
            # Texturing an existing mesh: the backend currently does not have a
            # dedicated mesh-texturing job type, so we fall back to image_to_3d
            # when an image is provided, or report the unsupported case clearly.
            if self.image_path and os.path.exists(self.image_path):
                with open(self.image_path, "rb") as fh:
                    img_b64 = base64.b64encode(fh.read()).decode()
                payload = {"type": "image_to_3d", "image": img_b64, **common}
                return payload
            self._set_status_error(
                "Mesh texturing requires an image path. Text-only mesh texturing is not "
                "supported by the current API."
            )
            return None
        if self.image_path:
            if not os.path.exists(self.image_path):
                self._set_status_error(f"Image not found: {self.image_path}")
                return None
            with open(self.image_path, "rb") as fh:
                img_b64 = base64.b64encode(fh.read()).decode()
            return {"type": "image_to_3d", "image": img_b64, **common}
        if self.prompt:
            return {"type": "text_to_3d", "prompt": self.prompt, **common}
        return None

    def _poll_job(self, api_root, uid, timeout_s, interval_s):
        """Poll GET /v1/jobs/<uid> until completion. Returns the final dict or None."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                r = requests.get(f"{api_root}/jobs/{uid}", timeout=10)
                r.raise_for_status()
                data = r.json()
            except requests.RequestException as e:
                self._set_status_error(f"Polling error: {e}")
                return None

            status = data.get("status")
            if status == "completed":
                return data
            if status == "failed":
                err = data.get("error", "unknown error")
                self._set_status_error(f"Backend reported failure: {err}")
                return None
            if status == "cancelled":
                self._set_status_error("Job was cancelled.")
                return None
            # queued or processing → wait
            self._set_status_info(
                f"Job {uid[:8]} status: {status}…"
            )
            time.sleep(interval_s)
        self._set_status_error(f"Job {uid[:8]} timed out after {timeout_s}s.")
        return None

    def _set_status_info(self, msg):
        # Must be called on the main thread; we're using module-level props
        # so a deferred call avoids races from the worker thread.
        def _apply():
            try:
                props = bpy.context.scene.gen_3d_props
                props.status_message = msg
            except Exception:
                pass
            return None
        bpy.app.timers.register(_apply, first_interval=0.0)

    def _set_status_error(self, msg):
        def _apply():
            try:
                props = bpy.context.scene.gen_3d_props
                props.status_message = f"ERROR: {msg}"
            except Exception:
                pass
            return None
        bpy.app.timers.register(_apply, first_interval=0.0)

    def _import_in_main_thread(self, glb_path):
        try:
            bpy.ops.import_scene.gltf(filepath=glb_path)
            new_obj = (
                bpy.context.selected_objects[0]
                if bpy.context.selected_objects
                else None
            )
            if new_obj and self.selected_mesh and self.texture:
                new_obj.location = self.selected_mesh.location
                new_obj.rotation_euler = self.selected_mesh.rotation_euler
                new_obj.scale = self.selected_mesh.scale
                self.selected_mesh.hide_set(True)
                self.selected_mesh.hide_render = True
        except Exception as e:
            self._set_status_error(f"Import failed: {e}")
        return None


class Hunyuan3DPanel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Hunyuan3D-2'
    bl_label = 'Hunyuan3D-2 3D Generator'

    def draw(self, context):
        layout = self.layout
        props = context.scene.gen_3d_props

        layout.prop(props, "api_url")
        layout.prop(props, "prompt")
        # Image file selector
        layout.prop(props, "image_path")
        # Additional property UI elements
        layout.prop(props, "octree_resolution")
        layout.prop(props, "num_inference_steps")
        layout.prop(props, "guidance_scale")
        # Texture property UI element
        layout.prop(props, "texture")

        row = layout.row()
        row.enabled = not props.is_processing
        row.operator("object.generate_3d")

        if props.is_processing:
            if props.status_message:
                for line in props.status_message.split("\n"):
                    layout.label(text=line)
            else:
                layout.label("Processing...")


classes = (
    Hunyuan3DProperties,
    Hunyuan3DOperator,
    Hunyuan3DPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gen_3d_props = bpy.props.PointerProperty(type=Hunyuan3DProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.gen_3d_props


if __name__ == "__main__":
    register()
