import axios from 'axios';

// API Configuration
// VITE_API_URL is the base server URL (e.g. http://localhost:9000).
// The /v1 path is appended here so individual callers only specify the resource
// (e.g. apiClient.get('/jobs') → http://localhost:9000/v1/jobs).
export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:9000';
export const API_URL = `${BASE_URL}/v1`;

export const apiClient = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});
