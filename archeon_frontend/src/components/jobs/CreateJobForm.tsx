import React, { useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { Wand2, Image as ImageIcon, Box, Layers, Loader2 } from 'lucide-react';
import { useJobEvents } from '../../context/useJobEvents';

// Cap user uploads so a stray 500 MB PNG doesn't OOM the tab or the backend.
const MAX_IMAGE_BYTES = 20 * 1024 * 1024; // 20 MB
const MAX_MESH_BYTES = 100 * 1024 * 1024; // 100 MB (GLBs are bigger)
const ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

type ViewKey = 'front' | 'back' | 'left' | 'right';

// Mode chips the user can pick from. The backend infers the actual
// mode from what's filled in, but having a chip helps the user see
// what the form is asking for.
type ModeHint = 'text' | 'image' | 'multiview' | 'texture';

const MODE_OPTIONS: { key: ModeHint; label: string; icon: React.ReactNode; description: string }[] = [
    { key: 'text',     label: 'Text',     icon: <Wand2 size={14} />,      description: 'Generate from a text prompt' },
    { key: 'image',    label: 'Image',    icon: <ImageIcon size={14} />,  description: 'Generate from a single image' },
    { key: 'multiview', label: '4 Views', icon: <Layers size={14} />,     description: 'Generate from 4 view images' },
    { key: 'texture',  label: 'Re-texture', icon: <Box size={14} />,      description: 'Re-texture an existing GLB mesh' },
];

export const CreateJobForm: React.FC = () => {
    const [hint, setHint] = useState<ModeHint>('text');
    const [text, setText] = useState('');
    const [image, setImage] = useState<File | null>(null);
    const [imagePreview, setImagePreview] = useState<string | null>(null);
    const [views, setViews] = useState<Record<ViewKey, File | null>>({
        front: null, back: null, left: null, right: null,
    });
    const [viewPreviews, setViewPreviews] = useState<Record<ViewKey, string | null>>({
        front: null, back: null, left: null, right: null,
    });
    const [mesh, setMesh] = useState<File | null>(null);
    const [refImage, setRefImage] = useState<File | null>(null);
    const [refPreview, setRefPreview] = useState<string | null>(null);

    const [steps, setSteps] = useState(50);
    const [guidance, setGuidance] = useState(5.0);
    const [seed, setSeed] = useState(1234);
    const [texture, setTexture] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    const { notifyJobSubmitted } = useJobEvents();

    // Revoke any previous object URLs when they change or on unmount.
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
            setMessage({ type: 'error', text: `Unsupported image type: ${file.type || 'unknown'}. Use PNG, JPEG, or WebP.` });
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            setMessage({ type: 'error', text: `Image too large. Max ${MAX_IMAGE_BYTES / 1024 / 1024} MB.` });
            return;
        }
        setImageFile(file);
        setMessage(null);
    };

    const handleViewPick = (key: ViewKey) => (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
            setMessage({ type: 'error', text: `View "${key}" must be PNG, JPEG, or WebP.` });
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            setMessage({ type: 'error', text: `View "${key}" too large. Max ${MAX_IMAGE_BYTES / 1024 / 1024} MB.` });
            return;
        }
        setViewFile(key, file);
        setMessage(null);
    };

    const handleMeshPick = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        // We accept any GLB; don't strictly validate MIME since some
        // browsers report empty types for binary blobs.
        if (file.size > MAX_MESH_BYTES) {
            setMessage({ type: 'error', text: `Mesh too large. Max ${MAX_MESH_BYTES / 1024 / 1024} MB.` });
            return;
        }
        setMesh(file);
        setMessage(null);
    };

    const canSubmit = useMemo(() => {
        if (hint === 'text') return text.trim().length > 0;
        if (hint === 'image') return image !== null;
        if (hint === 'multiview') return Object.values(views).every((f) => f !== null);
        if (hint === 'texture') return mesh !== null && (refImage !== null || text.trim().length > 0);
        return false;
    }, [hint, text, image, views, mesh, refImage]);

    const handleSubmit = async () => {
        if (!canSubmit || isSubmitting) return;
        setIsSubmitting(true);
        setMessage(null);
        try {
            const payload: Record<string, unknown> = {
                steps,
                guidance,
                seed,
                texture,
            };
            if (text.trim()) payload.text = text.trim();
            if (image) payload.image = await fileToBase64(image);
            if (refImage) payload.image = await fileToBase64(refImage);
            if (Object.values(views).some((v) => v !== null)) {
                payload.views = {
                    front: views.front ? await fileToBase64(views.front) : '',
                    back:  views.back  ? await fileToBase64(views.back)  : '',
                    left:  views.left  ? await fileToBase64(views.left)  : '',
                    right: views.right ? await fileToBase64(views.right) : '',
                };
            }
            if (mesh) payload.mesh = await fileToBase64(mesh);

            const r = await apiClient.post('/generate', payload);
            setMessage({ type: 'success', text: `Job submitted: ${r.data.uid}` });
            notifyJobSubmitted();
            // Reset just the inputs; keep the advanced settings.
            setText('');
            setImage(null);
            if (imagePreview) URL.revokeObjectURL(imagePreview);
            setImagePreview(null);
            setViews({ front: null, back: null, left: null, right: null });
            Object.values(viewPreviews).forEach((u) => { if (u) URL.revokeObjectURL(u); });
            setViewPreviews({ front: null, back: null, left: null, right: null });
            setMesh(null);
            setRefImage(null);
            if (refPreview) URL.revokeObjectURL(refPreview);
            setRefPreview(null);
        } catch (err) {
            setMessage({
                type: 'error',
                text: err instanceof Error ? err.message : 'Submission failed',
            });
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="bg-archeon-panel border border-gray-700 rounded-lg p-4 mb-4">
            <h3 className="text-lg font-semibold mb-3 text-gray-300">New Job</h3>

            {/* Mode chips — these are just hints. The backend infers the
                actual mode from what fields you fill in. */}
            <div className="flex flex-wrap gap-1 mb-4 text-xs" role="tablist">
                {MODE_OPTIONS.map((opt) => (
                    <button
                        key={opt.key}
                        role="tab"
                        aria-selected={hint === opt.key}
                        onClick={() => { setHint(opt.key); setMessage(null); }}
                        title={opt.description}
                        className={`px-2 py-1 rounded flex items-center gap-1 ${
                            hint === opt.key
                                ? 'bg-archeon-accent text-white'
                                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                        }`}
                    >
                        {opt.icon} {opt.label}
                    </button>
                ))}
            </div>

            {/* Input area — one row per mode, hidden when not selected. */}
            {hint === 'text' && (
                <div className="mb-3">
                    <label className="block text-xs text-gray-400 mb-1">Prompt</label>
                    <textarea
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        placeholder="a small red cube..."
                        className="w-full bg-archeon-bg border border-gray-600 rounded p-2 text-sm text-white"
                        rows={2}
                    />
                    <label className="flex items-center gap-2 text-xs text-gray-400 mt-2">
                        <input
                            type="checkbox"
                            checked={texture}
                            onChange={(e) => setTexture(e.target.checked)}
                        />
                        Also generate texture
                    </label>
                </div>
            )}

            {hint === 'image' && (
                <div className="mb-3">
                    <label className="block text-xs text-gray-400 mb-1">Image</label>
                    <input type="file" accept={ALLOWED_IMAGE_TYPES.join(',')} onChange={handleImagePick} />
                    {imagePreview && <img src={imagePreview} className="mt-2 max-h-32 rounded" alt="preview" />}
                    <label className="flex items-center gap-2 text-xs text-gray-400 mt-2">
                        <input
                            type="checkbox"
                            checked={texture}
                            onChange={(e) => setTexture(e.target.checked)}
                        />
                        Also generate texture
                    </label>
                </div>
            )}

            {hint === 'multiview' && (
                <div className="mb-3 grid grid-cols-2 gap-2">
                    {(['front', 'back', 'left', 'right'] as ViewKey[]).map((key) => (
                        <div key={key}>
                            <label className="block text-xs text-gray-400 mb-1 capitalize">{key}</label>
                            <input type="file" accept={ALLOWED_IMAGE_TYPES.join(',')} onChange={handleViewPick(key)} />
                            {viewPreviews[key] && (
                                <img src={viewPreviews[key]!} className="mt-1 max-h-20 rounded" alt={`${key} preview`} />
                            )}
                        </div>
                    ))}
                </div>
            )}

            {hint === 'texture' && (
                <div className="mb-3 space-y-2">
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">Mesh (.glb)</label>
                        <input type="file" accept=".glb" onChange={handleMeshPick} />
                        {mesh && <span className="text-xs text-gray-500 ml-2">{mesh.name}</span>}
                    </div>
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">Reference image (optional if prompt is set)</label>
                        <input type="file" accept={ALLOWED_IMAGE_TYPES.join(',')} onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f && ALLOWED_IMAGE_TYPES.includes(f.type) && f.size <= MAX_IMAGE_BYTES) {
                                setRefImageFile(f);
                                setMessage(null);
                            } else if (f) {
                                setMessage({ type: 'error', text: 'Bad image (type or size).' });
                            }
                        }} />
                        {refPreview && <img src={refPreview} className="mt-1 max-h-20 rounded" alt="ref preview" />}
                    </div>
                    <div>
                        <label className="block text-xs text-gray-400 mb-1">Or a reference prompt (optional if image is set)</label>
                        <input
                            type="text"
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            placeholder="matte black finish..."
                            className="w-full bg-archeon-bg border border-gray-600 rounded p-2 text-sm text-white"
                        />
                    </div>
                </div>
            )}

            {/* Advanced settings — shared across all modes. */}
            <details className="text-xs text-gray-400 mb-3">
                <summary className="cursor-pointer hover:text-gray-200">Advanced settings</summary>
                <div className="grid grid-cols-3 gap-2 mt-2">
                    <label className="flex flex-col">
                        Steps
                        <input type="number" min={1} max={100} value={steps} onChange={(e) => setSteps(Number(e.target.value))} className="bg-archeon-bg border border-gray-600 rounded p-1 text-white" />
                    </label>
                    <label className="flex flex-col">
                        Guidance
                        <input type="number" min={1} max={20} step={0.1} value={guidance} onChange={(e) => setGuidance(Number(e.target.value))} className="bg-archeon-bg border border-gray-600 rounded p-1 text-white" />
                    </label>
                    <label className="flex flex-col">
                        Seed
                        <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="bg-archeon-bg border border-gray-600 rounded p-1 text-white" />
                    </label>
                </div>
            </details>

            <button
                onClick={handleSubmit}
                disabled={!canSubmit || isSubmitting}
                className="bg-archeon-accent text-white px-4 py-2 rounded disabled:opacity-50 flex items-center gap-2"
            >
                {isSubmitting && <Loader2 size={14} className="animate-spin" />}
                Submit
            </button>
            {message && (
                <div className={`text-xs mt-2 ${message.type === 'error' ? 'text-red-400' : 'text-emerald-400'}`}>
                    {message.text}
                </div>
            )}
        </div>
    );
};

async function fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = reader.result;
            if (typeof result === 'string') {
                // Strip the `data:image/png;base64,` prefix — the backend
                // doesn't need it; the schema accepts both.
                const comma = result.indexOf(',');
                resolve(comma >= 0 ? result.slice(comma + 1) : result);
            } else {
                reject(new Error('FileReader returned non-string'));
            }
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}
