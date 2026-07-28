/**
 * CreateJobForm — submit a new generation job.
 *
 * Layout: vertical stack of zones separated by hairline dividers.
 *   1. Header row with the title + submit button on the right.
 *   2. Mode tabs (ModeChips).
 *   3. Mode-specific input area.
 *   4. Advanced settings (collapsed by default).
 *   5. Inline message line for success/error.
 *
 * Same business logic as before — validates file types, encodes
 * base64, posts to /v1/generate, notifies JobEventsProvider — but
 * rendered with the new design system primitives.
 */
import React, { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiClient } from "../../api/client";
import { useJobEvents } from "../../context/useJobEvents";
import {
  Stack,
  Divider,
  Button,
  Field,
  FieldTextarea,
  FieldFile,
  Text,
  Pill,
} from "../../design/primitives";
import { ModeChips, type ModeKey } from "./ModeChips";

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_MESH_BYTES = 100 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];

type ViewKey = "front" | "back" | "left" | "right";

const VIEW_KEYS: ViewKey[] = ["front", "back", "left", "right"];

export const CreateJobForm: React.FC = () => {
  const [hint, setHint] = useState<ModeKey>("text");
  const [text, setText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [views, setViews] = useState<Record<ViewKey, File | null>>({
    front: null,
    back: null,
    left: null,
    right: null,
  });
  const [viewPreviews, setViewPreviews] = useState<Record<ViewKey, string | null>>({
    front: null,
    back: null,
    left: null,
    right: null,
  });
  const [mesh, setMesh] = useState<File | null>(null);
  const [refImage, setRefImage] = useState<File | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);

  const [steps, setSteps] = useState(50);
  const [guidance, setGuidance] = useState(5.0);
  const [seed, setSeed] = useState(1234);
  const [texture, setTexture] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);

  const { notifyJobSubmitted } = useJobEvents();

  useEffect(() => {
    return () => {
      if (imagePreview) URL.revokeObjectURL(imagePreview);
      if (refPreview) URL.revokeObjectURL(refPreview);
      Object.values(viewPreviews).forEach((u) => {
        if (u) URL.revokeObjectURL(u);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setImageFile = (file: File | null) => {
    setImage(file);
    setImagePreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return file ? URL.createObjectURL(file) : null;
    });
  };
  const setRefImageFile = (file: File | null) => {
    setRefImage(file);
    setRefPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return file ? URL.createObjectURL(file) : null;
    });
  };
  const setViewFile = (key: ViewKey, file: File | null) => {
    setViews((prev) => ({ ...prev, [key]: file }));
    setViewPreviews((prev) => {
      if (prev[key]) URL.revokeObjectURL(prev[key]!);
      return { ...prev, [key]: file ? URL.createObjectURL(file) : null };
    });
  };

  const handleImagePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setMessage({
        type: "error",
        text: `Unsupported image type: ${file.type || "unknown"}. Use PNG, JPEG, or WebP.`,
      });
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setMessage({
        type: "error",
        text: `Image too large. Max ${MAX_IMAGE_BYTES / 1024 / 1024} MB.`,
      });
      return;
    }
    setImageFile(file);
    setMessage(null);
  };
  const handleViewPick =
    (key: ViewKey) => (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
        setMessage({
          type: "error",
          text: `View "${key}" must be PNG, JPEG, or WebP.`,
        });
        return;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        setMessage({
          type: "error",
          text: `View "${key}" too large. Max ${MAX_IMAGE_BYTES / 1024 / 1024} MB.`,
        });
        return;
      }
      setViewFile(key, file);
      setMessage(null);
    };
  const handleMeshPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_MESH_BYTES) {
      setMessage({
        type: "error",
        text: `Mesh too large. Max ${MAX_MESH_BYTES / 1024 / 1024} MB.`,
      });
      return;
    }
    setMesh(file);
    setMessage(null);
  };
  const handleRefPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setMessage({ type: "error", text: "Reference must be PNG, JPEG, or WebP." });
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setMessage({
        type: "error",
        text: `Reference too large. Max ${MAX_IMAGE_BYTES / 1024 / 1024} MB.`,
      });
      return;
    }
    setRefImageFile(file);
    setMessage(null);
  };

  const canSubmit = useMemo(() => {
    if (hint === "text") return text.trim().length > 0;
    if (hint === "image") return image !== null;
    if (hint === "multiview")
      return VIEW_KEYS.every((k) => views[k] !== null);
    if (hint === "texture")
      return mesh !== null && (refImage !== null || text.trim().length > 0);
    return false;
  }, [hint, text, image, views, mesh, refImage]);

  const handleSubmit = async () => {
    if (!canSubmit || isSubmitting) return;
    setIsSubmitting(true);
    setMessage(null);
    try {
      const payload: Record<string, unknown> = { steps, guidance, seed, texture };
      if (text.trim()) payload.text = text.trim();
      if (image) payload.image = await fileToBase64(image);
      if (refImage) payload.image = await fileToBase64(refImage);
      if (VIEW_KEYS.some((k) => views[k] !== null)) {
        payload.views = {
          front: views.front ? await fileToBase64(views.front) : "",
          back: views.back ? await fileToBase64(views.back) : "",
          left: views.left ? await fileToBase64(views.left) : "",
          right: views.right ? await fileToBase64(views.right) : "",
        };
      }
      if (mesh) payload.mesh = await fileToBase64(mesh);

      const r = await apiClient.post("/generate", payload);
      setMessage({ type: "success", text: `Job submitted · ${r.data.uid}` });
      notifyJobSubmitted();
      setText("");
      setImage(null);
      if (imagePreview) URL.revokeObjectURL(imagePreview);
      setImagePreview(null);
      setViews({ front: null, back: null, left: null, right: null });
      Object.values(viewPreviews).forEach((u) => {
        if (u) URL.revokeObjectURL(u);
      });
      setViewPreviews({ front: null, back: null, left: null, right: null });
      setMesh(null);
      setRefImage(null);
      if (refPreview) URL.revokeObjectURL(refPreview);
      setRefPreview(null);
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Submission failed",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="bg-bg">
      {/* Header row */}
      <div className="flex items-baseline justify-between gap-4 pb-3">
        <Stack gap={1}>
          <Text
            voice="mono"
            size="2xs"
            tone="muted"
            tracking="widest"
            uppercase
          >
            New job
          </Text>
          <Text voice="display" size="lg" tracking="tight">
            Configure generation
          </Text>
        </Stack>
        <Button
          variant="primary"
          size="md"
          onClick={handleSubmit}
          disabled={!canSubmit || isSubmitting}
        >
          {isSubmitting ? "Submitting…" : "Submit →"}
        </Button>
      </div>
      <Divider />

      {/* Mode tabs */}
      <ModeChips value={hint} onChange={setHint} />

      {/* Mode-specific input area */}
      <div className="py-5">
        <AnimatePresence mode="wait">
          <motion.div
            key={hint}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
          >
            {hint === "text" && (
              <Stack gap={4}>
                <FieldTextarea
                  label="Prompt"
                  placeholder="a small red cube…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={3}
                />
                <TextureToggle texture={texture} onChange={setTexture} />
              </Stack>
            )}
            {hint === "image" && (
              <Stack gap={4}>
                <FieldFile
                  label="Source image"
                  accept={ALLOWED_IMAGE_TYPES.join(",")}
                  onChange={handleImagePick}
                  filename={image?.name ?? null}
                />
                {imagePreview && (
                  <img
                    src={imagePreview}
                    className="max-h-32 border border-border"
                    alt="preview"
                  />
                )}
                <TextureToggle texture={texture} onChange={setTexture} />
              </Stack>
            )}
            {hint === "multiview" && (
              <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                {VIEW_KEYS.map((key) => (
                  <Stack key={key} gap={1}>
                    <FieldFile
                      label={key}
                      accept={ALLOWED_IMAGE_TYPES.join(",")}
                      onChange={handleViewPick(key)}
                      filename={views[key]?.name ?? null}
                    />
                    {viewPreviews[key] && (
                      <img
                        src={viewPreviews[key]!}
                        className="max-h-20 border border-border"
                        alt={`${key} preview`}
                      />
                    )}
                  </Stack>
                ))}
              </div>
            )}
            {hint === "texture" && (
              <Stack gap={4}>
                <FieldFile
                  label="Mesh (.glb)"
                  accept=".glb"
                  onChange={handleMeshPick}
                  filename={mesh?.name ?? null}
                />
                <FieldFile
                  label="Reference image (optional if prompt is set)"
                  accept={ALLOWED_IMAGE_TYPES.join(",")}
                  onChange={handleRefPick}
                  filename={refImage?.name ?? null}
                />
                {refPreview && (
                  <img
                    src={refPreview}
                    className="max-h-20 border border-border"
                    alt="ref preview"
                  />
                )}
                <Field
                  label="Or a reference prompt"
                  placeholder="matte black finish…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              </Stack>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <Divider />
      {/* Advanced settings */}
      <details className="py-3 group">
        <summary className="cursor-pointer list-none flex items-center justify-between">
          <Text
            voice="mono"
            size="2xs"
            tone="muted"
            tracking="widest"
            uppercase
            as="span"
          >
            Advanced
          </Text>
          <Text
            voice="mono"
            size="2xs"
            tone="dim"
            tracking="wider"
            as="span"
            className="group-open:rotate-180 transition-transform"
          >
            ▾
          </Text>
        </summary>
        <div className="grid grid-cols-3 gap-4 pt-4">
          <Field
            label="Steps"
            type="number"
            min={1}
            max={100}
            value={steps}
            onChange={(e) => setSteps(Number(e.target.value))}
          />
          <Field
            label="Guidance"
            type="number"
            min={1}
            max={20}
            step={0.1}
            value={guidance}
            onChange={(e) => setGuidance(Number(e.target.value))}
          />
          <Field
            label="Seed"
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
          />
        </div>
      </details>
      <Divider />

      {/* Status line */}
      <div className="pt-3 h-6 flex items-center">
        {message ? (
          <Pill tone={message.type === "error" ? "danger" : "success"}>
            {message.text}
          </Pill>
        ) : (
          <Text
            voice="mono"
            size="2xs"
            tone="dim"
            tracking="widest"
            uppercase
          >
            Ready
          </Text>
        )}
      </div>
    </section>
  );
};

const TextureToggle: React.FC<{
  texture: boolean;
  onChange: (v: boolean) => void;
}> = ({ texture, onChange }) => (
  <label className="flex items-center gap-3 cursor-pointer select-none">
    <span
      className={
        "inline-block w-9 h-5 rounded-sm border " +
        "transition-colors duration-[120ms] " +
        (texture
          ? "bg-accent border-accent"
          : "bg-surface-2 border-border-strong")
      }
    >
      <span
        className={
          "block w-4 h-4 mt-[1px] bg-bg " +
          "transition-transform duration-[120ms] ease-[cubic-bezier(0.16,1,0.3,1)] " +
          (texture ? "translate-x-[18px]" : "translate-x-[1px]")
        }
      />
    </span>
    <input
      type="checkbox"
      className="sr-only"
      checked={texture}
      onChange={(e) => onChange(e.target.checked)}
    />
    <Text
      voice="mono"
      size="2xs"
      tone="muted"
      tracking="widest"
      uppercase
      as="span"
    >
      Also generate texture
    </Text>
  </label>
);

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === "string") {
        const comma = result.indexOf(",");
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      } else {
        reject(new Error("FileReader returned non-string"));
      }
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
