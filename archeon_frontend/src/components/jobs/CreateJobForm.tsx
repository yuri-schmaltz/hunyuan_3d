import React, { useEffect, useState } from 'react';
import { apiClient } from '../../api/client';
import type { JobRequest, JobType } from '../../api/types';
import { Wand2, Image as ImageIcon, Loader2 } from 'lucide-react';
import { useJobEvents } from '../../context/useJobEvents';

// Cap user uploads so a stray 500 MB PNG doesn't OOM the tab or the backend.
const MAX_IMAGE_BYTES = 20 * 1024 * 1024; // 20 MB
const ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

export const CreateJobForm: React.FC = () => {
    const [mode, setMode] = useState<JobType>('text_to_3d');
    const [prompt, setPrompt] = useState('');
    const [selectedImage, setSelectedImage] = useState<File | null>(null);
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    // Multi-view state. The backend requires all four views; users can
    // upload one at a time and the form will block submission until complete.
    type ViewKey = 'front' | 'back' | 'left' | 'right';
    const [mvImages, setMvImages] = useState<Record<ViewKey, File | null>>({
        front: null, back: null, left: null, right: null,
    });
    const [mvPreviews, setMvPreviews] = useState<Record<ViewKey, string | null>>({
        front: null, back: null, left: null, right: null,
    });

    // Advanced settings
    const [steps, setSteps] = useState(50);
    const [guidance, setGuidance] = useState(5.0);
    const [seed, setSeed] = useState(1234);

    const { notifyJobSubmitted } = useJobEvents();

    // Revoke any previous object URL when it changes or on unmount, so blobs
    // aren't pinned in memory until page reload.
    useEffect(() => {
        return () => {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
        };
    }, [previewUrl]);

    const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
            setMessage({ type: 'error', text: `Unsupported image type: ${file.type || 'unknown'}. Use PNG, JPEG, or WebP.` });
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            setMessage({ type: 'error', text: `Image too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max ${MAX_IMAGE_BYTES / 1024 / 1024} MB.` });
            return;
        }
        setSelectedImage(file);
        setPreviewUrl((prev) => {
            if (prev) URL.revokeObjectURL(prev);
            return URL.createObjectURL(file);
        });
        setMessage(null);
    };

    const handleMvImageChange = (view: ViewKey) => (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
            setMessage({ type: 'error', text: `${view}: unsupported type ${file.type || 'unknown'}.` });
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            setMessage({ type: 'error', text: `${view}: too large (${(file.size / 1024 / 1024).toFixed(1)} MB).` });
            return;
        }
        setMvImages((prev) => ({ ...prev, [view]: file }));
        setMvPreviews((prev) => {
            const old = prev[view];
            if (old) URL.revokeObjectURL(old);
            return { ...prev, [view]: URL.createObjectURL(file) };
        });
        setMessage(null);
    };

    // Revoke any multiview object URLs on unmount.
    useEffect(() => {
        const urls = Object.values(mvPreviews).filter((u): u is string => !!u);
        return () => {
            for (const u of urls) URL.revokeObjectURL(u);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const convertToBase64 = (file: File): Promise<string> => {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            reader.onload = () => resolve(reader.result as string);
            reader.onerror = error => reject(error);
        });
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsSubmitting(true);
        setMessage(null);

        try {
            let request: JobRequest;

            if (mode === 'text_to_3d') {
                request = {
                    type: 'text_to_3d',
                    prompt,
                    steps,
                    guidance,
                    seed
                };
            } else if (mode === 'image_to_3d') {
                if (!selectedImage) throw new Error("Please select an image");
                const base64Image = await convertToBase64(selectedImage);
                request = {
                    type: 'image_to_3d',
                    image: base64Image,
                    steps,
                    guidance,
                    seed,
                    remove_background: true
                };
            } else if (mode === 'multiview') {
                // All four views are required by the backend schema.
                const missing = (['front', 'back', 'left', 'right'] as ViewKey[])
                    .filter((v) => !mvImages[v]);
                if (missing.length > 0) {
                    throw new Error(`Missing views: ${missing.join(', ')}`);
                }
                const enc = async (v: ViewKey): Promise<string> => {
                    const f = mvImages[v];
                    if (!f) throw new Error(`Missing view: ${v}`);
                    return convertToBase64(f);
                };
                request = {
                    type: 'multiview',
                    front: await enc('front'),
                    back: await enc('back'),
                    left: await enc('left'),
                    right: await enc('right'),
                    steps,
                    guidance,
                    seed,
                };
            } else {
                return;
            }

            await apiClient.post('/jobs', request);
            setMessage({ type: 'success', text: 'Job submitted successfully!' });
            // Notify sibling components (e.g. JobGallery) so they can refresh
            // immediately instead of waiting for the next poll tick.
            notifyJobSubmitted();
        } catch (err) {
            console.error(err);
            const detail = (err as { response?: { data?: { detail?: string } } })
                ?.response?.data?.detail;
            const message = err instanceof Error ? err.message : 'Submission failed';
            setMessage({ type: 'error', text: detail ?? message });
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="bg-archeon-panel p-6 rounded-lg border border-gray-700">
            <h2 className="text-lg font-semibold mb-6 flex items-center gap-2">
                <Wand2 className="text-archeon-primary" /> NEW GENERATION
            </h2>

            {/* Mode Switcher */}
            <div className="flex gap-2 mb-6 bg-gray-900 p-1 rounded-lg">
                <button
                    onClick={() => setMode('text_to_3d')}
                    className={`flex-1 py-2 text-sm rounded-md transition-colors ${mode === 'text_to_3d' ? 'bg-archeon-primary text-white' : 'text-gray-400 hover:text-white'}`}
                    aria-pressed={mode === 'text_to_3d'}
                >
                    Text to 3D
                </button>
                <button
                    onClick={() => setMode('image_to_3d')}
                    className={`flex-1 py-2 text-sm rounded-md transition-colors ${mode === 'image_to_3d' ? 'bg-archeon-primary text-white' : 'text-gray-400 hover:text-white'}`}
                    aria-pressed={mode === 'image_to_3d'}
                >
                    Image to 3D
                </button>
                <button
                    onClick={() => setMode('multiview')}
                    className={`flex-1 py-2 text-sm rounded-md transition-colors ${mode === 'multiview' ? 'bg-archeon-primary text-white' : 'text-gray-400 hover:text-white'}`}
                    aria-pressed={mode === 'multiview'}
                >
                    Multi-View
                </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
                {/* Inputs */}
                {mode === 'text_to_3d' ? (
                    <div>
                        <label htmlFor="prompt-textarea" className="block text-sm text-gray-400 mb-2">Prompt</label>
                        <textarea
                            id="prompt-textarea"
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            className="w-full bg-gray-800 border border-gray-700 rounded p-3 text-sm focus:border-archeon-primary outline-none"
                            placeholder="A futuristic cyberpunk helmet..."
                            rows={3}
                            required
                        />
                    </div>
                ) : mode === 'image_to_3d' ? (
                    <div>
                        <label className="block text-sm text-gray-400 mb-2">Input Image</label>
                        <div className="border-2 border-dashed border-gray-700 rounded-lg p-8 text-center hover:border-archeon-primary transition-colors cursor-pointer relative">
                            <input
                                type="file"
                                onChange={handleImageChange}
                                accept="image/*"
                                aria-label="Upload reference image"
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                            />
                            {previewUrl ? (
                                <img src={previewUrl} alt="Reference image preview" className="max-h-48 mx-auto rounded" />
                            ) : (
                                <div className="text-gray-500 flex flex-col items-center">
                                    <ImageIcon size={32} className="mb-2" />
                                    <span>Click or Drag to Upload</span>
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-3">
                        <p className="text-sm text-gray-400">
                            Provide one image per view. All four are required.
                        </p>
                        <div className="grid grid-cols-2 gap-3">
                            {(['front', 'back', 'left', 'right'] as ViewKey[]).map((view) => (
                                <div key={view}>
                                    <label
                                        htmlFor={`mv-${view}`}
                                        className="block text-xs text-gray-500 mb-1 capitalize"
                                    >
                                        {view} {mvImages[view] ? '✓' : ''}
                                    </label>
                                    <div className="border-2 border-dashed border-gray-700 rounded-lg p-2 text-center hover:border-archeon-primary transition-colors cursor-pointer relative aspect-square">
                                        <input
                                            id={`mv-${view}`}
                                            type="file"
                                            onChange={handleMvImageChange(view)}
                                            accept="image/*"
                                            aria-label={`Upload ${view} view`}
                                            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                        />
                                        {mvPreviews[view] ? (
                                            <img
                                                src={mvPreviews[view]!}
                                                alt={`${view} view preview`}
                                                className="max-h-32 max-w-full mx-auto rounded object-contain"
                                            />
                                        ) : (
                                            <div className="text-gray-500 flex flex-col items-center justify-center h-full">
                                                <ImageIcon size={20} className="mb-1" />
                                                <span className="text-xs">Click to upload</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Parameters (Condensed) */}
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-xs text-gray-500 mb-1">Steps ({steps})</label>
                        <input
                            type="range" min="10" max="100" value={steps} onChange={(e) => setSteps(Number(e.target.value))}
                            className="w-full accent-archeon-primary"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-gray-500 mb-1">Guidance ({guidance})</label>
                        <input
                            type="range" min="1" max="20" step="0.5" value={guidance} onChange={(e) => setGuidance(Number(e.target.value))}
                            className="w-full accent-archeon-primary"
                        />
                    </div>
                </div>

                {/* Seed */}
                <div>
                    <label className="block text-xs text-gray-500 mb-1">Seed</label>
                    <input
                        type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))}
                        className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-2 text-sm focus:border-archeon-primary outline-none"
                    />
                </div>

                {/* Submit */}
                <button
                    type="submit"
                    disabled={isSubmitting}
                    className="w-full bg-linear-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {isSubmitting ? (
                        <><Loader2 className="animate-spin" size={20} /> Generating...</>
                    ) : (
                        "Generate Asset"
                    )}
                </button>

                {/* Feedback */}
                {message && (
                    <div className={`text-sm p-3 rounded ${message.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
                        {message.text}
                    </div>
                )}
            </form>
        </div>
    );
};
