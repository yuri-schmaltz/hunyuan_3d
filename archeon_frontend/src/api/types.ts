export const JobStatus = {
    QUEUED: "queued",
    PROCESSING: "processing",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled"
} as const;

export type JobStatusType = typeof JobStatus[keyof typeof JobStatus];

export type JobType = 'text_to_3d' | 'image_to_3d';

export type MeshOpsAction = 'decimate' | 'convert';

export interface MeshOpsRequest {
    job_uid: string;
    action: MeshOpsAction;
    format?: 'glb' | 'obj' | 'ply' | 'stl';
    ratio?: number;
}

export interface BaseGenerationRequest {
    seed?: number;
    steps?: number;
    guidance?: number;
    octree_resolution?: number;
    format?: 'glb' | 'obj' | 'ply' | 'stl';
    texture?: boolean;
}

export interface TextTo3DRequest extends BaseGenerationRequest {
    type: 'text_to_3d';
    prompt: string;
}

export interface ImageTo3DRequest extends BaseGenerationRequest {
    type: 'image_to_3d';
    image: string; // Base64
    remove_background?: boolean;
}

export type JobRequest = TextTo3DRequest | ImageTo3DRequest;

export interface JobResponse {
    uid: string;
    status: JobStatusType;
    created_at: string;
    completed_at?: string;
    error?: string;
    file_path?: string;
}

export interface SystemMetrics {
    /** Seconds since the backend process started. */
    uptime_seconds: number;
    /** CPU utilization of the backend process (0–100). */
    cpu_percent: number;
    /** Resident set size of the backend process, in MB. */
    rss_mb: number;
    /** Virtual memory size of the backend process, in MB. */
    vms_mb: number;
    gpu?: {
        name: string;
        memory_allocated_mb: number;
        memory_reserved_mb: number;
        memory_total_mb: number;
    };
}
