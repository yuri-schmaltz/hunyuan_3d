import React from 'react';

interface MeshPreviewProps {
    /** Absolute URL of the GLB file to preview. */
    src: string;
    /** Optional alt text / caption. */
    alt?: string;
    /** Height in CSS units. Defaults to 320px. */
    height?: number | string;
}

/**
 * Renders a GLB in-page using the Google <model-viewer> web component.
 *
 * The script for the custom element is loaded via index.html; this component
 * is purely declarative and falls back to a download link if the web component
 * has not been registered yet (older browsers, ad blockers stripping the CDN).
 */
export const MeshPreview: React.FC<MeshPreviewProps> = ({ src, alt, height = 320 }) => {
    const customElementRegistered = typeof window !== 'undefined'
        && customElements
        && !!customElements.get('model-viewer');

    if (!customElementRegistered) {
        // Graceful fallback: surface a download link so the user is not stuck.
        return (
            <div
                className="bg-gray-800 border border-gray-700 rounded flex items-center justify-center text-center p-6"
                style={{ height }}
            >
                <div className="space-y-2">
                    <p className="text-sm text-gray-400">
                        In-browser 3D preview is not available in this browser.
                    </p>
                    <a
                        href={src}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-archeon-primary underline text-sm"
                    >
                        Download {alt || 'mesh'} instead
                    </a>
                </div>
            </div>
        );
    }

    return (
        <div
            className="bg-gray-800 border border-gray-700 rounded overflow-hidden"
            style={{ height }}
        >
            {/* @ts-expect-error — custom element typed in vite-env.d.ts */}
            <model-viewer
                src={src}
                alt={alt ?? 'Generated 3D mesh'}
                camera-controls
                auto-rotate
                shadow-intensity="1"
                exposure="1"
                style={{ width: '100%', height: '100%' }}
            />
        </div>
    );
};
